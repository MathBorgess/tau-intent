import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from tau_intent.graph import build, marcar_onipresentes
from tau_intent.project import load_project_config, projetar, render_tudo

try:
    from tau_intent.telemetry import TOKENIZER, count_tokens
except ImportError:
    TOKENIZER = "whitespace-v1"

    def count_tokens(text: str) -> int:
        return len(text.split()) if text and text.strip() else 0


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


class TestGraphAndProject(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "core.py").write_text(
            "def target():\n    helper()\n    return 1\n\ndef helper():\n    return 0\n",
            encoding="utf-8",
        )
        (root / "pkg" / "other.py").write_text(
            "from pkg.core import target\n\ndef unused():\n    return target()\n",
            encoding="utf-8",
        )
        (root / "pkg" / "hub.py").write_text(
            "from pkg.core import target, helper\n"
            "from pkg.other import unused\n\n"
            "def a():\n    return target()\n"
            "def b():\n    return helper()\n"
            "def c():\n    return unused()\n",
            encoding="utf-8",
        )

    def test_graph_edge_types_and_hub_pruning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._repo(root)
            graph = build(root)
            self.assertIn("pkg/core.py", graph.nodes)
            self.assertIn("pkg/core.py::target", graph.nodes)
            kinds = {key for _src, _dst, key in _all_edges(graph)}
            self.assertTrue({"contains", "imports", "invokes"} <= kinds)
            hubs = marcar_onipresentes(graph, lam=1.0)
            self.assertTrue(isinstance(hubs, set))

    def test_v4_projection_cuts_tokens_monotonically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._repo(root)
            graph = build(root)
            cfg = load_project_config()
            self.assertEqual(cfg.gamma, 0.1)
            self.assertFalse(cfg.llm_rescue)
            self.assertTrue(cfg.prune_hubs)
            self.assertEqual(cfg.up_depth, 1)

            entries = []
            for i in range(12):
                file = "pkg/core.py" if i < 3 else "pkg/other.py"
                symbol = "target" if i < 3 else "unused"
                entries.append(
                    _Entry(
                        id=f"e{i}",
                        ts=f"2026-08-31T00:{i:02d}:00Z",
                        anchor=_Anchor(file=file, symbol=symbol),
                        why=f"entrada longa de historico sintetico numero {i} " + ("token " * 20),
                        property="target returns int" if i < 3 else "unused wraps target",
                    )
                )
            ancoras = ["pkg/core.py::target", "pkg/core.py"]
            whole = render_tudo(entries)
            tokens_b = count_tokens(whole)
            bloco_c, tel = projetar(graph, entries, ancoras, cfg, orcamento_token=10_000)
            tokens_c = tel["tokens_served"]
            self.assertEqual(tel["tokenizer"], TOKENIZER)
            self.assertFalse(tel["llm_rescue"])
            self.assertLess(tokens_c, tokens_b)
            self.assertGreater(tokens_c, 0)

            served = []
            for budget in (200, 80, 40, 10):
                bloco, t = projetar(graph, entries, ancoras, cfg, orcamento_token=budget)
                served.append(t["tokens_served"])
                self.assertLessEqual(t["tokens_served"], budget)
                self.assertNotIn("CHARS_PER_TOKEN", bloco)
            for earlier, later in zip(served, served[1:]):
                self.assertGreaterEqual(earlier, later)

    def test_yaml_is_read_not_fitted(self):
        cfg = load_project_config()
        self.assertEqual(cfg.max_nodes, 200)
        self.assertEqual(cfg.gamma, 0.1)


def _all_edges(graph):
    seen = []
    for node in graph.nodes:
        for other, key, _direction in graph.neighbors(node):
            seen.append((node, other, key))
    return seen


if __name__ == "__main__":
    unittest.main()
