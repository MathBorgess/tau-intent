import unittest

from tau_intent import tools


class TestTools(unittest.TestCase):
    def test_record_intent_shape(self):
        record = tools.record_intent(
            file="src/x.py",
            symbol="run",
            why="corrige",
            property="run preserves X",
            domain="safety",
        )
        self.assertEqual(record["file"], "src/x.py")
        self.assertEqual(record["symbol"], "run")
        self.assertEqual(record["why"], "corrige")
        self.assertEqual(record["property"], "run preserves X")
        self.assertEqual(record["domain"], "safety")

    def test_schema_uses_path_not_file_path(self):
        self.assertIn("path", tools.WRITE_TOOL_SCHEMA["input_schema"]["properties"])
        self.assertNotIn("file_path", tools.WRITE_TOOL_SCHEMA["input_schema"]["properties"])
        self.assertIn("path", tools.EDIT_TOOL_SCHEMA["input_schema"]["properties"])
        self.assertNotIn("file_path", tools.EDIT_TOOL_SCHEMA["input_schema"]["properties"])

    def test_schema_docstrings_include_origin_sha_placeholder(self):
        self.assertIn("ORIGIN_SHA=<ORIGIN_SHA>", tools.READ_TOOL_SCHEMA["description"])
        self.assertIn("ORIGIN_SHA=<ORIGIN_SHA>", tools.WRITE_TOOL_SCHEMA["description"])
        self.assertIn("ORIGIN_SHA=<ORIGIN_SHA>", tools.EDIT_TOOL_SCHEMA["description"])
        self.assertIn("ORIGIN_SHA=<ORIGIN_SHA>", tools.BASH_TOOL_SCHEMA["description"])
