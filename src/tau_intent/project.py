"""The v1 selector, declared (P-0). Dumb 1-hop, relevance-only, greedy by ratio.

What this is, in writing, because the contradiction between the algorithms note
(§2.6, submodular / facility location) and the implementation note (§4, plain
greedy) was resolved in favour of the second:

* **Relevance-only.** The score of an entry is ``(gamma ** hops) x recency x
  type``. There is no coverage term, no diversity term, no pairwise similarity,
  and therefore no quadratic memory on the v1 path.
* **Greedy by ratio**, plus the **singleton fallback**: the answer is the better
  of (greedy fill by value/cost) and (the single best entry that fits). That
  pair is what makes the 1/2(1-1/e) guarantee of Khuller-Moss-Naor citable; the
  plain greedy alone has no bound.
* **Repr / Div are ablation keys**, declared in the YAML and off. Turning one on
  is an experiment, not a default.
* The budget cut is **linear**: each entry is costed once, not by re-rendering
  the whole block per candidate (D12).

The YAML is read, never fitted.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from tau_intent.config import load_yaml
from tau_intent.graph import Graph, marcar_onipresentes
from tau_intent.render import Recibo, envelope, render_block, render_entry, render_tudo
from tau_intent.telemetry import TOKENIZER, count_tokens

__all__ = [
    "DEFAULTS",
    "ProjectConfig",
    "expandir",
    "load_project_config",
    "projetar",
    "render_block",
    "render_entry",
    "render_tudo",
]

DEFAULTS_PATH = Path(__file__).with_name("projection.yaml")
FALLBACK_PATH = Path(__file__).parent / "defaults" / "project_v1.yaml"
DEFAULTS = {
    "k": 1,
    "prune_hubs": True,
    "llm_rescue": False,
    "gamma": 0.1,
    "max_nodes": 200,
    "lambda_grau": 3.0,
    "peso_tipo_com_property": 1.0,
    "peso_tipo_sem_property": 0.7,
    "repr": False,
    "div": False,
}


@dataclass(frozen=True)
class ProjectConfig:
    gamma: float = 0.1
    max_nodes: int = 200
    lambda_grau: float = 3.0
    prune_hubs: bool = True
    llm_rescue: bool = False
    up_depth: int = 1
    down_depth: int = 1
    token_budget: int = 1500
    #: Type weight. Was a bare 1.0/0.7 in the scoring line — an undeclared
    #: hyperparameter inside the frozen path (roadmap §5).
    peso_tipo_com_property: float = 1.0
    peso_tipo_sem_property: float = 0.7
    #: Ablation keys. Off in v1; turning one on is an experiment, not a default.
    repr: bool = False
    div: bool = False
    edge_types: tuple[str, ...] = ("contains", "imports", "invokes", "inherits")


def load_project_config(path: Path | None = None) -> ProjectConfig:
    chosen = Path(path) if path is not None else DEFAULTS_PATH
    if not chosen.exists() and FALLBACK_PATH.exists():
        chosen = FALLBACK_PATH
    raw = load_yaml(chosen) if chosen.exists() else {}
    raw = raw.get("projection", raw)
    lam = raw.get("lambda_grau", raw.get("hub_lambda", raw.get("lambda", 3.0)))
    return ProjectConfig(
        gamma=float(raw.get("gamma", 0.1)),
        max_nodes=int(raw.get("max_nodes", 200)),
        lambda_grau=float(lam),
        prune_hubs=bool(raw.get("prune_hubs", True)),
        llm_rescue=bool(raw.get("llm_rescue", False)),
        up_depth=int(raw.get("up_depth", raw.get("k", 1))),
        down_depth=int(raw.get("down_depth", raw.get("k", 1))),
        token_budget=int(raw.get("token_budget", 1500)),
        peso_tipo_com_property=float(raw.get("peso_tipo_com_property", 1.0)),
        peso_tipo_sem_property=float(raw.get("peso_tipo_sem_property", 0.7)),
        repr=bool(raw.get("repr", False)),
        div=bool(raw.get("div", False)),
    )


load_projection_config = load_project_config


def projetar(
    graph: Graph,
    entries: Sequence[Any],
    ancoras: Sequence[str],
    cfg: ProjectConfig,
    orcamento_token: int | None = None,
    *,
    superadas: int = 0,
    summarizer_fn: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Project current intents around the task anchors.

    Selection is deterministic and model-free. ``summarizer_fn`` (arm C's
    ``llm_rescue``) runs strictly **after** the budget cut and only rewrites the
    body of an already-selected block — see ``rescue.py``. Arm B passes nothing
    and never leaves this module.
    """
    budget = cfg.token_budget if orcamento_token is None else orcamento_token
    hubs = marcar_onipresentes(graph, cfg.lambda_grau) if cfg.prune_hubs else set()
    alcancados, nao_expandidos = expandir_com_recibo(
        graph, ancoras, cfg.edge_types, cfg.up_depth, cfg.down_depth, cfg.max_nodes, hubs
    )

    recencias = _recencias(entries)
    scored: list[tuple[float, int, Any]] = []
    for entry in entries:
        node = _node_id(entry)
        if node not in alcancados:
            continue
        why = str(getattr(entry, "why", "") or "")
        prop = str(getattr(entry, "property", "") or "")
        if not (why or prop):
            continue
        tipo = cfg.peso_tipo_com_property if prop else cfg.peso_tipo_sem_property
        peso = (cfg.gamma ** alcancados[node]) * recencias[id(entry)] * tipo
        custo = max(count_tokens(render_entry(entry)), 1)
        scored.append((peso, custo, entry))

    grafo_disponivel = bool(graph.nodes) and all(a in graph.nodes for a in ancoras)
    disponivel = budget - _custo_do_envelope(grafo_disponivel)
    if disponivel <= 0:
        # The envelope alone does not fit. Serving a receipt the agent did not
        # ask for, over budget, would break V4; suppressing it silently would
        # hide that it happened. So: nothing served, and the telemetry says so.
        escolhidas, cortadas = [], [item[2] for item in scored]
        suprimido = True
    else:
        escolhidas, cortadas = _guloso_com_fallback_singleton(scored, disponivel)
        suprimido = False

    recibo = Recibo(
        grafo_disponivel=grafo_disponivel,
        entradas=len(escolhidas),
        saltos_omitidos=len(nao_expandidos),
        superadas_omitidas=int(superadas),
        cortadas_por_orcamento=len(cortadas),
    )
    bloco = (
        ""
        if suprimido
        else render_block(
            escolhidas,
            cortadas,
            grafo_disponivel=recibo.grafo_disponivel,
            saltos_omitidos=recibo.saltos_omitidos,
            superadas_omitidas=recibo.superadas_omitidas,
        )
    )
    tokens_selecionados = count_tokens(bloco)

    tel: dict[str, Any] = {
        "tokenizer": TOKENIZER,
        "selecao": "relevancia-guloso-por-razao+singleton",
        "tokens_selecionados": tokens_selecionados,
        "tokens_served": tokens_selecionados,
        "n_escolhidas": len(escolhidas),
        "n_cortadas": len(cortadas),
        "n_alcancados": len(alcancados),
        "recibo": recibo.as_dict(),
        "bloco_suprimido_por_orcamento": suprimido,
        "llm_rescue": False,
        "repr": cfg.repr,
        "div": cfg.div,
        "servidas": list(escolhidas),
    }

    if cfg.llm_rescue and summarizer_fn is not None and escolhidas:
        contexto = {
            "estourou": bool(cortadas),
            "cortadas": len(cortadas),
            "tokens_selecionados": tokens_selecionados,
            "recibo": recibo.as_dict(),
        }
        bloco, resgate = _aplicar_rescue(
            bloco, escolhidas, recibo, summarizer_fn, contexto
        )
        tel.update(resgate)
        tel["tokens_served"] = count_tokens(bloco)
    return bloco, tel


