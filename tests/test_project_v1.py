"""Projection YAML defaults. Canonical V4 coverage lives in test_project.py."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from tau_intent.graph import build
from tau_intent.project import DEFAULTS, load_project_config, projetar


@dataclass(frozen=True)
class _Anchor:
    file: str
    symbol: str | None = None

    def node_id(self) -> str:
        return f"{self.file}::{self.symbol}" if self.symbol else self.file


@dataclass(frozen=True)
class _Entry:
    id: str
    ts: str
    anchor: _Anchor
    why: str
    property: str = ""


class TestProjectCompat(unittest.TestCase):
    def test_defaults_llm_rescue_off(self) -> None:
        self.assertFalse(DEFAULTS["llm_rescue"])
        self.assertFalse(load_project_config().llm_rescue)

    def test_projetar_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            graph = build(root)
            entries = [
                _Entry(
                    id="i1",
                    ts="t",
                    anchor=_Anchor("m.py", "f"),
                    why="expõe f",
                    property="f returns int",
                )
            ]
            out, tel = projetar(graph, entries, ["m.py::f"], load_project_config())
            self.assertIsInstance(out, str)
            self.assertFalse(tel["llm_rescue"])
