"""Graph builder alias. Canonical coverage lives in test_project.py."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tau_intent.graph import build_graph
from tau_intent.graph_builder import GraphBuilder


class TestGraphCompat(unittest.TestCase):
    def test_build_graph_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            graph = build_graph(tmp)
            self.assertIn("a.py::f", graph.nodes)
            self.assertTrue(
                any(attrs.get("kind") == "FunctionDef" for attrs in graph.nodes.values())
            )
            alias = GraphBuilder().build(tmp)
            self.assertIn("a.py", alias.nodes)

    def test_no_exec(self) -> None:
        src = Path("src/tau_intent/graph.py").read_text(encoding="utf-8")
        self.assertNotIn("exec(", ast.dump(ast.parse(src)))
