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

    def test_symbol_e_domain_sao_descritos_no_schema(self) -> None:
        """The gate validates symbol structurally, so the tool has to ask for it."""
        from tau_intent.tools import RECORD_INTENT_DESCRIPTION, RECORD_INTENT_SCHEMA

        props = RECORD_INTENT_SCHEMA["parameters"] if "parameters" in RECORD_INTENT_SCHEMA else RECORD_INTENT_SCHEMA
        props = props["properties"]
        self.assertIn("description", props["symbol"])
        self.assertIn("AST", props["symbol"]["description"])
        self.assertIn("description", props["domain"])
        self.assertIn("symbol", RECORD_INTENT_DESCRIPTION)

    def test_record_intent_ainda_nao_exige_domain_no_schema(self) -> None:
        """DOMINIO_AUSENTE is a gate code; making it required would turn an
        omission into NAO_PARSEAVEL and collapse two codes into one."""
        from tau_intent.tools import RECORD_INTENT_SCHEMA

        self.assertEqual(RECORD_INTENT_SCHEMA["required"], ["file", "why"])

