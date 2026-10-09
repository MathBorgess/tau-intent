"""Measurement and message fixes found by the frontier review (2026-10-09).

T3  ``pendencias_nao_publicadas`` counted touched regions, not intents. The
    telemetry now says how many intents were discarded and how many regions
    never had one.
T4  The gate's follow-up named only the file, once per region. It now names
    ``file::symbol`` and the lines, once per identity.
T6b ``block_turns`` counted gate verdicts while the turn rows counted turns.
    It now counts turns (P2); ``bloqueios`` counts verdicts.
T8  One record_intent over N hunks of one symbol became N identical entries,
    and the block served them all.
T9  ``aproveitamento_do_bloco`` matched by file, so in a one-file host every
    served entry counted as reused.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from dataclasses import replace

from tau_intent.collect import Pending, Region
from tau_intent.config import load_supervisor_config
from tau_intent.fake_provider import FakeHarness, FakeToolStart, FakeTurnEnd
from tau_intent.gate import Falha
from tau_intent.graph import Graph
from tau_intent.project import load_project_config, projetar
from tau_intent.render import render_falhas
from tau_intent.store import IntentStore
from tau_intent.supervisor import Flags, _flush_pendentes, run_task
from tau_intent.telemetry import aproveitamento_do_bloco

DIFF = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
)
B = Flags(capture=True, gate=True, project=False, serve=False)
WRITE = FakeToolStart(tool_name="write", args={"path": "src/mod.py", "content": "def f():\n    return 1\n"})
RECORD = FakeToolStart(tool_call_id="call-2", tool_name="record_intent", args={
    "file": "src/mod.py", "symbol": "f", "why": "f is the single entry point of this task",
    "property": "f returns an int", "domain": "demo"})


def _run(script, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        return asyncio.run(run_task(root, B, harness=FakeHarness(script, max_turns=None), diff=DIFF,
                                    symbols={"f"}, **kwargs))


# T3 is about counting what a unit did not publish. Since Q2 the cap publishes
# what passes the gate, so these cases switch end publication off to keep a
# discarded intent to count.
SEM_PUBLICACAO_NO_FIM = replace(load_supervisor_config(), publicacao_no_encerramento="nenhuma")


class TestT3DiscardedIntentsAreNotTouchedRegions(unittest.TestCase):
    def test_capped_unit_with_an_intent_counts_one_discarded_intent(self):
        result = _run([[WRITE, RECORD, FakeTurnEnd(tool_results=[{"tool_name": "write"}])]],
                      max_productive_turns=1, supervisor_cfg=SEM_PUBLICACAO_NO_FIM)
        tel = result.telemetry
        self.assertEqual(result.verdict, "TETO")
        self.assertFalse(tel["captura_publicada"])
        self.assertEqual(tel["pendencias_nao_publicadas"], 1)  # regions, as before
        self.assertEqual(tel["intencoes_nao_publicadas"], 1)
        self.assertEqual(tel["regioes_sem_intencao"], 0)
        self.assertEqual(tel["chamadas_record_intent"], 1)

    def test_capped_unit_without_an_intent_discards_no_intent(self):
        result = _run([[WRITE, FakeTurnEnd(tool_results=[{"tool_name": "write"}])]], max_productive_turns=1,
                      supervisor_cfg=SEM_PUBLICACAO_NO_FIM)
        tel = result.telemetry
        self.assertEqual(tel["pendencias_nao_publicadas"], 1)
        self.assertEqual(tel["intencoes_nao_publicadas"], 0)
        self.assertEqual(tel["regioes_sem_intencao"], 1)
        self.assertEqual(tel["chamadas_record_intent"], 0)

    def test_published_unit_discards_nothing(self):
        result = _run([[WRITE, RECORD, FakeTurnEnd(tool_results=[{"tool_name": "write"}]),
                        FakeTurnEnd(tool_results=[])]])
        tel = result.telemetry
        self.assertTrue(tel["captura_publicada"])
        self.assertEqual(tel["intencoes_nao_publicadas"], 0)
        self.assertEqual(tel["pendencias_nao_publicadas"], 0)


class TestT4GateMessageNamesTheSymbol(unittest.TestCase):
    def test_one_line_per_identity_with_symbol_and_lines(self):
        a = Region("pkg/engine.py", 10, 40, symbol="Parser", edited_lines=30)
        b = Region("pkg/engine.py", 50, 90, symbol="Parser", edited_lines=40)
        c = Region("pkg/engine.py", 100, 120, symbol="run", edited_lines=20)
        msg = render_falhas([Falha("EDICAO_GRANDE_SEM_SIMBOLO", a, "70 edited_lines"),
                             Falha("EDICAO_GRANDE_SEM_SIMBOLO", b, "70 edited_lines"),
                             Falha("AUSENTE", c)])
        lines = msg.splitlines()[1:]
        self.assertEqual(lines, [
            "- EDICAO_GRANDE_SEM_SIMBOLO: pkg/engine.py::Parser (linhas 10-90; 70 edited_lines)",
            "- AUSENTE: pkg/engine.py::run (linhas 100-120)",
        ])

    def test_region_without_symbol_keeps_the_file_and_lines(self):
        msg = render_falhas([Falha("AUSENTE", Region("README.md", 1, 3))])
        self.assertIn("- AUSENTE: README.md (linhas 1-3)", msg)


class TestT6bBlockTurnsAreTurns(unittest.TestCase):
    def test_block_turns_counts_turns_and_bloqueios_counts_verdicts(self):
        script = [[WRITE, FakeTurnEnd(tool_results=[{"tool_name": "write"}]), FakeTurnEnd(tool_results=[])],
                  [RECORD, FakeTurnEnd(tool_results=[{"tool_name": "record_intent"}]),
                   FakeTurnEnd(tool_results=[])]]
        result = _run(script)
        self.assertEqual(result.verdict, "PASSA")
        self.assertEqual(result.telemetry["bloqueios"], 1)
        self.assertEqual(result.block_turns, 2)  # the record_intent turn and the closing turn
        self.assertEqual(result.telemetry["block_turns"], 2)
        self.assertEqual(sum(1 for t in result.telemetry["turnos"] if t["kind"] == "block"), 2)


class TestT8OneEntryPerDecision(unittest.TestCase):
    def test_flush_merges_hunks_of_one_symbol_with_one_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def f():\n" + "    x = 1\n" * 20, encoding="utf-8")
            store = IntentStore(root / "log")
            pend = {}
            for start, end in ((2, 4), (10, 12)):
                region = Region("m.py", start, end, symbol="f")
                pend[region.key()] = Pending(region=region, why="w", property="p", domain="d", symbol="f")
            other = Region("m.py", 15, 16, symbol="f")
            pend[other.key()] = Pending(region=other, why="another decision", domain="d", symbol="f")
            _flush_pendentes(store, pend, "t1", root)
            entries = store.current()
        self.assertEqual(len(entries), 2)
        merged = next(e for e in entries if e.why == "w")
        self.assertEqual((merged.anchor.line_start, merged.anchor.line_end), (2, 12))

    def test_projection_serves_identical_entries_once(self):
        @dataclass(frozen=True)
        class Anchor:
            file: str
            symbol: str

            def node_id(self):
                return f"{self.file}::{self.symbol}"

        @dataclass(frozen=True)
        class Entry:
            id: str
            ts: str
            anchor: Anchor
            why: str
            property: str = ""
            domain: str = ""

        graph = Graph()
        graph.add_edge("m.py", "m.py::f", "contains")
        same = [Entry(str(i), "2026-10-09T00:00:0%dZ" % i, Anchor("m.py", "f"), "w", "p") for i in range(3)]
        bloco, tel = projetar(graph, same, ["m.py::f"], load_project_config())
        self.assertEqual(tel["n_escolhidas"], 1)
        self.assertEqual(tel["duplicadas_colapsadas"], 2)
        self.assertEqual(bloco.count("Por que: w"), 1)


class TestT9ReuseIsBySymbol(unittest.TestCase):
    def test_entry_with_a_symbol_is_reused_only_if_that_symbol_changed(self):
        @dataclass(frozen=True)
        class Anchor:
            file: str
            symbol: str | None

            def node_id(self):
                return f"{self.file}::{self.symbol}" if self.symbol else self.file

        @dataclass(frozen=True)
        class Entry:
            anchor: Anchor

        served = [Entry(Anchor("e.py", "Parser")), Entry(Anchor("e.py", "run")), Entry(Anchor("e.py", None))]
        out = aproveitamento_do_bloco(served, [Region("e.py", 1, 5, symbol="Parser")])
        self.assertEqual(out["reaproveitadas"], 2)  # Parser by symbol, the file-level entry by file
        self.assertEqual(out["chaves"], ["e.py", "e.py::Parser"])
        self.assertEqual(out["criterio"], "simbolo")


if __name__ == "__main__":
    unittest.main()
