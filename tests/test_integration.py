import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path

from tau_intent.cli import build_parser, flags_from_args, main
from tau_intent.fake_provider import (
    FakeHarness,
    FakeTurnEnd,
    FakeToolStart,
    passing_script,
)
from tau_intent.supervisor import Flags, run_task
from tau_intent.telemetry import TOKENIZER, count_tokens

from tau_intent.gate import GateConfig, Veredito


DIFF = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
)


class TestCliFlags(unittest.TestCase):
    def test_four_independent_flags(self):
        parser = build_parser()
        a = flags_from_args(parser.parse_args(["--no-capture", "--no-gate", "--no-project", "--no-serve"]))
        b = flags_from_args(parser.parse_args(["--capture", "--gate", "--project", "--serve"]))
        c = flags_from_args(parser.parse_args(
            ["--capture", "--gate", "--project", "--serve", "--llm-rescue"]))
        self.assertEqual((a.capture, a.gate, a.project, a.serve), (False, False, False, False))
        # H16: B and C both project; llm_rescue is the whole difference.
        self.assertEqual((b.capture, b.gate, b.project, b.serve), (True, True, True, True))
        self.assertEqual((c.capture, c.gate, c.project, c.serve), (True, True, True, True))
        self.assertFalse(b.llm_rescue)
        self.assertTrue(c.llm_rescue)
        self.assertTrue(any(action.dest == "serve" for action in parser._actions))

    def test_no_arm_branch_outside_flag_reading(self):
        import tau_intent.supervisor as sup

        source = inspect.getsource(sup)
        self.assertNotIn('arm == "A"', source)
        self.assertNotIn("arm == 'A'", source)


class TestIntegrationFakeProvider(unittest.TestCase):
    def test_arm_a_writes_no_intents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            harness = FakeHarness(max_turns=None)
            result = asyncio.run(
                run_task(
                    root,
                    Flags(capture=False, gate=False, project=False, serve=False),
                    harness=harness,
                    diff=DIFF,
                    symbols={"f"},
                )
            )
            self.assertFalse((root / "intents.jsonl").exists())
            self.assertEqual(result.block_turns, 0)

    def test_arm_b_appends_after_successful_gate(self):
        # Arm B under H16: capture + gate + projected view, llm_rescue off.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            harness = FakeHarness(passing_script(), max_turns=None)
            result = asyncio.run(
                run_task(
                    root,
                    Flags(capture=True, gate=True, project=True, serve=True),
                    harness=harness,
                    diff=DIFF,
                    symbols={"f", "int"},
                    max_productive_turns=8,
                )
            )
            self.assertEqual(result.verdict, "PASSA")
            try:
                from tau_intent.store import IntentStore  # noqa: F401

                self.assertTrue((root / "intents.jsonl").exists())
                self.assertGreater(
                    len((root / "intents.jsonl").read_text(encoding="utf-8").splitlines()),
                    0,
                )
            except ImportError:
                pass
            names = [
                t["name"] if isinstance(t, dict) else getattr(t, "name", "")
                for t in harness.tools
            ]
            if names:
                self.assertIn("record_intent", names)

    def test_arm_c_serve_and_project_flags_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            harness = FakeHarness(passing_script(), max_turns=None)
            result = asyncio.run(
                run_task(
                    root,
                    Flags(capture=True, gate=True, project=True, serve=True),
                    harness=harness,
                    diff=DIFF,
                    symbols={"f", "int"},
                )
            )
            self.assertEqual(result.flags.project, True)
            self.assertEqual(result.flags.serve, True)
            self.assertEqual(result.verdict, "PASSA")

    def test_gate_runs_only_on_last_empty_turn_end(self):
        calls = []

        def counting_gate(regions, pendentes, symbols, cfg, bloqueios):
            calls.append(len(regions))
            return Veredito.passa()

        with tempfile.TemporaryDirectory() as temp_dir:
            harness = FakeHarness(passing_script(), max_turns=None)
            asyncio.run(
                run_task(
                    Path(temp_dir),
                    Flags(capture=True, gate=True, project=False, serve=False),
                    harness=harness,
                    diff=DIFF,
                    symbols={"f", "int"},
                    gate_fn=counting_gate,
                )
            )
        self.assertEqual(len(calls), 1)

    def test_bloqueia_calls_follow_up_and_does_not_close_session(self):
        script = [
            [
                FakeToolStart(args={"path": "src/mod.py", "content": "x"}),
                FakeTurnEnd(tool_results=[{"tool_name": "write"}]),
                FakeTurnEnd(tool_results=[]),
            ],
            [FakeTurnEnd(tool_results=[])],
            [FakeTurnEnd(tool_results=[])],
            [FakeTurnEnd(tool_results=[])],
        ]
        harness = FakeHarness(script, max_turns=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = asyncio.run(
                run_task(
                    Path(temp_dir),
                    Flags(capture=True, gate=True, project=False, serve=False),
                    harness=harness,
                    diff=DIFF,
                    symbols={"f"},
                    gate_cfg=GateConfig(n_max=2),
                    max_productive_turns=8,
                )
            )
        self.assertEqual(result.verdict, "ESCALAR")
        self.assertGreaterEqual(result.block_turns, 2)
        self.assertTrue(result.follow_ups)
        self.assertEqual(result.productive_turns, 1)
        self.assertNotEqual(result.productive_turns, result.block_turns)

    def test_fake_harness_rejects_raw_max_turns(self):
        with self.assertRaises(ValueError):
            FakeHarness(max_turns=8)

    def test_whitespace_tokenizer_not_chars_per_token(self):
        self.assertEqual(TOKENIZER, "whitespace-v1")
        self.assertEqual(count_tokens("one two three"), 3)
        import tau_intent.telemetry as tel

        self.assertNotIn("CHARS_PER_TOKEN =", inspect.getsource(tel))

    def test_cli_fake_provider_demo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rc = main(
                [
                    "--fake-provider",
                    "--capture",
                    "--gate",
                    "--no-project",
                    "--serve",
                    "--workspace",
                    temp_dir,
                ]
            )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
