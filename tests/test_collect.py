import unittest

from tau_intent.collect import collect_blocks, collect_tool_assertions


class TestCollect(unittest.TestCase):
    def test_blocks_come_from_regions_and_attach_why_property(self):
        regions = [{"path": "src/a.py", "start_line": 10, "end_line": 14}]
        tool_events = [
            {
                "name": "edit",
                "arguments": {
                    "path": "src/a.py",
                    "file_path": "src/wrong.py",
                    "why": "corrige",
                    "property": "foo remains pure",
                },
            }
        ]
        blocks = collect_blocks(regions, tool_events)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["path"], "src/a.py")
        self.assertEqual(blocks[0]["size"], 5)
        self.assertTrue(blocks[0]["pending_assertion"])
        self.assertEqual(blocks[0]["why"], "corrige")
        self.assertEqual(blocks[0]["property"], "foo remains pure")

    def test_unparseable_when_raw_arguments_present(self):
        assertions = collect_tool_assertions(
            [
                {"name": "edit", "_raw_arguments": "{\"path\":\"x.py\"}"},
                {"name": "edit", "arguments": {"_raw_arguments": "{\"path\":\"x.py\"}"}},
            ]
        )
        self.assertEqual(len(assertions), 2)
        self.assertTrue(assertions[0]["unparseable"])
        self.assertTrue(assertions[1]["unparseable"])
