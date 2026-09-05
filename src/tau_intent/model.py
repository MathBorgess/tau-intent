"""Frozen intent record. Current vs superseded is derived, never stored as status."""

from __future__ import annotations

from dataclasses import dataclass, field
from tau_intent.checkpoint import Checkpoint


@dataclass(frozen=True)
class Anchor:
    file: str
    symbol: str | None
    line_start: int
    line_end: int
    blob_sha: str

    def node_id(self) -> str:
        return f"{self.file}::{self.symbol}" if self.symbol else self.file

    def overlaps(self, other: "Anchor") -> bool:
        if not isinstance(other, Anchor) or self.file != other.file:
            return False
        return self.line_start <= other.line_end and other.line_start <= self.line_end


@dataclass(frozen=True)
class IntentEntry:
    id: str
    ts: str
    task_id: str
    anchor: Anchor
    why: str
    property: str
    domain: str
    supersedes: tuple[str, ...] = ()
    author: str = "agent"
    trigger_log: tuple[str, ...] = field(default_factory=tuple)
    checkpoint: Checkpoint | None = None

