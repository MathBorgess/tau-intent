"""Tool catalog facts. Canonical coverage also lives in test_collect.py."""

from __future__ import annotations

import asyncio
import inspect
import unittest

from tau_intent.tools import (
    CATALOG,
    ORIGIN_SHA,
    WRITE_TOOL_SCHEMA,
    catalog,
    record_intent,
)


class TestTools(unittest.TestCase):
    def test_origin_sha_is_commit(self) -> None:
        self.assertNotIn("<", ORIGIN_SHA)
        self.assertEqual(len(ORIGIN_SHA), 40)
        self.assertIn(ORIGIN_SHA, WRITE_TOOL_SCHEMA["description"])

    def test_schema_uses_path_not_file_path(self) -> None:
        self.assertIn("path", WRITE_TOOL_SCHEMA["parameters"]["properties"])
        self.assertNotIn("file_path", WRITE_TOOL_SCHEMA["parameters"]["properties"])
        for name in ("read", "write", "edit", "bash"):
            self.assertNotIn("file_path", str(CATALOG[name].parameters))

    def test_record_intent_is_async(self) -> None:
        self.assertTrue(inspect.iscoroutinefunction(record_intent))
        result = asyncio.run(record_intent("src/x.py", "run", "expõe run", "run preserves X", "safety"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["anchor"], "src/x.py::run")

    def test_catalog_record_intent_only_when_capture(self) -> None:
        names_a = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=False)]
        names_b = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=True)]
        self.assertNotIn("record_intent", names_a)
        self.assertIn("record_intent", names_b)
