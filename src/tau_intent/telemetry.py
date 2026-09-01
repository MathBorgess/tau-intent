"""Local token counts and cobertura efetiva. Never a four-chars-per-token heuristic."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

TOKENIZER = "whitespace-v1"


def count_tokens(text: str) -> int:
    """Declared tokenizer for v1: split on whitespace."""
    if not text or not text.strip():
        return 0
    return len(text.split())


def cobertura(ancoras: Sequence[str], entries: Iterable[Any], graph: Any = None) -> float:
    """Fraction of task anchors that have a current intent entry."""
    del graph
    if not ancoras:
        return 0.0
    have = {_node_id(entry) for entry in entries}
    hits = [anchor for anchor in ancoras if anchor in have]
    return len(hits) / len(ancoras)


def _node_id(entry: Any) -> str:
    anchor = getattr(entry, "anchor", None)
    if anchor is not None and hasattr(anchor, "node_id"):
        return str(anchor.node_id())
    return str(getattr(anchor, "file", "") or "")
