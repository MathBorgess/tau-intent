"""The bench's build check (owner decision, 2026-10-09).

In the SWE-Milestone pilot, arm B left a Cython compile error at milestone 2. The chain
carried the tree forward, so milestones 3 to 6 started broken and scored 0, and the agent
ignored the error it saw. The owner decided: the build check is the bench's job, the next
session is told (with the compiler's output, the same way in every arm), and every break
and every recovery is recorded.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tau_intent.bench.cell import build_telemetry
from tau_intent.bench.oracle import run_build_check
from tau_intent.bench.taskset import TasksetError, load_taskset
from tau_intent.config import aviso_de_build, config_hashes
from tests.test_v3_bench_ambiente import READY, SETUP, demo_copy

#: "Builds" while calc/core.py has no ``sub``: task 1 of the demo chain breaks it.
CHECK = """#!/usr/bin/env bash
if grep -q "def sub" calc/core.py; then
  echo "compiling calc/core.py"
  echo "error: sub is not allowed here"
  exit 1
fi
echo "build ok"
"""


def with_check(tmp: Path) -> Path:
    root = demo_copy(tmp, environment={"setup": ["bash", "environment/setup.sh"], "bin": "bin",
                                       "timeout_s": 60, "build_check": "environment/build_check.sh"})
    (root / "environment").mkdir()
    (root / "environment" / "setup.sh").write_text(SETUP)
    (root / "environment" / "build_check.sh").write_text(CHECK)
    return root


class TestDeclaration(unittest.TestCase):
    def test_the_check_is_read_with_its_default_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts = load_taskset(with_check(Path(tmp)))
        self.assertEqual(ts.environment["build_check"], "environment/build_check.sh")
        self.assertEqual(ts.environment["build_check_timeout_s"], 900)

    def test_a_missing_script_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = with_check(Path(tmp))
            (root / "environment" / "build_check.sh").unlink()
            with self.assertRaises(TasksetError):
                load_taskset(root)

    def test_the_notice_is_a_hashed_prompt(self):
        self.assertIn("prompts/aviso-de-build-v1.txt", config_hashes())
        texto = aviso_de_build("error: sub is not allowed here")
        self.assertTrue(texto.startswith("Build check:"))
        self.assertIn("```\nerror: sub is not allowed here\n```", texto)


class TestRun(unittest.TestCase):
    def test_it_runs_in_the_agent_tree_and_keeps_the_output_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts = load_taskset(with_check(Path(tmp)))
            work = Path(tmp) / "work"
            (work / "calc").mkdir(parents=True)
            (work / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")
            ok = run_build_check(ts, work)
            (work / "calc" / "core.py").write_text("def sub(a, b):\n    return a - b\n")
            broken = run_build_check(ts, work)
        self.assertTrue(ok["ok"])
        self.assertFalse(broken["ok"])
        self.assertEqual(broken["exit_code"], 1)
        self.assertIn("error: sub is not allowed here", broken["output_tail"])

    def test_no_declaration_no_check(self):
        from tests.bench_support import DEMO

        self.assertIsNone(run_build_check(load_taskset(DEMO), Path(".")))


class TestTelemetry(unittest.TestCase):
    def test_a_break_inside_the_session(self):
        tel = build_telemetry({"ok": True}, {"ok": False},
                              [{"turn": 2, "build_ok": True}, {"turn": 5, "build_ok": False}])
        self.assertTrue(tel["quebrou"])
        self.assertEqual(tel["turno_quebra"], 5)
        self.assertIsNone(tel["recuperou"])
        self.assertFalse(tel["aviso_enviado"])

    def test_a_recovery_after_the_notice(self):
        tel = build_telemetry({"ok": False}, {"ok": True},
                              [{"turn": 1, "build_ok": False}, {"turn": 3, "build_ok": True}])
        self.assertTrue(tel["aviso_enviado"])
        self.assertTrue(tel["recuperou"])
        self.assertEqual(tel["turno_recuperacao"], 3)
        self.assertFalse(tel["quebrou"])
        self.assertEqual(tel["turnos_com_build_quebrada"], 1)

    def test_a_notice_that_did_not_help(self):
        tel = build_telemetry({"ok": False}, {"ok": False}, [{"turn": 1, "build_ok": False}])
        self.assertIs(tel["recuperou"], False)
        self.assertIsNone(tel["turno_recuperacao"])


@unittest.skipUnless(READY, "needs pytest and tau_agent")
class TestCell(unittest.TestCase):
    def test_the_next_session_is_told_and_the_record_says_so(self):
        from tests.bench_support import DemoModel, read_records
        from tests.stub_openai import StubServer
        from tau_intent.bench.cli import main as bench_main

        with tempfile.TemporaryDirectory() as tmp:
            root = with_check(Path(tmp))
            out = Path(tmp) / "out"
            with StubServer(DemoModel()) as stub:
                argv = ["--offline", "--arms", "A,B", "--seed", "7", "--taskset", str(root), "--out", str(out),
                        "--provider-url", stub.url, "--model", "stub-model", "--skip-pin-check",
                        "--snapshot-oracle", "every-edit"]
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = bench_main(argv)
            self.assertEqual(code, 0, buffer.getvalue())
            (cell,) = [p for p in out.iterdir() if p.is_dir() and not p.name.startswith(".")]
            records = {(r["arm_id"], r["task_index"]): r for r in read_records(cell)}
            prompts = {key: (cell / r["artifacts"]["paths"]["prompt"]).read_text()
                       for key, r in records.items()}
            build_files = {key: json.loads((cell / r["artifacts"]["paths"]["build"]).read_text())
                           for key, r in records.items()}
        for arm in ("A", "B"):
            first, second = records[(arm, 1)]["build"], records[(arm, 2)]["build"]
            self.assertTrue(first["quebrou"], arm)
            self.assertEqual(first["turno_quebra"], 1, arm)
            self.assertFalse(first["aviso_enviado"], arm)
            self.assertNotIn("Build check:", prompts[(arm, 1)])
            self.assertTrue(second["aviso_enviado"], arm)
            self.assertIs(second["recuperou"], False, arm)
            self.assertIn("Build check:", prompts[(arm, 2)])
            self.assertIn("error: sub is not allowed here", prompts[(arm, 2)])
            self.assertFalse(build_files[(arm, 2)]["inicio"]["ok"], arm)
        # The same notice, word for word, in both arms.
        def aviso(text: str) -> str:
            start = text.index("Build check:")
            fence = text.index("```", text.index("```", start) + 3)
            return text[start:fence + 3]

        self.assertEqual(aviso(prompts[("A", 2)]), aviso(prompts[("B", 2)]))


if __name__ == "__main__":
    unittest.main()
