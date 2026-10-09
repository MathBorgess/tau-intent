"""The gate names every edited region exactly (owner decision, 2026-10-09).

The SWE-Milestone pilot found the gate asking for names the agent could not
give: a hunk was named by the innermost def around *all* its lines, context
included, with decorators outside the def and bare names only. So an edit of
``@validate_params`` was named by the module, a signature change by the class,
and ``QuadraticDiscriminantAnalysis.fit`` was never ``fit``. Each case here is
one the pilot hit (``B/task-04``, ``B/task-06``).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tau_intent.adapters.code import CodeAdapter, regions_from_diff, resolver_simbolos
from tau_intent.collect import collect_events, simbolo_confere
from tau_intent.config import load_gate_config
from tau_intent.gate import portao
from tau_intent.render import render_falhas

BEFORE = '''import os


def validate_params(spec):
    def wrap(f):
        return f
    return wrap


@validate_params(
    {"y_true": ["array-like"]},
)
def accuracy_score(y_true, y_pred):
    return 1.0


class LDA:
    def fit(self, X):
        return self

    def transform(self, X):
        return X

    def score(self, X):
        return 0


class QDA:
    def fit(self, X):
        return self

    def partial_fit(self, X):
        return self

    def old_helper(self):
        return None
'''

AFTER = '''import os
import warnings


def validate_params(spec):
    def wrap(f):
        return f
    return wrap


@validate_params(
    {"y_true": ["array-like"], "zero_division": ["warn"]},
)
def accuracy_score(y_true, y_pred, zero_division="warn"):
    return 1.0


class LDA:
    def fit(self, X):
        return self

    def fit_transform(self, X):
        return self.fit(X).transform(X)

    def transform(self, X, normalize=True):
        return X

    def score(self, X):
        return 0


class QDA:
    def fit(self, X):
        X = list(X)
        return self

    def partial_fit(self, X):
        return self


def new_function():
    return 2
'''


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout


class Workspace:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")
        (self.root / "m.py").write_text(BEFORE, encoding="utf-8")
        git(self.root, "add", "m.py")
        git(self.root, "commit", "-q", "-m", "seed")
        (self.root / "m.py").write_text(AFTER, encoding="utf-8")
        self.regions = CodeAdapter().effects(self.root)
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()

    def names(self) -> list[str | None]:
        return [region.symbol for region in self.regions]

    def gate(self, intents: list[dict]):
        events = [{"tool_name": "record_intent", "args": intent} for intent in intents]
        pendentes = collect_events(events, self.regions, self.root)
        adapter = CodeAdapter()
        return portao(self.regions, pendentes, adapter.identities(self.regions, self.root),
                      load_gate_config(), 0)


def intent(symbol: str | None) -> dict:
    out = {"file": "m.py", "why": "w", "property": "p", "domain": "d"}
    if symbol is not None:
        out["symbol"] = symbol
    return out


class TestNames(unittest.TestCase):
    def test_every_region_has_the_exact_name_of_its_def(self):
        with Workspace() as ws:
            self.assertEqual(ws.names(), [
                None,                      # import warnings: module level
                "accuracy_score",          # decorator argument + signature
                "LDA.fit_transform",       # a new method
                "LDA.transform",           # its signature, right below
                "QDA.fit",
                "QDA.old_helper",          # removed: keeps its pre-edit name
                "new_function",            # with the blank lines above it
            ])

    def test_the_decorator_belongs_to_the_function(self):
        with Workspace() as ws:
            region = next(r for r in ws.regions if r.symbol == "accuracy_score")
            self.assertEqual((region.line_start, region.line_end), (12, 14))

    def test_context_lines_name_nothing(self):
        """B/task-04: ``_lda.py`` 722-732 was named ``LatentDirichletAllocation``."""
        with Workspace() as ws:
            self.assertNotIn("LDA", ws.names())
            self.assertNotIn("QDA", ws.names())
            fit_transform = next(r for r in ws.regions if r.symbol == "LDA.fit_transform")
            self.assertEqual((fit_transform.line_start, fit_transform.line_end), (22, 23))
            transform = next(r for r in ws.regions if r.symbol == "LDA.transform")
            self.assertEqual((transform.line_start, transform.line_end), (24, 25))

    def test_edited_lines_are_kept_across_the_split(self):
        with Workspace() as ws:
            diff = git(ws.root, "diff", "HEAD")
            antes = sum(r.edited_lines for r in regions_from_diff(diff))
            self.assertEqual(sum(r.edited_lines for r in ws.regions), antes)

    def test_the_resolver_is_idempotent(self):
        with Workspace() as ws:
            again = resolver_simbolos(list(ws.regions), ws.root)
            self.assertEqual([r.symbol for r in again], ws.names())

    def test_a_removed_line_starting_with_two_dashes_is_not_a_file_header(self):
        diff = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
                "@@ -1,2 +1,1 @@\n--- a comment\n select 1\n")
        regions = regions_from_diff(diff)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].edited_lines, 1)


class TestDeclaredSymbols(unittest.TestCase):
    def test_whole_or_last_parts_match_whole_parts_only(self):
        self.assertTrue(simbolo_confere("QDA.fit", "QDA.fit"))
        self.assertTrue(simbolo_confere("fit", "QDA.fit"))
        self.assertTrue(simbolo_confere("m.py::QDA.fit", "QDA.fit"))
        self.assertFalse(simbolo_confere("fit", "QDA.partial_fit"))
        self.assertFalse(simbolo_confere("QDA", "QDA.fit"))
        self.assertFalse(simbolo_confere("", "QDA.fit"))

    def test_the_gate_passes_when_each_def_has_its_intent(self):
        with Workspace() as ws:
            # The import is module level: only a file-level intent (no symbol) names it.
            verdict = ws.gate([intent(None)] + [
                intent(name) for name in ("accuracy_score", "LDA.fit_transform", "transform",
                                          "fit", "QDA.old_helper", "new_function")])
            self.assertEqual(verdict.tipo, "PASSA", verdict.falhas)

    def test_a_method_intent_does_not_cover_its_neighbour(self):
        """B/task-06: one def recorded must leave the next one AUSENTE, by its own name."""
        with Workspace() as ws:
            verdict = ws.gate([intent(name) for name in ("accuracy_score", "LDA.fit_transform",
                                                         "QDA.fit", "QDA.old_helper",
                                                         "new_function")])
            self.assertEqual(verdict.tipo, "BLOQUEIA")
            message = render_falhas(verdict.falhas)
            self.assertIn("AUSENTE: m.py::LDA.transform (linhas 24-25)", message)
            self.assertIn("AUSENTE: m.py (linhas 2-2)", message)
            self.assertNotIn("m.py::LDA ", message)
            self.assertEqual(len(verdict.falhas), 2, message)


class TestViewKeepsWorking(unittest.TestCase):
    def test_a_bare_recall_finds_a_dotted_anchor(self):
        from types import SimpleNamespace

        from tau_intent.recall import RecallService

        anchor = SimpleNamespace(node_id=lambda: "m.py::QDA.fit", file="m.py")
        entry = SimpleNamespace(anchor=anchor)
        service = RecallService.__new__(RecallService)
        found = service._ancoras([], ["fit"], SimpleNamespace(nodes={"m.py::fit": {}}), [entry])
        self.assertIn("m.py::QDA.fit", found)
        self.assertIn("m.py::fit", found)

    def test_the_projection_reaches_an_entry_on_a_dotted_anchor(self):
        from tau_intent.graph import Graph
        from tau_intent.project import no_do_grafo

        graph = Graph()
        graph.add_node("m.py", kind="file")
        graph.add_node("m.py::fit", kind="FunctionDef")
        self.assertEqual(no_do_grafo(graph, "m.py::QDA.fit"), "m.py::fit")
        self.assertEqual(no_do_grafo(graph, "m.py::fit"), "m.py::fit")
        self.assertEqual(no_do_grafo(graph, "m.py"), "m.py")
        self.assertEqual(no_do_grafo(graph, "x.yaml::a.b"), "x.yaml::a.b")


if __name__ == "__main__":
    unittest.main()
