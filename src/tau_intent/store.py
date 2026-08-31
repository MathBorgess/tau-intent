import json
from dataclasses import asdict, replace
from pathlib import Path

from tau_intent.model import Anchor, IntentEntry


class IntentStore:
    def __init__(self, root_path: Path):
        self.root_path = Path(root_path)
        self.file_path = self.root_path / "intents.jsonl"

    def append(self, entry: IntentEntry) -> IntentEntry:
        current = self._current_entries()
        supersedes = set(entry.supersedes)
        for existing in current:
            if self._entries_overlap(existing, entry):
                supersedes.add(existing.id)
        stored = replace(entry, supersedes=tuple(sorted(supersedes)))
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(stored), ensure_ascii=False) + "\n")
        return stored

    def query_region(
        self,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[IntentEntry]:
        anchor = Anchor(path=path, start_line=start_line, end_line=end_line)
        return [
            entry
            for entry in self._current_entries()
            if any(candidate.overlaps(anchor) for candidate in entry.anchors)
        ]

    def _read_entries(self) -> list[IntentEntry]:
        if not self.file_path.exists():
            return []
        entries: list[IntentEntry] = []
        with self.file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                data = json.loads(line)
                entries.append(
                    IntentEntry(
                        id=data["id"],
                        why=data["why"],
                        property=data.get("property"),
                        anchors=tuple(Anchor(**anchor) for anchor in data["anchors"]),
                        supersedes=tuple(data.get("supersedes", [])),
                    )
                )
        return entries

    def _current_entries(self) -> list[IntentEntry]:
        entries = self._read_entries()
        superseded_ids = {item for entry in entries for item in entry.supersedes}
        return [entry for entry in entries if entry.id not in superseded_ids]

    @staticmethod
    def _entries_overlap(left: IntentEntry, right: IntentEntry) -> bool:
        return any(a.overlaps(b) for a in left.anchors for b in right.anchors)
