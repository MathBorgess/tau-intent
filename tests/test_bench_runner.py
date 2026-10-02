"""S6: ``tau-intent bench`` end to end, offline, against the local stub model.

The stub plays the participant's Ollama/LM Studio/llama.cpp: no live model, no
external network. The demo task set (2 tasks + Q0) lives in tests/fixtures; the
real one is built in mathai-harness and checked separately (test_bench_taskset).
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    READY = True
except ImportError:  # pragma: no cover - depends on the environment
    READY = False

from tau_intent.bench.cli import main as bench_main
from tau_intent.bench.record import validate_record
from tau_intent.bench.taskset import load_taskset
from tests.bench_support import DEMO, MODEL, DemoModel, clone_bundle, git_log, read_records
from tests.stub_openai import StubServer


def run_bench(out: Path, stub: StubServer, *extra: str, offline_args=("--arms", "B,A,C", "--seed", "7")):
    argv = ["--offline", *offline_args, "--taskset", str(DEMO), "--out", str(out),
            "--provider-url", stub.url, "--model", MODEL, "--skip-pin-check", *extra]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = bench_main(argv)
    return code, buffer.getvalue()


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestOfflineCell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.model = DemoModel()
        with StubServer(cls.model) as stub:
            cls.code, cls.stdout = run_bench(cls.out, stub)
            cls.requests = stub.chat_requests()
        (cls.cell_dir,) = [p for p in cls.out.iterdir() if p.is_dir()]
        cls.records = read_records(cls.cell_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def arm_records(self, arm):
        return [r for r in self.records if r["arm_id"] == arm]

    def test_exit_code_and_one_record_per_arm_and_task_in_the_assigned_order(self):
        self.assertEqual(self.code, 0, self.stdout)
        self.assertEqual(len(self.records), 6)
        order = [(r["arm_id"], r["task_index"]) for r in self.records]
        # interleaved by task index, arms in the owner's order
        self.assertEqual(order, [("B", 1), ("A", 1), ("C", 1), ("B", 2), ("A", 2), ("C", 2)])
        self.assertTrue(all(r["arm_order"] == ["B", "A", "C"] and r["seed"] == 7 for r in self.records))

    def test_every_record_is_valid_draft_and_bijective(self):
        for record in self.records:
            self.assertEqual(validate_record(record), [], record["arm_id"])
            self.assertIs(record["draft"], True)
            self.assertEqual(record["schema_version"], "gambiarra-coleta-2")
        self.assertEqual({r["arm_id"]: r["harness_id"] for r in self.records},
                         {"A": "tau", "B": "tau_intent", "C": "tau_intent_llm_rescue"})
        self.assertFalse((self.cell_dir / "records.invalid.jsonl").exists())

    def test_hashes_are_recomputed_from_the_task_set(self):
        ts = load_taskset(DEMO)
        for record in self.records:
            self.assertEqual(record["task_set_sha"], ts.sha)
            self.assertEqual(record["task_hash"], ts.task(record["task_index"]).hash)

    def test_oracle_passes_with_regression_and_runs_outside_the_workspace(self):
        for record in self.records:
            oracle = record["oracle"]
            self.assertTrue(oracle["pass"], record["arm_id"])
            ids = [t["nodeid"] for t in oracle["per_test"]]
            self.assertIn("tests/01/test_t01_sub.py::test_sub", ids)
            if record["task_index"] == 2:  # regression of task 1 is part of the oracle of task 2
                self.assertIn("tests/02/test_t02_mul.py::test_mul", ids)
            self.assertEqual((oracle["failed"], oracle["errors"]), (0, 0))

    def test_one_commit_per_task_per_arm_and_the_bundle_holds_the_series(self):
        for arm in "ABC":
            repo = clone_bundle(self.cell_dir / "arms" / arm / "repo.bundle")
            self.assertEqual(git_log(repo), ["seed", "task-01", "task-02"], arm)
            tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/main"], cwd=repo,
                                  capture_output=True, text=True, check=True).stdout.split()
            self.assertIn("calc/ops.py", tree)  # the untracked module made it into the commit
            self.assertFalse([p for p in tree if "test_t0" in p], "hidden tests leaked into the workspace")
            self.assertFalse([p for p in tree if p.endswith(".pyc") or p == "intents.jsonl"])

    def test_evolution_data_per_task(self):
        for record in self.records:
            evo = record["evolution"]
            self.assertNotEqual(evo["commit_before"], evo["commit_after"])
            if record["task_index"] == 2:
                self.assertEqual(evo["untracked_created"], ["calc/ops.py"])
                self.assertEqual((evo["files_changed"], evo["insertions"], evo["deletions"]), (1, 2, 0))
            else:
                self.assertEqual((evo["files_changed"], evo["insertions"], evo["deletions"]), (1, 4, 0))
                self.assertEqual(evo["untracked_created"], [])
            self.assertEqual(evo["edit_size"], evo["insertions"] + evo["deletions"])
        # the second task starts from where the first one ended, per arm
        for arm in "ABC":
            first, second = self.arm_records(arm)
            self.assertEqual(second["evolution"]["commit_before"], first["evolution"]["commit_after"])

    def test_arm_a_is_isolated_from_the_mechanism(self):
        self.assertFalse((self.cell_dir / "arms" / "A" / "intents.jsonl").exists())
        for record in self.arm_records("A"):
            self.assertEqual(set(record["mechanism"]["flags"].values()), {False})
            self.assertEqual(record["mechanism_telemetry"]["block_turns"], 0)
            self.assertFalse(any(t["kind"] in ("block", "rescue") for t in record["turns"]))
            transcript = (self.cell_dir / record["artifacts"]["paths"]["transcript"]).read_text()
            self.assertNotIn("record_intent", transcript)
        # and the wire agrees: A sessions were handed no record_intent tool
        plain = [s for s in self.model.agent_sessions if not s["intent_tool"]]
        self.assertEqual(len(plain), 2)
        self.assertTrue(all("intencao_registrada" not in s["prompt"] for s in plain))

    def test_arms_b_and_c_capture_intents_and_project(self):
        for arm in "BC":
            lines = [json.loads(l) for l in (self.cell_dir / "arms" / arm / "intents.jsonl").read_text().splitlines()]
            self.assertEqual([l["anchor"]["file"] for l in lines], ["calc/core.py", "calc/ops.py"], arm)
            self.assertEqual(lines[1]["anchor"]["symbol"], "mul")
            second = self.arm_records(arm)[1]
            self.assertFalse(second["mechanism_telemetry"]["bloco_vazio"])
            self.assertEqual(second["mechanism_telemetry"]["verdict"], "PASSA")
            prompt = (self.cell_dir / second["artifacts"]["paths"]["prompt"]).read_text()
            self.assertIn("Evidência do histórico de intenção", prompt)
        self.assertEqual(self.arm_records("B")[0]["mechanism"]["flags"],
                         {"capture": True, "gate": True, "project": True, "serve": True, "llm_rescue": False})
        self.assertTrue(self.arm_records("C")[0]["mechanism"]["flags"]["llm_rescue"])

    def test_rescue_tokens_only_where_there_is_a_rescue(self):
        for record in self.arm_records("B") + self.arm_records("A"):
            self.assertEqual((record["tokens"]["rescue_in"], record["tokens"]["rescue_out"]), (0, 0))
        second_c = self.arm_records("C")[1]
        self.assertGreater(second_c["tokens"]["rescue_in"], 0)
        self.assertEqual([t["kind"] for t in second_c["turns"]][0], "rescue")
        self.assertTrue(second_c["mechanism_telemetry"]["llm_rescue_disparou"])

    def test_outcome_tokens_come_from_provider_usage(self):
        for record in self.records:
            tokens = record["tokens"]
            self.assertEqual(tokens["source"], "provider_usage")
            self.assertEqual(tokens["cost_usd"], 0)
            self.assertEqual(tokens["in"], 11 * 2)  # two answered calls, stub usage 11/7 each
            self.assertEqual(tokens["out"], 7 * 2)

    def test_sampling_was_on_the_wire_for_every_request(self):
        self.assertGreater(len(self.requests), 12)
        for body in self.requests:
            self.assertEqual((body["temperature"], body["seed"], body["model"]), (0, 7, MODEL))
        for record in self.records:
            manifest = json.loads((self.cell_dir / record["artifacts"]["paths"]["manifest"]).read_text())
            self.assertTrue(manifest["run"]["amostragem_conferida_no_fio"])

    def test_artifacts_and_the_uploaded_bundle_shape(self):
        for path in self.records[0]["artifacts"]["paths"].values():
            self.assertTrue((self.cell_dir / path).is_file(), path)
        cell = json.loads((self.cell_dir / "cell.json").read_text())
        self.assertEqual(cell["records"], 6)
        self.assertFalse(cell["truncated"])
        self.assertEqual(cell["bench_assign"]["arms"], ["B", "A", "C"])
        self.assertEqual(cell["task_set"]["sha"], load_taskset(DEMO).sha)
        bundle = self.out / f"{cell['bench_assign']['cell_id']}.tar.gz"
        with tarfile.open(bundle) as tar:
            names = set(tar.getnames())
        self.assertTrue({"cell.json", "records.jsonl", "arms/B/intents.jsonl", "arms/A/repo.bundle",
                         "arms/B/task-01/transcript.jsonl", "arms/C/task-02/diff.patch"} <= names)
        self.assertNotIn("arms/A/intents.jsonl", names)
        self.assertIn("bundle", self.stdout)

    def test_transcript_has_real_tau_events_without_token_deltas(self):
        path = self.cell_dir / self.records[0]["artifacts"]["paths"]["transcript"]
        events = [json.loads(l)["event"]["type"] for l in path.read_text().splitlines()]
        self.assertIn("tool_execution_start", events)
        self.assertIn("turn_end", events)
        self.assertNotIn("message_update", events)


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestQualificationAndGuards(unittest.TestCase):
    def test_qualification_runs_q0_in_plain_tau_with_at_most_two_attempts(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(q_first_attempt_wrong=True)) as stub:
            code, stdout = run_bench(Path(tmp), stub, offline_args=("--mode", "qualification"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
            cell = json.loads((cell_dir / "cell.json").read_text())
        self.assertEqual(code, 0, stdout)
        self.assertEqual([(r["arm_id"], r["harness_id"], r["task_index"], r["task_id"]) for r in records],
                         [("Q", "tau", 0, "Q0")] * 2)
        self.assertEqual([r["oracle"]["pass"] for r in records], [False, True])
        self.assertEqual(cell["qualification"], {"passed": True})
        for record in records:
            self.assertEqual(validate_record(record), [])
            self.assertEqual(set(record["mechanism"]["flags"].values()), {False})
            self.assertEqual(record["arm_order"], ["A"])

    def test_qualification_stops_after_a_pass_on_the_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub:
            run_bench(Path(tmp), stub, offline_args=("--mode", "qualification"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
        self.assertEqual(len(records), 1)

    def test_a_failed_qualification_twice_is_reported_not_hidden(self):
        class AlwaysWrong(DemoModel):
            def __call__(self, index, body):
                self.q_first_attempt_wrong, self.q_attempts = True, 0
                return super().__call__(index, body)

        with tempfile.TemporaryDirectory() as tmp, StubServer(AlwaysWrong()) as stub:
            run_bench(Path(tmp), stub, offline_args=("--mode", "qualification"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
            cell = json.loads((cell_dir / "cell.json").read_text())
        self.assertEqual([r["oracle"]["pass"] for r in records], [False, False])
        self.assertEqual(cell["qualification"], {"passed": False})

    def test_provider_failure_is_recorded_as_error_and_the_series_still_has_its_commits(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(), status=lambda i: 500) as stub:
            code, stdout = run_bench(Path(tmp), stub, "--skip-preflight", offline_args=("--arms", "A,B", "--k-max", "1"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
            repo = clone_bundle(cell_dir / "arms" / "A" / "repo.bundle")
            log = git_log(repo)
        self.assertEqual(code, 0)
        self.assertEqual([r["terminated_by"] for r in records], ["error", "error"])
        self.assertEqual(log, ["seed", "task-01"])  # a commit even when nothing happened
        self.assertFalse(any(r["oracle"]["pass"] for r in records))
        for record in records:
            self.assertEqual(validate_record(record), [])

    def test_unreachable_endpoint_is_refused_before_any_counted_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = bench_main(["--offline", "--taskset", str(DEMO), "--out", tmp,
                                   "--provider-url", "http://127.0.0.1:9/v1", "--model", MODEL,
                                   "--skip-pin-check"])
        self.assertEqual(code, 2)
        self.assertIn("provider_unreachable", buffer.getvalue())

    def test_deadline_ends_the_task_as_deadline_and_it_is_still_committed(self):
        class Slow(DemoModel):
            def __call__(self, index, body):
                turn = super().__call__(index, body)
                if body.get("stream"):
                    turn["delay"] = 5
                return turn

        with tempfile.TemporaryDirectory() as tmp, StubServer(Slow()) as stub:
            run_bench(Path(tmp), stub, "--skip-preflight", "--deadline-s", "1",
                      offline_args=("--arms", "A", "--k-max", "1"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            (record,) = read_records(cell_dir)
        self.assertEqual(record["terminated_by"], "deadline")
        self.assertFalse(record["oracle"]["pass"])
        self.assertEqual(validate_record(record), [])

    def test_productive_turn_cap_is_per_arm_and_task(self):
        class Reader(DemoModel):
            def __call__(self, index, body):
                from tests.stub_openai import call, tools
                return tools(call("read", {"path": "calc/core.py"})) if body.get("stream") else super().__call__(index, body)

        with tempfile.TemporaryDirectory() as tmp, StubServer(Reader()) as stub:
            run_bench(Path(tmp), stub, "--max-productive-turns", "2",
                      offline_args=("--arms", "A", "--k-max", "1"))
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            (record,) = read_records(cell_dir)
        self.assertEqual(record["terminated_by"], "teto_turnos")

    def test_refuses_to_mix_two_runs_in_one_cell_directory(self):
        from tau_intent.bench.cell import CellError, CellRunner, CellSettings

        ts = load_taskset(DEMO)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "cell-x").mkdir()
            (Path(tmp) / "cell-x" / "old.txt").write_text("x")
            settings = CellSettings(out_dir=Path(tmp), taskset=ts, provider_url="http://127.0.0.1:9/v1",
                                    model=MODEL, runner_kind="other", participant_id="p", join={})
            with self.assertRaises(CellError) as ctx:
                CellRunner(settings, lambda m: None).run(
                    {"cell_id": "cell-x", "mode": "bench", "arms": ["A"], "seed": 1, "k_max": 1,
                     "deadline_s": 10, "max_productive_turns": 2})
        self.assertEqual(ctx.exception.code, "cell_exists")

    def test_a_bad_assignment_is_refused_with_a_reason(self):
        from tau_intent.bench.cell import CellError, validate_assign

        good = {"cell_id": "c1", "mode": "bench", "arms": ["A", "B"], "seed": 1, "k_max": 2,
                "deadline_s": 10, "max_productive_turns": 3}
        validate_assign(dict(good))
        for patch in ({"arms": ["A", "A"]}, {"arms": []}, {"arms": ["Z"]}, {"cell_id": "../x"},
                      {"mode": "other"}, {"deadline_s": 0}, {"k_max": "6"}):
            with self.assertRaises(CellError, msg=patch):
                validate_assign({**good, **patch})


if __name__ == "__main__":
    unittest.main()
