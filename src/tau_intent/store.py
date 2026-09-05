"""Append-only JSONL intent store. The only write is append."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from tau_intent.model import Anchor, IntentEntry
from tau_intent.checkpoint import Checkpoint
from tau_intent.adapters import anchor_from_dict


class IntentStore:
    """Append-only. Current vs superseded is derived from ``supersedes``.

    The file never updates a past line. ``append`` writes a new object whose
    ``supersedes`` lists the ids of **current** entries whose anchors overlap
    (same file, overlapping lines). ``current()`` is every stored entry whose
    id is not in that derived set. The recent block is therefore not a rewrite
    of the JSONL: it is a read-time filter. The omitted lines remain lastro
    on disk; the derived view serves ``current()`` and the receipt counts the
    rest (``superadas_omitidas``), without injecting the old prose.
    """

    def __init__(self, path: Path):
        path = Path(path)
        self.path = path / "intents.jsonl" if path.suffix != ".jsonl" else path
        self._entries = self._read()
        self._superseded = {sid for e in self._entries for sid in e.supersedes}

    def current(self) -> list[IntentEntry]:
        return [e for e in self._entries if e.id not in self._superseded]

    def query_region(self, file: str, line_start: int, line_end: int) -> list[IntentEntry]:
        probe = Anchor(
            file=file,
            symbol=None,
            line_start=line_start,
            line_end=line_end,
            blob_sha="",
        )
        return [e for e in self.current() if e.anchor.overlaps(probe)]

    def append(self, nova: IntentEntry) -> IntentEntry:
        sobrepostas = [e.id for e in self.current() if e.anchor.overlaps(nova.anchor)]
        nova = replace(nova, supersedes=tuple(sobrepostas))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            data = asdict(nova)
            if nova.checkpoint is None:
                data.pop("checkpoint")  # legacy records remain byte-compatible
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")
        self._entries.append(nova)
        self._superseded.update(sobrepostas)
        return nova

    def _read(self) -> list[IntentEntry]:
        if not self.path.exists():
            return []
        entries: list[IntentEntry] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                entries.append(_entry_from_dict(json.loads(line)))
        return entries


def _entry_from_dict(data: dict) -> IntentEntry:
    raw_anchor = data["anchor"]
    return IntentEntry(
        id=data["id"],
        ts=data["ts"],
        task_id=data["task_id"],
        anchor=anchor_from_dict(raw_anchor),
        why=data["why"],
        property=data.get("property") or "",
        domain=data.get("domain") or "",
        supersedes=tuple(data.get("supersedes") or ()),
        author=data.get("author", "agent"),
        trigger_log=tuple(data.get("trigger_log") or ()),
        checkpoint=Checkpoint.from_dict(data["checkpoint"]) if data.get("checkpoint") is not None else None,
    )
