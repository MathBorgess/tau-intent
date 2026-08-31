"""Supervisor loop for tau-intent PR4."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .render import render_falhas
from .telemetry import build_telemetry

try:
    from tau_intent.store import append_intent_jsonl as _append_intent_jsonl  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated PR4 tests
    from ._pr4_local import append_intent_jsonl as _append_intent_jsonl

try:
    from tau_intent.gate import gate_eval as _gate_eval  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated PR4 tests
    from ._pr4_local import gate_eval as _gate_eval

try:
    from tau_intent.collect import collect_intent_from_git_diff as _collect_intent_from_git_diff  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated PR4 tests
    from ._pr4_local import collect_intent_from_git_diff as _collect_intent_from_git_diff


@dataclass(frozen=True)
class Flags:
    capture: bool
    gate: bool
    project: bool
    serve: bool


def _event_name(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("type") or event.get("event") or "")
    return type(event).__name__


def _tool_results(event: Any) -> list[Any] | None:
    if isinstance(event, dict):
        value = event.get("tool_results")
    else:
        value = getattr(event, "tool_results", None)
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return list(value)


def _last_turn_end_event(events: list[Any]) -> Any | None:
    last: Any | None = None
    for event in events:
        if _event_name(event) == "TurnEndEvent" and _tool_results(event) == []:
            last = event
    return last


def _file_signature(path: Path) -> tuple[bool, int]:
    if not path.exists():
        return (False, 0)
    return (True, path.stat().st_size)


def run_supervisor(
    *,
    provider: Any,
    flags: Flags,
    repo_path: str,
    intents_path: str,
    max_productive_turns: int,
    max_gate_block_turns: int = 3,
    gate_eval: Callable[[dict[str, Any] | None], dict[str, Any]] = _gate_eval,
    collect_intent: Callable[..., dict[str, Any] | None] = _collect_intent_from_git_diff,
    append_intent: Callable[[str, dict[str, Any]], None] = _append_intent_jsonl,
) -> dict[str, Any]:
    """Run the supervisor loop. Tau max_turns is always None."""
    session = provider.create_session(max_turns=None, serve=flags.serve, project=flags.project)

    productive_turns = 0
    gate_block_turns = 0
    total_turns = 0

    intents_file = Path(intents_path)
    before_a_signature = _file_signature(intents_file)

    while productive_turns < max_productive_turns:
        events = session.run_turn()
        if not events:
            break

        total_turns += 1
        candidate_intent = collect_intent(repo_path) if flags.capture else None
        terminal_event = _last_turn_end_event(list(events))

        if flags.gate and terminal_event is not None:
            decision = gate_eval(candidate_intent)
            if decision.get("code") == "BLOQUEIA":
                gate_block_turns += 1
                session.follow_up(render_falhas(decision.get("failures", [])))
                if gate_block_turns > max_gate_block_turns:
                    raise RuntimeError("Gate block budget exceeded")
                if not flags.capture and _file_signature(intents_file) != before_a_signature:
                    raise RuntimeError("Arm A wrote intents.jsonl")
                continue

        if flags.capture and candidate_intent is not None:
            append_intent(intents_path, candidate_intent)

        productive_turns += 1

        if not flags.capture and _file_signature(intents_file) != before_a_signature:
            raise RuntimeError("Arm A wrote intents.jsonl")

    return {
        "productive_turns": productive_turns,
        "gate_block_turns": gate_block_turns,
        "total_turns": total_turns,
        "telemetry": build_telemetry(
            total_turns=total_turns,
            productive_turns=productive_turns,
            gate_block_turns=gate_block_turns,
        ),
    }
