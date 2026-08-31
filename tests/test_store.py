import tempfile
import unittest
from pathlib import Path

from tau_intent.model import Anchor, IntentEntry
from tau_intent.store import IntentStore


class TestIntentStore(unittest.TestCase):
    def test_append_is_append_only_and_writes_two_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = IntentStore(root)
            anchor = Anchor(path="src/a.py", start_line=1, end_line=3)

            first = store.append(
                IntentEntry(
                    id="e1",
                    why="first",
                    property="p",
                    anchors=(anchor,),
                )
            )
            second = store.append(
                IntentEntry(
                    id="e2",
                    why="second",
                    property="p",
                    anchors=(anchor,),
                )
            )

            self.assertEqual(first.supersedes, ())
            self.assertEqual(second.supersedes, ("e1",))

            content = (root / "intents.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(content), 2)

    def test_v3_synthetic_pairs_query_returns_only_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = IntentStore(root)

            for i in range(40):
                start = (i * 10) + 1
                end = start + 4
                anchor = Anchor(path="src/file.py", start_line=start, end_line=end)
                old_id = f"old-{i}"
                new_id = f"new-{i}"

                old_entry = store.append(
                    IntentEntry(
                        id=old_id,
                        why=f"old {i}",
                        property=f"prop-{i}",
                        anchors=(anchor,),
                    )
                )
                new_entry = store.append(
                    IntentEntry(
                        id=new_id,
                        why=f"new {i}",
                        property=f"prop-{i}",
                        anchors=(anchor,),
                    )
                )

                self.assertEqual(old_entry.supersedes, ())
                self.assertEqual(new_entry.supersedes, (old_id,))

            for i in range(40):
                start = (i * 10) + 1
                end = start + 4
                current = store.query_region("src/file.py", start, end)
                self.assertEqual(len(current), 1)
                self.assertEqual(current[0].id, f"new-{i}")


if __name__ == "__main__":
    unittest.main()
