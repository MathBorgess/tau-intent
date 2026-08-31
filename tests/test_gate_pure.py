"""Gate purity. Canonical coverage lives in test_gate.py."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tau_intent.gate import avaliar, portao


class TestGatePure(unittest.TestCase):
    def test_portao_alias(self) -> None:
        self.assertIs(avaliar, portao)

    def test_no_model_in_gate_module(self) -> None:
        src = Path("src/tau_intent/gate.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(node.module.startswith("tau_agent"))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith("tau"))
