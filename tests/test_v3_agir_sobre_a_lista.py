"""The agent acts on the gate's list (owner decision after pilot run 09c, 2026-10-09).

Run 09c named every region exactly, and the block loop went on: 33 block turns in arm B
and an ``ESCALAR``. Three causes, three fixes:

1. the message said what was wrong, not what clears it, in Portuguese inside an English
   session; the agent kept editing code. Each line now says: record an intent with this
   file and this symbol;
2. the agent declared ``_raise_or_warn_if_not_fitted`` and the edit was in its inner
   ``wrapper``: a def now covers the defs inside it;
3. one intent listed ``_splitter.pyx`` (no names: not Python) and ``_classes.py`` (names)
   with a symbol, and scoping both files together dropped the ``.pyx``: scoping is now
   file by file, and a file with no observable names is claimed whole.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tau_intent.collect import RESOLVER_V2, Region, collect_events, simbolo_confere
from tau_intent.config import config_hashes, load_gate_config
from tau_intent.fake_provider import FakeHarness, FakeToolStart, FakeTurnEnd
from tau_intent.gate import Falha, portao
from tau_intent.render import render_falhas
from tau_intent.supervisor import Flags, run_task


class TestTheMessageSaysWhatClearsALine(unittest.TestCase):
    def test_each_line_names_the_record_intent_that_clears_it(self):
        msg = render_falhas([
            Falha("AUSENTE", Region("sklearn/pipeline.py", 573, 573, symbol="Pipeline.predict",
                                    resolver=RESOLVER_V2)),
            Falha("AUSENTE", Region("sklearn/pipeline.py", 14, 14, resolver=RESOLVER_V2)),
            Falha("AUSENTE", Region("sklearn/tree/_splitter.pyx", 718, 1026, resolver=None)),
        ])
        header, *lines = msg.splitlines()
        self.assertTrue(header.startswith("The gate blocked this turn"))
        self.assertIn("record_intent, all lines in one call", header)
        self.assertIn("Editing the code again does not clear a line", header)
        self.assertEqual(lines, [
            '- AUSENTE: sklearn/pipeline.py::Pipeline.predict (lines 573-573). No recorded intent covers it. '
            'Record one with file "sklearn/pipeline.py" and symbol "Pipeline.predict".',
            '- AUSENTE: sklearn/pipeline.py (lines 14-14). No recorded intent covers it. '
            'Record one with file "sklearn/pipeline.py" and no symbol (module-level lines).',
            '- AUSENTE: sklearn/tree/_splitter.pyx (lines 718-1026). No recorded intent covers it. '
            'Record one with file "sklearn/tree/_splitter.pyx" and no symbol.',
        ])

    def test_every_gate_code_has_a_remedy(self):
        from tau_intent.config import mensagem_do_portao
        from tau_intent.gate import CODIGOS

        _header, remedios, alvos = mensagem_do_portao()
        self.assertEqual(set(remedios), set(CODIGOS))
        self.assertEqual(set(alvos), {"simbolo", "modulo", "arquivo"})

    def test_the_message_is_a_hashed_prompt(self):
        self.assertIn("prompts/portao-bloqueio-v1.txt", config_hashes())

    def test_the_supervisor_sends_it(self):
        diff = ("diff --git a/src/mod.py b/src/mod.py\n--- a/src/mod.py\n+++ b/src/mod.py\n"
                "@@ -1,0 +1,2 @@\n+def f():\n+    return 1\n")
        write = FakeToolStart(tool_name="write", args={"path": "src/mod.py", "content": "def f():\n    return 1\n"})
        flags = Flags(capture=True, gate=True, project=False, serve=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            harness = FakeHarness([[write, FakeTurnEnd(tool_results=[{"tool_name": "write"}]),
                                    FakeTurnEnd(tool_results=[])],
                                   [FakeTurnEnd(tool_results=[])]], max_turns=None)
            result = asyncio.run(run_task(root, flags, harness=harness, diff=diff, symbols={"f"}))
        self.assertTrue(result.follow_ups)
        self.assertTrue(result.follow_ups[0].startswith("The gate blocked this turn"))
        self.assertIn('Record one with file "src/mod.py" and symbol "f".', result.follow_ups[0])


class TestADefCoversTheDefsInsideIt(unittest.TestCase):
    def test_matching_rule(self):
        self.assertTrue(simbolo_confere("_raise_or_warn_if_not_fitted", "_raise_or_warn_if_not_fitted.wrapper"))
        self.assertTrue(simbolo_confere("fit", "LDA.fit.helper"))
        self.assertTrue(simbolo_confere("LDA.fit", "LDA.fit"))
        self.assertFalse(simbolo_confere("fit", "LDA.partial_fit"))
        self.assertFalse(simbolo_confere("wrapper", "_raise_or_warn_if_not_fitted"))
        self.assertFalse(simbolo_confere("LDA", "QDA.fit"))

    def test_the_gate_passes_an_intent_on_the_outer_function(self):
        region = Region("p.py", 50, 61, symbol="_raise_or_warn_if_not_fitted.wrapper", edited_lines=5,
                        resolver=RESOLVER_V2)
        events = [{"tool_name": "record_intent", "args": {
            "file": "p.py", "symbol": "_raise_or_warn_if_not_fitted", "why": "w", "property": "p", "domain": "d"}}]
        pendentes = collect_events(events, [region])
        known = {"p.py::_raise_or_warn_if_not_fitted", "p.py::_raise_or_warn_if_not_fitted.wrapper",
                 "p.py::wrapper"}
        verdict = portao([region], pendentes, known, load_gate_config(), 0)
        self.assertEqual(verdict.tipo, "PASSA", verdict.falhas)


class TestScopingIsFileByFile(unittest.TestCase):
    def regions(self):
        return [
            Region("sklearn/tree/_splitter.pyx", 718, 760, edited_lines=20, resolver=None),
            Region("sklearn/tree/_classes.py", 100, 110, symbol="BaseDecisionTree.fit", edited_lines=5,
                   resolver=RESOLVER_V2),
            Region("sklearn/tree/_classes.py", 3, 3, edited_lines=1, resolver=RESOLVER_V2),
        ]

    def test_a_file_without_names_is_claimed_whole_by_an_intent_that_lists_it(self):
        """Run 09c, B/task-02: the ``.pyx`` was dropped because ``_classes.py`` had names."""
        regions = self.regions()
        events = [{"tool_name": "record_intent", "args": {
            "files": ["sklearn/tree/_splitter.pyx", "sklearn/tree/_classes.py"], "symbol": "fit",
            "why": "w", "property": "p", "domain": "d"}}]
        pendentes = collect_events(events, regions)
        claimed = {key for key, pending in pendentes.items() if pending.why}
        self.assertIn(regions[0].key(), claimed)       # the .pyx, whole
        self.assertIn(regions[1].key(), claimed)       # BaseDecisionTree.fit, by its last part
        self.assertNotIn(regions[2].key(), claimed)    # a module-level line needs a file-level intent

    def test_the_module_level_line_is_listed_with_its_remedy(self):
        regions = self.regions()
        events = [{"tool_name": "record_intent", "args": {
            "files": ["sklearn/tree/_splitter.pyx", "sklearn/tree/_classes.py"], "symbol": "fit",
            "why": "w", "property": "p", "domain": "d"}}]
        pendentes = collect_events(events, regions)
        known = {"sklearn/tree/_classes.py::BaseDecisionTree.fit", "sklearn/tree/_classes.py::fit"}
        verdict = portao(regions, pendentes, known, load_gate_config(), 0)
        self.assertEqual(verdict.tipo, "BLOQUEIA")
        self.assertEqual([(f.code, f.region.key()) for f in verdict.falhas],
                         [("AUSENTE", regions[2].key())])
        self.assertIn('file "sklearn/tree/_classes.py" and no symbol (module-level lines)',
                      render_falhas(verdict.falhas))


if __name__ == "__main__":
    unittest.main()