def _aplicar_rescue(
    bloco: str,
    escolhidas: Sequence[Any],
    recibo: Recibo,
    summarizer_fn: Any,
    contexto: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Hand the selected body to the summarizer. Envelope and receipt are ours.

    Failure is declared and deterministic: fall back to the selected block and
    say so in the telemetry. Silently becoming arm B is the worst outcome — it
    contaminates the contrast without showing up in the report.
    """
    corpo = "\n\n".join(render_entry(entry) for entry in escolhidas)
    base: dict[str, Any] = {
        "llm_rescue": True,
        "llm_rescue_disparou": False,
        "llm_rescue_aplicado": False,
        "llm_rescue_falhou": False,
        "llm_rescue_tokens_antes": count_tokens(bloco),
        "llm_rescue_bloco_servido": bloco,
    }
    try:
        resumo = summarizer_fn(corpo, contexto or {})
    except Exception as exc:  # noqa: BLE001 - failure is data, not a crash
        # Declared and deterministic: degrade to the selected block and say in
        # the manifest that it fell. Silently becoming arm B is the worst
        # outcome, because it contaminates the contrast without appearing.
        return bloco, {
            **base,
            "llm_rescue_disparou": True,
            "llm_rescue_falhou": True,
            "llm_rescue_erro": f"{type(exc).__name__}: {exc}"[:200],
        }
    if resumo is None:
        # Trigger policy said no (gatilho: ao_estourar with nothing cut). Not a
        # failure: C is byte-for-byte B this session, and the frequency of that
        # is what gets reported per arm.
        return bloco, base
    texto = str(getattr(resumo, "texto", resumo) or "")
    if not texto.strip():
        return bloco, {
            **base,
            "llm_rescue_disparou": True,
            "llm_rescue_falhou": True,
            "llm_rescue_erro": "resposta vazia",
        }
    novo = envelope(texto.strip(), recibo)
    tel: dict[str, Any] = {
        **base,
        "llm_rescue_disparou": True,
        "llm_rescue_aplicado": True,
        "llm_rescue_tokens_depois": count_tokens(novo),
        "llm_rescue_bloco_servido": novo,
    }
    for campo in (
        "modelo",
        "prompt_sha256",
        "tokens_entrada",
        "tokens_saida",
        "amostragem",
        "chamadas",
    ):
        valor = getattr(resumo, campo, None)
        if valor is not None:
            tel[f"llm_rescue_{campo}"] = valor
    try:
        from tau_intent.rescue import recall_de_simbolo

        tel["llm_rescue_recall_de_simbolo"] = recall_de_simbolo(bloco, novo)
    except ImportError:  # pragma: no cover
        pass
    return novo, tel


def _custo_do_envelope(grafo_disponivel: bool = True) -> int:
    """Tokens the tagged envelope, the notice and the receipt cost on their own."""
    # The receipt line has a fixed word count whatever the numbers are, so any
    # non-empty receipt gives the same overhead. An empty one renders nothing.
    return count_tokens(envelope("", Recibo(entradas=1, grafo_disponivel=grafo_disponivel)))


def _guloso_com_fallback_singleton(
    scored: Sequence[tuple[float, int, Any]], disponivel: int
) -> tuple[list[Any], list[Any]]:
    """max(greedy by value/cost, best single item that fits) — Khuller-Moss-Naor.

    Linear in the number of candidates: every entry is costed once, before the
    loop, instead of re-rendering the whole block per candidate (D12).
    """
    ordenados = sorted(scored, key=lambda item: (-(item[0] / item[1]), -item[0]))
    escolhidas: list[Any] = []
    cortadas: list[Any] = []
    usado = 0
    valor_guloso = 0.0
    for peso, custo, entry in ordenados:
        if usado + custo <= disponivel:
            escolhidas.append(entry)
            usado += custo
            valor_guloso += peso
        else:
            cortadas.append(entry)

    cabem = [item for item in scored if item[1] <= disponivel]
    if cabem:
        melhor = max(cabem, key=lambda item: item[0])
        if melhor[0] > valor_guloso:
            escolhidas = [melhor[2]]
            cortadas = [item[2] for item in scored if item[2] is not melhor[2]]
    return escolhidas, cortadas


def expandir_com_recibo(
    graph: Graph,
    ancoras: Iterable[str],
    edge_types: Sequence[str],
    up_depth: int,
    down_depth: int,
    max_nodes: int,
    hubs: set[str],
) -> tuple[dict[str, int], set[str]]:
    """BFS from the task anchors. Also returns what it reached but did not expand.

    The second half is the ``saltos`` of the omission receipt: hub-pruned nodes
    and nodes dropped at ``max_nodes`` are reachable context the agent is not
    being shown, and the block says so.
    """
    alcancados: dict[str, int] = {a: 0 for a in ancoras if a}
    nao_expandidos: set[str] = set()
    fila: deque[tuple[str, int]] = deque((a, 0) for a in alcancados)
    types = tuple(edge_types)
    while fila:
        v, h = fila.popleft()
        if h >= max(up_depth, down_depth):
            continue
        for w, _key, direcao in graph.neighbors(v, types):
            limite = up_depth if direcao == "entrada" else down_depth
            if h >= limite or w in alcancados:
                continue
            if len(alcancados) >= max_nodes:
                nao_expandidos.add(w)
                continue
            alcancados[w] = h + 1
            if w in hubs:
                nao_expandidos.add(w)
                continue
            fila.append((w, h + 1))
    return alcancados, nao_expandidos


def expandir(
    graph: Graph,
    ancoras: Iterable[str],
    edge_types: Sequence[str],
    up_depth: int,
    down_depth: int,
    max_nodes: int,
    hubs: set[str],
) -> dict[str, int]:
    alcancados, _ = expandir_com_recibo(
        graph, ancoras, edge_types, up_depth, down_depth, max_nodes, hubs
    )
    return alcancados


def _node_id(entry: Any) -> str:
    anchor = getattr(entry, "anchor", None)
    if anchor is not None and hasattr(anchor, "node_id"):
        return str(anchor.node_id())
    return str(getattr(anchor, "file", "") or "")


def _recencias(entries: Sequence[Any]) -> dict[int, float]:
    """1 / (1 + newer entries on the same file), computed in one pass.

    Recency is among **current** entries that share a file, not a wall clock
    and not per symbol. The newest timestamp on that file scores 1; older
    distinct timestamps score ``1 / (1 + how many newer)``. Ties on the
    timestamp string still tie, deliberately: the store has no finer clock,
    and inventing one here would be calibration.

    Was O(n^2) with a string compare per pair (roadmap §5.5).
    """
    por_arquivo: dict[str, list[tuple[str, int]]] = {}
    for entry in entries:
        file = str(getattr(getattr(entry, "anchor", None), "file", "") or "")
        por_arquivo.setdefault(file, []).append(
            (str(getattr(entry, "ts", "") or ""), id(entry))
        )
    recencias: dict[int, float] = {}
    for itens in por_arquivo.values():
        itens.sort(key=lambda par: par[0], reverse=True)
        mais_novos = 0
        anterior: str | None = None
        vistos = 0
        for ts, key in itens:
            if anterior is not None and ts != anterior:
                mais_novos = vistos
            recencias[key] = 1.0 / (1.0 + mais_novos)
            anterior = ts
            vistos += 1
    return recencias
