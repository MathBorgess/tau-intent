"""Copilot extra path. Canonical suite is tests/test_integration.py."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tau_intent.cli import flags_from_args
from tau_intent.fake_provider import FakeHarness, FakeTurnEnd, passing_script
from tau_intent.supervisor import Flags, run_task

from tau_intent.gate import Veredito

DIFF = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
)


class TestPr4Contract(unittest.TestCase):
    def test_arm_a_never_writes_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = asyncio.run(
                run_task(
                    root,
                    flags_from_args(["--arm", "A"]),
                    harness=FakeHarness(max_turns=None),
                    diff=DIFF,
                    symbols={"f"},
                )
            )
            self.assertFalse((root / "intents.jsonl").exists())
            self.assertEqual(result.productive_turns, 1)
            self.assertEqual(result.verdict, "PASSA")

    def test_gate_only_on_last_empty_turn_end(self) -> None:
        calls: list[int] = []

        def counting_gate(regions, pendentes, symbols, cfg, bloqueios):
            del pendentes, symbols, cfg, bloqueios
            calls.append(len(regions))
            return Veredito.passa()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(
                run_task(
                    Path(tmp),
                    Flags(capture=True, gate=True, project=False, serve=False),
                    harness=FakeHarness(passing_script(), max_turns=None),
                    diff=DIFF,
                    symbols={"f", "int"},
                    gate_fn=counting_gate,
                )
            )
        self.assertEqual(len(calls), 1)

    def test_raw_max_turns_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FakeHarness(max_turns=8)

    def test_empty_turn_end_is_the_gate_boundary(self) -> None:
        event = FakeTurnEnd(tool_results=[])
        self.assertEqual(list(event.tool_results), [])
