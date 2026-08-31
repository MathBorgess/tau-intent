"""Supervisor around tau AgentHarness. Four flags, productive-turn cap, last-turn gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from tau_intent.fake_provider import FakeHarness
from tau_intent.render import render_falhas
from tau_intent.telemetry import cobertura, count_tokens

PASSA = "PASSA"
BLOQUEIA = "BLOQUEIA"
ESCALAR = "ESCALAR"
LIBERA = PASSA
PERMITE = PASSA

try:
    from tau_intent.collect import Pending, Region, collect_events, regions_from_diff
    from tau_intent.gate import GateConfig, Veredito, portao
    from tau_intent.tools import catalog
except ImportError:  # PR4 may land before PR3
    from tau_intent._slice4_fallbacks import (  # type: ignore[assignment]
        GateConfig,
        Pending,
        Region,
        Veredito,
        catalog,
        collect_events,
        portao,
        regions_from_diff,
    )

try:
    from tau_intent.store import IntentStore
except ImportError:  # PR4 may land before PR2
    IntentStore = None  # type: ignore[misc, assignment]

try:
    from tau_intent.model import Anchor, IntentEntry
except ImportError:
    Anchor = None  # type: ignore[misc, assignment]
    IntentEntry = None  # type: ignore[misc, assignment]


@dataclass(frozen=True)
class Flags:
    capture: bool
    gate: bool
    project: bool
    serve: bool


@dataclass
class RunResult:
    flags: Flags
    productive_turns: int
    block_turns: int
    verdict: str
    follow_ups: list[str]
    intents_path: Path
    telemetry: dict[str, Any]


def git_diff(workspace: Path) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "diff", "--no-color", "HEAD"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


async def run_task(
    workspace: Path,
    flags: Flags,
    *,
    prompt: str = "implement the task",
    task_id: str = "task",
    max_productive_turns: int | None = 8,
    gate_cfg: GateConfig | None = None,
    harness: Any = None,
    diff: str | list[Region] | None = None,
    symbols: set[str] | None = None,
    store: Any = None,
    gate_fn: Callable[..., Veredito] | None = None,
    project_fn: Callable[..., tuple[str, dict]] | None = None,
) -> RunResult:
    workspace = Path(workspace)
    intents_path = workspace / "intents.jsonl"
    before_lines = _line_count(intents_path)
    gate_cfg = gate_cfg or GateConfig()
    gate_fn = gate_fn or portao

    tools = catalog(capture=flags.capture)
    if harness is None:
        harness = FakeHarness(max_turns=None, tools=tools)
    _assert_tau_max_turns_none(harness)

    bloco = ""
    tel: dict[str, Any] = {"tokenizer": "whitespace-v1"}
    current_entries: list[Any] = []
    if store is None and IntentStore is not None:
        store = IntentStore(workspace)
    if store is not None:
        current_entries = list(store.current())

    if flags.serve:
        if flags.project:
            projetar = project_fn or _try_project
            ancoras = [str(workspace)]
            bloco, proj_tel = projetar(workspace, current_entries, ancoras)
            tel.update(proj_tel)
        elif flags.capture:
            from tau_intent.render import render_tudo as serve_all

            bloco = serve_all(current_entries)
            tel["tokens_served"] = count_tokens(bloco)

    prompt_text = prompt if not bloco else f"{prompt}\n\n{bloco}"

    regions = regions_from_diff(diff if diff is not None else git_diff(workspace))
    collected_events: list[Any] = []
    productive = 0
    blocks = 0
    verdict = "PASSA"
    follow_ups: list[str] = []
    last_empty: Any = None

    async for event in harness.prompt(prompt_text):
        collected_events.append(event)
        if _is_tool_start(event):
            continue
        if not _is_turn_end(event):
            continue
        results = _tool_results(event)
        if results:
            productive += 1
            if max_productive_turns is not None and productive >= max_productive_turns:
                # Keep consuming until the last empty TurnEndEvent if it is already queued
                # in this same script step; otherwise stop. Productive cap does not
                # count follow_up block turns.
                continue
            continue
        last_empty = event
        if not flags.gate:
            verdict = "PASSA"
            break
        pendentes = collect_events(collected_events, regions)
        v = gate_fn(
            regions,
            pendentes,
            symbols or _symbols_from_pending(pendentes),
            gate_cfg,
            blocks,
        )
        verdict = v.tipo
        if v.tipo == "BLOQUEIA":
            blocks += 1
            msg = render_falhas(v.falhas)
            follow_ups.append(msg)
            harness.follow_up(msg)
            continue
        break

    del last_empty
    pendentes = collect_events(collected_events, regions)

    if flags.capture and store is not None:
        _flush_pendentes(store, pendentes, task_id)
    elif not flags.capture:
        after = _line_count(intents_path)
        if after > before_lines:
            raise RuntimeError("capture=off wrote intents.jsonl")

    tel["cobertura_efetiva"] = cobertura(
        [r.path for r in regions],
        store.current() if store is not None else [],
    )
    tel["productive_turns"] = productive
    tel["block_turns"] = blocks
    tel["max_turns_on_tau"] = None
    return RunResult(
        flags=flags,
        productive_turns=productive,
        block_turns=blocks,
        verdict=verdict,
        follow_ups=follow_ups,
        intents_path=intents_path,
        telemetry=tel,
    )


def _flush_pendentes(store: Any, pendentes: dict, task_id: str) -> None:
    if IntentEntry is None or Anchor is None:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for pending in pendentes.values():
        if not isinstance(pending, Pending):
            continue
        if pending.unparseable:
            continue
        if not pending.why and not pending.property:
            continue
        store.append(
            IntentEntry(
                id=str(uuid4()),
                ts=now,
                task_id=task_id,
                anchor=Anchor(
                    file=pending.region.path,
                    symbol=None,
                    line_start=pending.region.line_start,
                    line_end=pending.region.line_end,
                    blob_sha="0" * 40,
                ),
                why=pending.why,
                property=pending.property,
                domain=pending.domain,
            )
        )


def _try_project(workspace: Path, entries: list[Any], ancoras: list[str]) -> tuple[str, dict]:
    try:
        from tau_intent.graph import build
        from tau_intent.project import load_project_config, projetar
    except ImportError:
        return "", {"llm_rescue": False, "tokens_served": 0}
    cfg = load_project_config()
    graph = build(workspace)
    node_ids = list(ancoras)
    for entry in entries:
        anchor = getattr(entry, "anchor", None)
        if anchor is not None:
            node_ids.append(anchor.node_id())
            break
    return projetar(graph, entries, node_ids[:1] or [""], cfg)


def _assert_tau_max_turns_none(harness: Any) -> None:
    cfg = getattr(harness, "config", None)
    max_turns = getattr(cfg, "max_turns", None)
    if max_turns is not None:
        raise ValueError("tau max_turns must be None; cap productive turns in the supervisor")


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _is_turn_end(event: Any) -> bool:
    kind = getattr(event, "type", None) or type(event).__name__
    return kind in {"turn_end", "TurnEndEvent"}


def _is_tool_start(event: Any) -> bool:
    kind = getattr(event, "type", None) or type(event).__name__
    return kind in {"tool_execution_start", "ToolExecutionStartEvent"}


def _tool_results(event: Any) -> list[Any]:
    return list(getattr(event, "tool_results", None) or [])


def _symbols_from_pending(pendentes: dict) -> set[str]:
    names: set[str] = set()
    for pending in pendentes.values():
        prop = getattr(pending, "property", "") or ""
        names.update(part for part in prop.replace(".", " ").split() if part.isidentifier())
    return names
