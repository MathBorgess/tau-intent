"""Bench support for a heavyweight brownfield task set (SWE-Milestone sklearn, 2026-10-09).

environment   a task set may declare a setup script, run once per arm workspace, that
              builds the arm's own interpreter outside the agent's tree; its ``bin`` goes
              first on the agent's PATH and is the oracle's interpreter.
oracle_scope  ``own``: the oracle of task k is task k's own tests directory (the builder
              made it cumulative with the tests of the end state of k).
snapshot      ``--snapshot-oracle every-edit``: after every turn that edited files, the
              bench runs task k's tests outside the agent's tree and outside its clock;
              the record says at which turn they first went green (Q6, turns to green).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    READY = True
except ImportError:  # pragma: no cover - depends on the environment
    READY = False

from tau_intent.bench.oracle import oracle_dirs, run_oracle, run_snapshot
from tau_intent.bench.taskset import TasksetError, load_taskset
from tau_intent.fake_provider import FakeHarness, FakeTurnEnd
from tau_intent.supervisor import Flags, run_task
from tau_intent.workspace_tools import _command_env
from tests.bench_support import DEMO

SETUP = """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$ENV_DIR/bin"
ln -sf "$BENCH_PYTHON" "$ENV_DIR/bin/python"
printf '#!/usr/bin/env bash\\necho env-marker\\n' > "$ENV_DIR/bin/marker"
chmod +x "$ENV_DIR/bin/marker"
echo "setup ran in $WORKSPACE" > "$ENV_DIR/setup.log"
"""

CONFTEST = """import os
def pytest_collection_modifyitems(config, items):
    keep = "snapshot_only" if os.environ.get("TAU_INTENT_ORACLE_MODE") == "snapshot" else None
    if keep:
        items[:] = [i for i in items if keep in i.nodeid]
"""


def demo_copy(tmp: Path, **manifest_changes) -> Path:
    root = tmp / "taskset"
    shutil.copytree(DEMO, root)
    manifest = json.loads((root / "taskset.json").read_text())
    manifest.update(manifest_changes)
    (root / "taskset.json").write_text(json.dumps(manifest))
    return root


class TestTasksetDeclarations(unittest.TestCase):
    def test_environment_and_scope_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = demo_copy(Path(tmp), environment={"setup": ["bash", "environment/setup.sh"], "bin": "bin",
                                                     "timeout_s": 60}, oracle_scope="own")
            (root / "environment").mkdir()
            (root / "environment" / "setup.sh").write_text(SETUP)
            ts = load_taskset(root)
        self.assertEqual(ts.environment["setup"], ["bash", "environment/setup.sh"])
        self.assertEqual(ts.oracle_scope, "own")
        self.assertEqual([label for label, _ in oracle_dirs(ts, 2)], ["02"])

    def test_default_scope_is_cumulative(self):
        ts = load_taskset(DEMO)
        self.assertEqual(ts.oracle_scope, "cumulative")
        self.assertEqual([label for label, _ in oracle_dirs(ts, 2)], ["01", "02"])
        self.assertIsNone(ts.environment)

    def test_bad_declarations_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TasksetError):
                load_taskset(demo_copy(Path(tmp), oracle_scope="sideways"))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TasksetError):
                load_taskset(demo_copy(Path(tmp), environment={"setup": "not-a-list", "bin": "bin"}))


@unittest.skipUnless(READY, "needs pytest")
class TestSnapshotMode(unittest.TestCase):
    def test_the_task_set_sees_which_mode_runs_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = demo_copy(Path(tmp))
            tests = root / "tasks" / "01" / "tests"
            (tests / "conftest.py").write_text(CONFTEST)
            (tests / "test_mode.py").write_text("def test_snapshot_only():\n    pass\n\ndef test_other():\n    pass\n")
            ws = Path(tmp) / "ws"
            shutil.copytree(root / "reference" / "01", ws)
            ts = load_taskset(root)
            full = run_oracle(ts, 1, ws)
            snap = run_snapshot(ts, 1, ws)
        ids = lambda r: sorted(t["nodeid"].rsplit("::", 1)[-1] for t in r["per_test"])  # noqa: E731
        self.assertIn("test_other", ids(full))
        self.assertEqual(ids(snap), ["test_snapshot_only"])


class TestAgentPath(unittest.TestCase):
    def test_env_bin_goes_first_on_the_agent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _command_env(Path(tmp), env_bin=Path(tmp) / "env" / "bin")
        self.assertTrue(env["PATH"].startswith(str(Path(tmp) / "env" / "bin") + os.pathsep))
        self.assertEqual(env["VIRTUAL_ENV"], str(Path(tmp) / "env"))


class TestClockExcludesCallbacks(unittest.TestCase):
    def test_time_spent_in_on_event_does_not_count_toward_the_deadline(self):
        now = {"t": 0.0}

        def relogio():
            return now["t"]

        def slow_callback(event):
            if getattr(event, "type", "") == "turn_end":
                now["t"] += 50.0  # a snapshot oracle run, outside the agent's clock

        script = [[FakeTurnEnd(tool_results=[{"tool_name": "write"}]) for _ in range(3)] + [FakeTurnEnd()]]
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(run_task(Path(tmp), Flags(False, False, False, False),
                                          harness=FakeHarness(script, max_turns=None), diff=[],
                                          max_productive_turns=10, deadline_s=60.0, relogio=relogio,
                                          on_event=slow_callback))
        self.assertEqual(result.telemetry["encerramento"], "completed")
        self.assertEqual(result.telemetry["fora_do_relogio_s"], 200.0)


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestCellWithEnvironmentAndSnapshots(unittest.TestCase):
    def test_setup_runs_per_arm_and_the_record_has_turns_to_green(self):
        from tests.bench_support import DemoModel, read_records
        from tests.stub_openai import StubServer
        from tau_intent.bench.cli import main as bench_main
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = demo_copy(Path(tmp), environment={"setup": ["bash", "environment/setup.sh"], "bin": "bin",
                                                     "timeout_s": 60})
            (root / "environment").mkdir()
            (root / "environment" / "setup.sh").write_text(SETUP)
            out = Path(tmp) / "out"
            with StubServer(DemoModel()) as stub:
                argv = ["--offline", "--arms", "A,B", "--seed", "7", "--taskset", str(root), "--out", str(out),
                        "--provider-url", stub.url, "--model", "stub-model", "--skip-pin-check",
                        "--snapshot-oracle", "every-edit", "--keep-workspaces"]
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = bench_main(argv)
            self.assertEqual(code, 0, buffer.getvalue())
            (cell,) = [p for p in out.iterdir() if p.is_dir() and not p.name.startswith(".")]
            records = read_records(cell)
            logs = sorted(out.rglob("env/setup.log"))
        self.assertEqual(len(logs), 2)  # one per arm workspace
        for record in records:
            snap = record["snapshot_oracle"]
            self.assertEqual(snap["mode"], "every-edit")
            self.assertEqual(snap["turns_to_green"], 1, record["arm_id"])
            self.assertGreaterEqual(snap["runs"], 1)
            self.assertEqual(record["environment"]["setup_exit"], 0)


if __name__ == "__main__":
    unittest.main()
