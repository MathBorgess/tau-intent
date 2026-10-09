"""Supervisor around tau AgentHarness. Four flags, productive-turn cap, last-turn gate.

Arms, as decided in H16:

* **A** — no capture, no gate, no derived view.
* **B** — capture + gate + **projected** derived view, ``llm_rescue`` off.
* **C** — B plus ``llm_rescue`` on. That is the *only* difference: the same
  envelope, the same position, the same receipt.

``render_tudo`` — the whole current store, no budget — is no longer on any
arm's path (D1). It stayed an inspection tool in ``render.py``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from tau_intent.collect import (
    Pending,
    Region,
    collect_events,
    regions_from_diff,
    resolver_simbolos,
    simbolos_do_ast,
)
from tau_intent.config import BlocoConfig, load_bloco_config, load_gate_config
from tau_intent.fake_provider import FakeHarness
from tau_intent.gate import GateConfig, Veredito, portao
from tau_intent.model import IntentEntry
from tau_intent.adapters import Adapter, get_adapter
from tau_intent.render import render_falhas
from tau_intent.store import IntentStore
from tau_intent.telemetry import (
    aproveitamento_do_bloco,
    cobertura_de_captura,
    count_tokens,
    latencia_de_captura,
    linha_de_turno,
    resumir_tokens,
    uso_do_provedor,
)
from tau_intent.tools import catalog

class ArmIsolationError(RuntimeError):
    """capture=off wrote the intent log. The arm is not what it claims to be."""


PASSA = "PASSA"
BLOQUEIA = "BLOQUEIA"
ESCALAR = "ESCALAR"
LIBERA = PASSA
PERMITE = PASSA


@dataclass(frozen=True)
class Flags:
    capture: bool
    gate: bool
    project: bool
    serve: bool
    #: Arm C's only knob (H16/H17). Off is arm B. The summariser itself lives
    #: in ``rescue.py``; here it is read, never branched on by arm name.
    llm_rescue: bool = False


@dataclass
class RunResult:
    flags: Flags
    productive_turns: int
    #: P2 of the pre-registration: model turns spent answering a gate block
    #: (every turn between a ``BLOQUEIA`` and the next gate run). ``bloqueios``
    #: counts the verdicts themselves.
    block_turns: int
    verdict: str
    follow_ups: list[str]
    intents_path: Path
    telemetry: dict[str, Any]
    bloco: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)
    bloqueios: int = 0




def montar(
    prompt_base: str,
    enunciado: str,
    bloco: str,
    cfg: BlocoConfig | None = None,
) -> str:
    """Assemble the first user message. Position is declared, not accidental.

    Before this existed the supervisor did ``prompt + "\\n\\n" + bloco`` inline:
    the behaviour already matched H10 (first user message, adjacent to the task
    statement) but by accident — no parameter, no declaration, no test, and
    nothing would have failed if someone moved it into the system prompt.
    """
    cfg = cfg or load_bloco_config()
    partes = [parte for parte in (prompt_base.strip(), enunciado.strip()) if parte]
    corpo = "\n\n".join(partes)
    if not bloco.strip():
        return corpo
    if cfg.posicao == "primeira_mensagem_usuario_apos_enunciado":
        return f"{corpo}\n\n{bloco}"
    if cfg.posicao == "primeira_mensagem_usuario_antes_do_enunciado":
        return f"{bloco}\n\n{corpo}"
    raise ValueError(f"bloco.posicao não declarada: {cfg.posicao!r}")


def ancoras_da_tarefa(
    regions: list[Region],
    graph: Any = None,
    enunciado: str = "",
    explicitas: list[str] | None = None,
) -> list[str]:
    """Anchors of the derived view, in declared order of preference.

    D3: the anchors used to be ``[str(workspace)]`` — a filesystem path, which
    is not a node of the graph. ``expandir`` started from a node that did not
    exist, reached the empty set, and arm C served an empty block on the
    integrated path while every projection unit test passed.

    1. what the caller declared;
    2. the regions this task touches, symbol first, then file;
    3. file node ids literally named in the task statement.
    """
    if explicitas:
        return list(explicitas)
    das_regioes: list[str] = []
    for region in regions:
        node = region.node_id()
        if node not in das_regioes:
            das_regioes.append(node)
        if region.path not in das_regioes:
            das_regioes.append(region.path)
    if das_regioes:
        return das_regioes
    if graph is not None and enunciado:
        tokens = {t.strip(".,;:()[]'\"`") for t in enunciado.split()}
        return sorted(token for token in tokens if token and token in graph.nodes)
    return []


async def run_task(
    workspace: Path,
    flags: Flags,
    *,
    prompt: str = "implement the task",
    prompt_base: str = "",
    task_id: str = "task",
    max_productive_turns: int | None = 8,
    gate_cfg: GateConfig | None = None,
    bloco_cfg: BlocoConfig | None = None,
    harness: Any = None,
    diff: str | list[Region] | None = None,
    symbols: set[str] | None = None,
    ancoras: list[str] | None = None,
    store: Any = None,
    gate_fn: Callable[..., Veredito] | None = None,
    project_fn: Callable[..., tuple[str, dict]] | None = None,
    summarizer_fn: Callable[[str], Any] | None = None,
    alvos_excluidos: list[str] | None = None,
    adapter: Adapter | str = "code",
    checkpoint_source: Callable[[list], Any] | None = None,
    modelo_produtor: str | None = None,
    modelo_consumidor: str | None = None,
    deadline_s: float | None = None,
    on_event: Callable[[Any], None] | None = None,
) -> RunResult:
    # The deadline is the whole attempt's clock: the rescue call that builds the
    # block (arm C) is part of what C costs, so it runs on this clock too.
    clock_start = time.monotonic()
    adapter = get_adapter(adapter) if isinstance(adapter, str) else adapter
    workspace = Path(workspace)
    if store is None:
        store = IntentStore(workspace)
    # The store knows where the log lives: the bench keeps it outside the
    # agent's workspace, so the capture=off guard must watch *that* file.
    intents_path = Path(getattr(store, "path", None) or workspace / "intents.jsonl")
    before_lines = _line_count(intents_path)
    gate_cfg = gate_cfg or load_gate_config()
    bloco_cfg = bloco_cfg or load_bloco_config()
    gate_fn = gate_fn or portao
    if max_productive_turns is not None and max_productive_turns < 1:
        raise ValueError("productive turn cap must be positive or None")

    if flags.llm_rescue and flags.serve and flags.project and summarizer_fn is None:
        # Arm C without a summariser would run as arm B and say nothing. v1 has
        # no live provider (tests carry no API key), so the caller supplies one.
        raise RuntimeError(
            "llm_rescue=on exige summarizer_fn: o braço C precisa de um provedor "
            "declarado, e cair para o braço B em silêncio contamina o contraste"
        )

    if deadline_s is not None and deadline_s <= 0:
        raise ValueError("deadline_s must be positive or None")
    tools = catalog(capture=flags.capture)
    if harness is None:
        harness = FakeHarness(max_turns=None, tools=tools)
    _assert_tau_max_turns_none(harness)
    modelo_consumidor = modelo_consumidor or getattr(harness, "model_id", None) \
        or getattr(getattr(harness, "config", None), "model", None)
    if modelo_consumidor is None and isinstance(harness, FakeHarness):
        modelo_consumidor = "fake-provider-v1"
    modelo_produtor = modelo_produtor or modelo_consumidor
    if not modelo_produtor or not modelo_consumidor:
        raise ValueError("a execução exige modelo_produtor e modelo_consumidor")

    # Regions come first: they are the anchors of the derived view (D3). Their
    # symbols are resolved here, before serving, so the anchor is (file, symbol)
    # and not merely the file — otherwise the projection loses the precision the
    # graph has, at the one moment it matters.
    regions = adapter.effects(workspace, diff)

    from tau_intent.manifest import conferir_resolvedores, cobertura_distribuida
    excluidos = (sorted({r.path for r in regions if r.resolver is None})
                 if alvos_excluidos is None else list(alvos_excluidos))
    conferir_resolvedores(regions, excluidos)
    indisponiveis = []
    tel: dict[str, Any] = {"tokenizer": "whitespace-v1",
                           "edge_types_efetivos": [], "grafo_heterogeneo": False}
    current_entries: list[Any] = []
    if store is not None:
        current_entries = list(store.current())

    bloco = ""
    servidas: list[Any] = []
    rescue_ini = len(getattr(summarizer_fn, "chamadas_log", ()))  # this run's calls start here
    if flags.serve and not flags.project:
        # Under H16 no measured arm serves the whole store: render_tudo left
        # the arms (D1). The flag combination still parses, and it serves
        # nothing rather than silently resurrecting the revoked design.
        tel["serve_sem_projecao"] = True
        tel["tokens_served"] = 0
    elif flags.serve:
        projetar = project_fn or (lambda *args: _projetar_visao_derivada(*args, adapter=adapter, enunciado=prompt))
        bloco, proj_tel = projetar(
            workspace,
            current_entries,
            ancoras_da_tarefa(regions, None, prompt, ancoras),
            flags,
            _superadas(store, current_entries),
            summarizer_fn,
        )
        servidas = list(proj_tel.pop("servidas", []))
        tel.update(proj_tel)
        tel.setdefault("tokens_served", count_tokens(bloco))
    tel["servidas"] = [{"id": e.id, "status": "current"} for e in servidas]
    tel["modelo_produtor"] = modelo_produtor
    tel["modelo_consumidor"] = modelo_consumidor
    tel["bloco_vazio"] = not bloco.strip()

    prompt_text = montar(prompt_base, prompt, bloco, bloco_cfg)
    tel["bloco_posicao"] = bloco_cfg.posicao
    tel["bloco_versao"] = bloco_cfg.versao

    collected_events: list[Any] = []
    productive = 0
    blocks = 0
    verdict = "NAO_AVALIAVEL" if flags.gate else "PASSA"
    tel["gate_avaliado"] = False
    tel["esbarrou_teto"] = False
    follow_ups: list[str] = []

    tel["encerramento"] = "completed"
    turnos: list[dict[str, Any]] = []
    # Rescue calls come first in time: the block is built before the session.
    chamadas_rescue = [dict(c, kind="rescue")
                       for c in list(getattr(summarizer_fn, "chamadas_log", ()))[rescue_ini:]]
    last_was_turn_end = True
    events = harness.prompt(prompt_text).__aiter__()
    try:
        while True:
            remaining = None if deadline_s is None else deadline_s - (time.monotonic() - clock_start)
            if remaining is not None and remaining <= 0:
                tel["encerramento"], verdict = "deadline", "DEADLINE"
                tel["chamada_interrompida"] = not last_was_turn_end
                break
            try:
                # A hung local model must not outlive the cell's clock: the wait for
                # the next event is what the deadline bounds, not only the tools.
                event = await (anext(events) if remaining is None
                               else asyncio.wait_for(anext(events), remaining))
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                tel["encerramento"], verdict = "deadline", "DEADLINE"
                tel["chamada_interrompida"] = True
                break
            last_was_turn_end = _is_turn_end(event)
            if on_event is not None:
                on_event(event)
            # Only the events the collector understands feed it. tau also emits
            # tool_execution_update/_end events that carry ``tool_name`` and no
            # ``args``: handed to the collector they read as malformed capture calls.
            if _is_tool_start(event) or _is_turn_end(event) or isinstance(event, dict):
                collected_events.append(event)
            if _is_tool_start(event):
                continue
            if not _is_turn_end(event):
                continue
            failure = _provider_failure(event)
            if failure is None:
                # One row per provider call that answered. Turns that follow a
                # gate rejection are the blocking budget's, the rest productive.
                turnos.append(linha_de_turno(
                    len(chamadas_rescue) + len(turnos) + 1,
                    "block" if follow_ups else "productive",
                    uso_do_provedor(getattr(event, "message", None)),
                    len(getattr(getattr(event, "message", None), "tool_calls", None)
                        or _tool_results(event)),
                    getattr(getattr(event, "message", None), "timing", None),
                ))
            if failure is not None:
                # tau ends the loop with a TurnEnd whose message has stop_reason
                # error/aborted and no tool results. That is a dead provider, not a
                # finished task: running the gate on it would approve an empty diff.
                tel["erro_de_provedor"] = failure
                tel["encerramento"], verdict = "error", "ERRO"
                break
            if _tool_results(event):
                productive += 1
                if max_productive_turns is not None and productive >= max_productive_turns:
                    tel["esbarrou_teto"] = True
                    tel["encerramento"] = "teto_turnos"
                    verdict = "TETO"
                    break
                continue
            if diff is None:
                regions = adapter.effects(workspace)
                if alvos_excluidos is None:
                    excluidos = sorted({r.path for r in regions if r.resolver is None})
                conferir_resolvedores(regions, excluidos)
            if not getattr(adapter, "observable", True):
                verdict = "NAO_AVALIAVEL"
                break
            if not flags.gate:
                verdict = "PASSA"
                break
            pendentes = adapter.collect(collected_events, regions, workspace)
            v = gate_fn(
                regions,
                pendentes,
                symbols if symbols is not None else adapter.identities(regions, workspace),
                gate_cfg,
                blocks,
            )
            tel["gate_avaliado"] = True
            indisponiveis = list(v.nao_avaliaveis)
            verdict = v.tipo
            if v.tipo == "BLOQUEIA":
                blocks += 1
                msg = render_falhas(v.falhas)
                follow_ups.append(msg)
                harness.follow_up(msg)
                continue
            break
    finally:
        await _close_events(events)

    if diff is None:
        regions = adapter.effects(workspace)
        if alvos_excluidos is None:
            excluidos = sorted({r.path for r in regions if r.resolver is None})
        conferir_resolvedores(regions, excluidos)
    pendentes = adapter.collect(collected_events, regions, workspace)

    checkpoint = checkpoint_source(regions) if checkpoint_source is not None else None
    if checkpoint is not None:
        if checkpoint.changed_targets != tuple(sorted({r.node_id() for r in regions})):
            raise ValueError("checkpoint targets differ from independently observed effects")
    publicar = flags.capture and (not flags.gate or (tel["gate_avaliado"] and verdict == "PASSA"))
    tel["captura_publicada"] = publicar
    # Regions the agent touched and that were not published. This is not a
    # count of intents: a region nobody annotated is in it too (review T3).
    tel["pendencias_nao_publicadas"] = len(pendentes) if flags.capture and not publicar else 0
    a_gravar = _entradas_a_gravar(pendentes) if flags.capture else []
    tel["intencoes_nao_publicadas"] = len(a_gravar) if flags.capture and not publicar else 0
    tel["regioes_sem_intencao"] = sum(
        1 for p in pendentes.values()
        if isinstance(p, Pending) and not p.unparseable and not (p.why or p.property))
    tel["chamadas_record_intent"] = sum(
        1 for e in collected_events if _is_tool_start(e) and _tool_name(e) == "record_intent")
    if publicar and store is not None:
        _flush_pendentes(store, pendentes, task_id, workspace, adapter, checkpoint)
    elif not flags.capture:
        after = _line_count(intents_path)
        if after > before_lines:
            raise ArmIsolationError("capture=off wrote intents.jsonl")

    depois = list(store.current()) if store is not None else []
    tel["cobertura_de_captura"] = cobertura_de_captura(regions, depois)
    tel["cobertura_efetiva"] = tel["cobertura_de_captura"]["estrita"]
    tel["fracao_resolvida"] = tel["cobertura_de_captura"]["fracao_resolvida"]
    tel["denominadores"] = tel["cobertura_de_captura"]["denominadores"]
    tel.update(cobertura_distribuida(regions, depois, indisponiveis, excluidos, adapter))
    if not getattr(adapter, "observable", True):
        from tau_intent.gate import CODIGOS
        tel["modo"] = "degradado-sem-testemunha"
        tel["codigos_nao_avaliaveis"] = [
            {"code": code, "alvo": "*", "detail": "efeito independente indisponível"} for code in CODIGOS]
    from tau_intent.collect import diagnosticos_de_captura
    observation = getattr(adapter, "last_observation", None)
    if diff is None and observation is not None:
        tel["efeitos_nao_rastreados"] = list(observation.untracked)
        tel["efeitos_opacos"] = dict(observation.opaque)
    tel["erros_de_captura"] = diagnosticos_de_captura(collected_events)
    tel["latencia_de_captura"] = latencia_de_captura(pendentes)
    tel["aproveitamento_do_bloco"] = aproveitamento_do_bloco(servidas, regions)
    tel["productive_turns"] = productive
    tel["block_turns"] = sum(1 for turno in turnos if turno["kind"] == "block")
    tel["bloqueios"] = blocks
    tel["max_turns_on_tau"] = None
    amostragem = _amostragem_no_fio(harness)
    tel["amostragem"] = amostragem
    # Outcome tokens (Q3) come from provider usage per call, never from the
    # whitespace counter that sizes the block. Rescue calls are read at the end:
    # a rejected rewrite is in the log too, and it cost the model all the same.
    chamadas_rescue = [dict(c, kind="rescue")
                       for c in list(getattr(summarizer_fn, "chamadas_log", ()))[rescue_ini:]]
    for ordem, chamada in enumerate(chamadas_rescue, start=1):
        chamada["turn_index"] = ordem
    tel["turnos"] = chamadas_rescue + turnos
    tel["tokens"] = resumir_tokens(
        turnos, chamadas_rescue, chamada_interrompida=bool(tel.get("chamada_interrompida")))
    from tau_intent.manifest import manifest_da_execucao
    return RunResult(
        flags=flags,
        productive_turns=productive,
        block_turns=tel["block_turns"],
        bloqueios=blocks,
        verdict=verdict,
        follow_ups=follow_ups,
        intents_path=intents_path,
        telemetry=tel,
        bloco=bloco,
        manifest=manifest_da_execucao(
            flags, tel,
            temperatura_configurada=amostragem.get("temperature"),
            amostragem_conferida_no_fio=bool(amostragem.get("conferida_no_fio")),
        ),
    )


def _superadas(store: Any, correntes: list[Any]) -> int:
    """Entries the store holds that the current view does not serve.

    Feeds the ``superadas omitidas`` half of the block receipt (P-1/D9): the
    agent is told that older intent exists for these regions and is not being
    shown, which is different from there being none.
    """
    todas = getattr(store, "_entries", None)
    if todas is None:
        return 0
    return max(len(todas) - len(correntes), 0)


def _projetar_visao_derivada(
    workspace: Path,
    entries: list[Any],
    ancoras: list[str],
    flags: Flags,
    superadas: int = 0,
    summarizer_fn: Callable[[str], Any] | None = None,
    *, adapter: Adapter | None = None, enunciado: str = "",
) -> tuple[str, dict]:
    """Both measured arms project (H16). The knob that separates them is llm_rescue."""
    from dataclasses import replace

    from tau_intent.project import load_project_config, projetar

    cfg = load_project_config()
    if flags.llm_rescue != cfg.llm_rescue:
        cfg = replace(cfg, llm_rescue=flags.llm_rescue)
    adapter = adapter or get_adapter("code")
    cfg = replace(cfg, edge_types=adapter.edge_types)
    graph = adapter.neighbourhood(workspace)
    if not ancoras:
        ancoras = ancoras_da_tarefa([], graph, enunciado)
    if not ancoras:
        return "", {
            "llm_rescue": cfg.llm_rescue,
            "tokens_served": 0,
            "ancoras": [],
            "ancoras_vazias": True,
        }
    bloco, tel = projetar(
        graph,
        entries,
        ancoras,
        cfg,
        superadas=superadas,
        summarizer_fn=summarizer_fn,
    )
    tel["edge_types_efetivos"] = sorted({key for edges in graph._out.values() for _,key in edges})
    tel["grafo_heterogeneo"] = len(tel["edge_types_efetivos"]) > 1
    tel["ancoras"] = list(ancoras)
    tel["ancoras_vazias"] = False
    return bloco, tel


def _entradas_a_gravar(pendentes: dict) -> list[Pending]:
    """The entries a publication writes: one per decision, not one per hunk.

    Hunks of one AST symbol that carry the same why/property/domain are one
    decision and become one entry spanning them (review T8); before, one call
    over N hunks wrote N identical entries and the block served every copy.
    A region without a symbol has no identity to merge on and stays as it is,
    so a file-level span never grows over unrelated lines.
    """
    grupos: dict[tuple, list[Pending]] = {}
    soltas: list[Pending] = []
    for pending in pendentes.values():
        if not isinstance(pending, Pending) or pending.unparseable:
            continue
        if not pending.why and not pending.property:
            continue
        region = pending.region
        if isinstance(region, Region) and region.symbol:
            chave = (region.path, region.symbol, pending.why, pending.property, pending.domain)
            grupos.setdefault(chave, []).append(pending)
        else:
            soltas.append(pending)
    unidas: list[Pending] = []
    for grupo in grupos.values():
        if len(grupo) == 1:
            unidas.append(grupo[0])
            continue
        primeira = grupo[0]
        regioes = [p.region for p in grupo]
        editadas = [r.edited_lines for r in regioes]
        span = replace(
            primeira.region,
            line_start=min(r.line_start for r in regioes),
            line_end=max(r.line_end for r in regioes),
            size=0,
            edited_lines=None if any(e is None for e in editadas) else sum(editadas),
        )
        span.size = max(span.line_end - span.line_start + 1, 0)
        unidas.append(replace(primeira, region=span,
                              trigger_log=[n for p in grupo for n in p.trigger_log],
                              claimed_regions=len(grupo)))
    return unidas + soltas


def _flush_pendentes(store: Any, pendentes: dict, task_id: str, workspace: Path,
                     adapter: Adapter | None = None, checkpoint: Any = None) -> None:
    adapter = adapter or get_adapter("code")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for pending in _entradas_a_gravar(pendentes):
        store.append(
            IntentEntry(
                id=str(uuid4()),
                ts=now,
                task_id=task_id,
                anchor=adapter.anchor(pending, workspace),
                why=pending.why,
                property=pending.property,
                domain=pending.domain,
                trigger_log=tuple(pending.trigger_log),
                checkpoint=checkpoint,
            )
        )




def _assert_tau_max_turns_none(harness: Any) -> None:
    cfg = getattr(harness, "config", None)
    max_turns = getattr(cfg, "max_turns", None)
    if max_turns is not None:
        raise ValueError("tau max_turns must be None; cap productive turns in the supervisor")


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _amostragem_no_fio(harness: Any) -> dict[str, Any]:
    """What the request bodies carried, read from the wire log of the provider.

    A harness without a wire log (the fake one) has nothing to verify, and
    says so: ``conferida_no_fio`` stays False instead of claiming a check.
    """
    wire = getattr(harness, "wire", None)
    return wire.report() if wire is not None else {"conferida_no_fio": False}


def _provider_failure(event: Any) -> str | None:
    """Reason when a TurnEnd closes a failed provider call, else None."""
    message = getattr(event, "message", None)
    if getattr(message, "stop_reason", None) in {"error", "aborted"}:
        return str(getattr(message, "error_message", None) or message.stop_reason)
    return None


async def _close_events(events: Any) -> None:
    """Close the harness stream so a harness that stopped early can run again."""
    closer = getattr(events, "aclose", None)
    if closer is not None:
        await closer()


def _is_turn_end(event: Any) -> bool:
    kind = getattr(event, "type", None) or type(event).__name__
    return kind in {"turn_end", "TurnEndEvent"}


def _is_tool_start(event: Any) -> bool:
    kind = getattr(event, "type", None) or type(event).__name__
    return kind in {"tool_execution_start", "ToolExecutionStartEvent"}


def _tool_name(event: Any) -> str:
    return str(getattr(event, "tool_name", None) or getattr(event, "toolName", None)
               or (event.get("tool_name") if isinstance(event, dict) else "") or "")


def _tool_results(event: Any) -> list[Any]:
    return list(getattr(event, "tool_results", None) or [])


# Legacy callers may still request these helpers; implementation lives in code.
def git_diff(workspace):
    from tau_intent.adapters.code import git_diff as implementation
    return implementation(workspace)


def _blob_sha(path):
    from tau_intent.adapters.code import _blob_sha as implementation
    return implementation(path)
