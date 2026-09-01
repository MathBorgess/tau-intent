import unittest

from tau_intent.collect import collect_events, regions_from_diff
from tau_intent.tools import ORIGIN_SHA, catalog, record_intent, tool_specs


class TestCollect(unittest.TestCase):
    DIFF = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,1 +1,4 @@\n"
        "+def f():\n"
        "+    return 1\n"
    )

    def test_regions_come_from_git_diff(self):
        regions = regions_from_diff(self.DIFF)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].path, "src/mod.py")
        self.assertEqual(regions[0].line_start, 1)

    def test_path_not_file_path(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "write",
                "args": {"file_path": "src/mod.py", "content": "x"},
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertTrue(any(p.unparseable for p in pendentes.values()))

    def test_edit_takes_oldtext_newtext(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "edit",
                "args": {
                    "path": "src/mod.py",
                    "edits": [{"oldText": "a", "newText": "b"}],
                },
            },
            {
                "tool_name": "record_intent",
                "args": {
                    "file": "src/mod.py",
                    "why": "expõe f",
                    "property": "f retorna int",
                    "domain": "demo",
                },
            },
        ]
        pendentes = collect_events(events, regions)
        pending = next(iter(pendentes.values()))
        self.assertFalse(pending.unparseable)
        self.assertEqual(pending.why, "expõe f")
        self.assertEqual(pending.property, "f retorna int")

    def test_v6_raw_arguments_is_unparseable(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "write",
                "args": {"path": "src/mod.py", "content": "x"},
                "_raw_arguments": "{not json",
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertTrue(next(iter(pendentes.values())).unparseable)

    def test_bash_redirect_attaches_to_region(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "bash",
                "args": {"command": "echo hi > src/mod.py", "description": "Writing file"},
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertIn("src/mod.py", {p.region.path for p in pendentes.values()})


class TestTools(unittest.TestCase):
    def test_record_intent_typed(self):
        import asyncio

        result = asyncio.run(
            record_intent("src/a.py", "f", "why", "prop", "domain")
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["anchor"], "src/a.py::f")

    def test_origin_sha_in_copied_schemas(self):
        specs = {spec["name"]: spec for spec in tool_specs(capture=True)}
        for name in ("read", "write", "edit", "bash"):
            self.assertIn(ORIGIN_SHA, specs[name]["description"])
        self.assertIn("path", specs["write"]["parameters"]["properties"])
        self.assertNotIn("file_path", specs["write"]["parameters"]["properties"])
        self.assertEqual(
            set(specs["edit"]["parameters"]["properties"]["edits"]["items"]["properties"]),
            {"oldText", "newText"},
        )

    def test_catalog_record_intent_only_when_capture(self):
        names_a = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=False)]
        names_b = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=True)]
        self.assertNotIn("record_intent", names_a)
        self.assertIn("record_intent", names_b)


if __name__ == "__main__":
    unittest.main()
