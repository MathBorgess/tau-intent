import tempfile
import unittest
from pathlib import Path

from tau_intent.model import Anchor, IntentEntry
from tau_intent.store import IntentStore


def _entry(entry_id: str, file: str, start: int, end: int, **kwargs) -> IntentEntry:
    return IntentEntry(
        id=entry_id,
        ts=kwargs.get("ts", "2026-08-31T00:00:00Z"),
        task_id=kwargs.get("task_id", "t"),
        anchor=Anchor(
            file=file,
            symbol=kwargs.get("symbol"),
            line_start=start,
            line_end=end,
            blob_sha=kwargs.get("blob_sha", "0" * 40),
        ),
        why=kwargs.get("why", "why"),
        property=kwargs.get("property", "prop"),
        domain=kwargs.get("domain", "d"),
    )


class TestIntentStore(unittest.TestCase):
    def test_append_is_append_only_and_writes_two_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = IntentStore(Path(temp_dir))
            first = store.append(_entry("e1", "src/a.py", 1, 3))
            second = store.append(_entry("e2", "src/a.py", 1, 3, why="replacement"))
            self.assertEqual(first.supersedes, ())
            self.assertEqual(second.supersedes, ("e1",))
            content = (Path(temp_dir) / "intents.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(content), 2)
            self.assertNotIn("status", content[0])
            self.assertNotIn("status", content[1])

    def test_v3_synthetic_pairs_query_returns_only_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = IntentStore(Path(temp_dir))
            for i in range(40):
                start = (i * 10) + 1
                end = start + 4
                old = store.append(_entry(f"old-{i}", "src/file.py", start, end, why=f"old {i}"))
                new = store.append(_entry(f"new-{i}", "src/file.py", start, end, why=f"new {i}"))
                self.assertEqual(old.supersedes, ())
                self.assertEqual(new.supersedes, (f"old-{i}",))
            hits = 0
            for i in range(40):
                start = (i * 10) + 1
                end = start + 4
                current = store.query_region("src/file.py", start, end)
                self.assertEqual(len(current), 1)
                self.assertEqual(current[0].id, f"new-{i}")
                hits += 1
            self.assertEqual(hits, 40)
            self.assertEqual(len(store.current()), 40)
            self.assertEqual(len(store._entries), 80)


if __name__ == "__main__":
    unittest.main()
