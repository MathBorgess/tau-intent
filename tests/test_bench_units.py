"""S6 building blocks: task set, hashes, oracle, per-arm git, record validator, environment."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import pytest  # noqa: F401
    HAVE_PYTEST = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_PYTEST = False

from tau_intent.bench import environment
from tau_intent.bench.client import fit_for_wire, http_base, upload_bundle
from tau_intent.bench.gitws import ArmWorkspace, GitError
from tau_intent.bench.oracle import OracleError, oracle_dirs, run_oracle
from tau_intent.bench.record import config_sha256, validate_record
from tau_intent.bench.taskset import TasksetError, hash_task, hash_taskset, list_files, load_taskset
from tests.bench_support import DEMO
from tests.stub_openai import StubServer, text


def valid_record(arm="B"):
    harness = {"A": "tau", "B": "tau_intent", "C": "tau_intent_llm_rescue", "Q": "tau"}[arm]
    flags = {"capture": arm in "BC", "gate": arm in "BC", "project": arm in "BC", "serve": arm in "BC",
             "llm_rescue": arm == "C"}
    return {
        "schema_version": "gambiarra-coleta-2", "draft": True, "cell_id": "c1", "participant_id": "p1",
        "session_pin_hash": None, "arm_id": arm, "harness_id": harness, "task_set_sha": "a" * 64,
        "task_index": 0 if arm == "Q" else 1, "task_id": "t", "task_hash": "b" * 64,
        "model": {"id": "m", "digest": None, "runner_kind": "ollama"},
        "hardware": {"os": "Linux", "chip": "x", "ram_gb": 16, "accel": "cpu"},
        "arm_order": ["B", "A", "C"], "seed": 7,
        "mechanism": {"flags": flags}, "oracle": {"pass": True, "per_test": []},
        "evolution": {}, "tokens": {"in": 1, "out": 1, "rescue_in": 0, "rescue_out": 0,
                                    "source": "provider_usage", "cost_usd": 0},
        "turns": [{"turn_index": 1, "kind": "productive", "tokens_in": 1, "tokens_out": 1, "tool_calls": 0}],
        "mechanism_telemetry": {"verdict": "PASSA", "productive_turns": 1, "block_turns": 0},
        "terminated_by": "completed", "started_at": "2026-10-01T00:00:00Z", "ended_at": "2026-10-01T00:00:01Z",
        "artifacts": {},
    }


class TestTaskset(unittest.TestCase):
    def reference_hash_of(self, root: Path):
        """The contract's encoding, written out independently of the implementation."""
        def entries(base: Path):
            files = sorted((p.relative_to(base).as_posix(), p) for p in base.rglob("*")
                           if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
            return b"".join(rel.encode() + b"\0" + p.read_bytes() for rel, p in files)
        return entries

    def test_hash_encoding_is_the_contracts(self):
        entries = self.reference_hash_of(DEMO)
        ts = load_taskset(DEMO)
        self.assertEqual(ts.sha, hashlib.sha256(entries(DEMO)).hexdigest())
        for task in ts.tasks:
            expected = hashlib.sha256(task.statement.read_bytes() + entries(task.tests)).hexdigest()
            self.assertEqual(task.hash, expected)
        self.assertEqual([t.index for t in ts.tasks], [1, 2])
        self.assertEqual(ts.qualification.id, "Q0")

    def test_any_byte_of_a_hidden_test_or_statement_changes_the_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_ = Path(tmp) / "ts"
            shutil.copytree(DEMO, copy_)
            before = load_taskset(copy_)
            test = copy_ / "tasks" / "02" / "tests" / "test_t02_mul.py"
            test.write_bytes(test.read_bytes() + b"\n# x\n")
            after = load_taskset(copy_)
            self.assertNotEqual(before.sha, after.sha)
            self.assertNotEqual(before.task(2).hash, after.task(2).hash)
            self.assertEqual(before.task(1).hash, after.task(1).hash)

    def test_bytecode_and_cache_directories_never_enter_a_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_ = Path(tmp) / "ts"
            shutil.copytree(DEMO, copy_)
            before = load_taskset(copy_)
            (copy_ / "tasks" / "01" / "tests" / "__pycache__").mkdir()
            (copy_ / "tasks" / "01" / "tests" / "__pycache__" / "x.pyc").write_bytes(b"\0")
            (copy_ / "seed" / ".pytest_cache").mkdir()
            (copy_ / "seed" / ".pytest_cache" / "v").write_text("x")
            (copy_ / "seed" / "calc" / "core.pyc").write_bytes(b"\0")
            self.assertEqual(load_taskset(copy_).sha, before.sha)
            self.assertNotIn("__pycache__/x.pyc", [r for r, _ in list_files(copy_)])

    def test_malformed_task_sets_are_refused_with_a_reason(self):
        def broken(mutate):
            with tempfile.TemporaryDirectory() as tmp:
                copy_ = Path(tmp) / "ts"
                shutil.copytree(DEMO, copy_)
                manifest = json.loads((copy_ / "taskset.json").read_text())
                mutate(manifest, copy_)
                (copy_ / "taskset.json").write_text(json.dumps(manifest))
                with self.assertRaises(TasksetError):
                    load_taskset(copy_)

        broken(lambda m, d: m.update(schema="tg-taskset-2"))
        broken(lambda m, d: m["tasks"][1].update(index=3))  # not contiguous
        broken(lambda m, d: m["tasks"][0].update(statement="tasks/01/nope.md"))
        broken(lambda m, d: m.update(language="rust"))
        broken(lambda m, d: m.update(test_runner="pytest"))
        broken(lambda m, d: m.update(python=">=9.0"))
        with self.assertRaises(TasksetError):
            load_taskset("/nonexistent/taskset")


@unittest.skipUnless(HAVE_PYTEST, "the oracle needs pytest (pip install .[bench])")
class TestOracle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ts = load_taskset(DEMO)
        self.ws = self.root / "ws"
        shutil.copytree(self.ts.seed, self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_fails_task_one_and_the_failing_test_is_named(self):
        result = run_oracle(self.ts, 1, self.ws)
        self.assertFalse(result["pass"])
        self.assertGreaterEqual(result["errors"] + result["failed"], 1)
        self.assertTrue(any(t["outcome"] != "passed" for t in result["per_test"]))

    def test_oracle_of_task_k_includes_the_hidden_tests_of_tasks_below_it(self):
        self.assertEqual([label for label, _ in oracle_dirs(self.ts, 2)], ["01", "02"])
        self.assertEqual([label for label, _ in oracle_dirs(self.ts, 0)], ["q"])
        shutil.copytree(self.ts.root / "reference" / "01", self.ws, dirs_exist_ok=True)
        shutil.copytree(self.ts.root / "reference" / "02", self.ws, dirs_exist_ok=True)
        result = run_oracle(self.ts, 2, self.ws)
        self.assertTrue(result["pass"], result["output_tail"])
        self.assertEqual({t["nodeid"].split("/")[1] for t in result["per_test"]}, {"01", "02"})

    def test_hidden_tests_are_never_inside_the_workspace_and_the_workspace_is_not_touched(self):
        shutil.copytree(self.ts.root / "reference" / "01", self.ws, dirs_exist_ok=True)
        before = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*"))
        run_oracle(self.ts, 1, self.ws)
        after = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*"))
        self.assertEqual(before, after)  # no bytecode, no cache, no copied tests
        self.assertFalse([p for p in after if "test_t0" in p])

    def test_workspace_is_the_only_thing_on_pythonpath(self):
        # a regression: task 1's code in the workspace is what the hidden test imports
        shutil.copytree(self.ts.root / "reference" / "01", self.ws, dirs_exist_ok=True)
        (self.ws / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")  # sub removed
        self.assertFalse(run_oracle(self.ts, 1, self.ws)["pass"])

    def test_timeout_is_a_failure_not_a_hang(self):
        with tempfile.TemporaryDirectory() as tmp:
            slow = Path(tmp) / "ts"
            shutil.copytree(DEMO, slow)
            (slow / "tasks" / "01" / "tests" / "test_t01_sub.py").write_text(
                "import time\n\ndef test_slow():\n    time.sleep(30)\n")
            result = run_oracle(load_taskset(slow), 1, self.ws, timeout_s=1)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["pass"])

    def test_a_missing_runner_is_an_instrument_error_not_a_failed_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "ts"
            shutil.copytree(DEMO, odd)
            manifest = json.loads((odd / "taskset.json").read_text())
            manifest["test_runner"] = ["python", "-c", "print('No module named pytest')"]
            (odd / "taskset.json").write_text(json.dumps(manifest))
            with self.assertRaises(OracleError):
                run_oracle(load_taskset(odd), 1, self.ws)
        with self.assertRaises(OracleError):
            run_oracle(self.ts, 1, self.root / "nope")


class TestArmWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = ArmWorkspace(Path(self._tmp.name) / "arm")
        self.seed = self.ws.create(load_taskset(DEMO).seed)

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_commit_then_one_commit_per_task_even_when_empty(self):
        first = self.ws.commit("task-01")
        second = self.ws.commit("task-02")
        self.assertEqual(self.ws.log(), ["seed", "task-01", "task-02"])
        self.assertEqual(len({self.seed, first, second}), 3)

    def test_untracked_files_are_committed_and_counted_as_created(self):
        (self.ws.path / "calc" / "ops.py").write_text("def mul(a, b):\n    return a * b\n")
        (self.ws.path / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
        after = self.ws.commit("task-01")
        evo = self.ws.evolution(self.seed, after)
        self.assertEqual(evo.untracked_created, ["calc/ops.py"])
        self.assertEqual((evo.files_changed, evo.insertions, evo.deletions), (2, 3, 1))
        self.assertEqual(evo.edit_size, 4)
        self.assertIn("calc/ops.py", self.ws.patch(self.seed, after))

    def test_bytecode_and_the_intent_log_stay_out_of_the_series(self):
        (self.ws.path / "__pycache__").mkdir()
        (self.ws.path / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
        (self.ws.path / "intents.jsonl").write_text("{}\n")
        (self.ws.path / ".pytest_cache").mkdir()
        (self.ws.path / ".pytest_cache" / "v").write_text("x")
        after = self.ws.commit("task-01")
        self.assertEqual(self.ws.evolution(self.seed, after).files_changed, 0)

    def test_binary_files_are_counted_without_line_numbers(self):
        (self.ws.path / "logo.bin").write_bytes(b"\x00\x01\x02")
        evo = self.ws.evolution(self.seed, self.ws.commit("task-01"))
        self.assertEqual((evo.files_changed, evo.insertions, evo.deletions), (1, 0, 0))
        self.assertEqual(evo.untracked_created, ["logo.bin"])

    def test_participants_git_config_cannot_change_the_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "gitconfig"
            config.write_text("[commit]\n\tgpgsign = true\n[core]\n\thooksPath = /nonexistent\n"
                              "[user]\n\tname = Someone Else\n")
            old = os.environ.get("GIT_CONFIG_GLOBAL")
            os.environ["GIT_CONFIG_GLOBAL"] = str(config)
            try:
                ws = ArmWorkspace(Path(tmp) / "other")
                ws.create(load_taskset(DEMO).seed)
                (ws.path / "x.txt").write_text("x")
                ws.commit("task-01")
                author = ws._git("log", "-1", "--format=%an").strip()
            finally:
                os.environ.pop("GIT_CONFIG_GLOBAL") if old is None else os.environ.update(GIT_CONFIG_GLOBAL=old)
        self.assertEqual(author, "tau-intent-bench")

    def test_bundle_round_trips_and_a_git_failure_is_an_error(self):
        self.ws.commit("task-01")
        target = Path(self._tmp.name) / "out" / "repo.bundle"
        self.ws.bundle(target)
        self.assertTrue(target.stat().st_size > 0)
        with self.assertRaises(GitError):
            self.ws._git("no-such-subcommand")


class TestRecordValidator(unittest.TestCase):
    def test_a_well_formed_record_of_each_arm_is_valid(self):
        for arm in "ABCQ":
            self.assertEqual(validate_record(valid_record(arm)), [], arm)

    def problems(self, mutate, arm="B"):
        record = valid_record(arm)
        mutate(record)
        return validate_record(record)

    def test_bijection_between_arm_and_harness(self):
        self.assertTrue(self.problems(lambda r: r.update(harness_id="tau")))
        self.assertTrue(self.problems(lambda r: r.update(harness_id="tau_intent"), arm="A"))
        self.assertTrue(self.problems(lambda r: r.update(harness_id="tau_intent"), arm="Q"))

    def test_task_index_rules_for_q_and_for_the_arms(self):
        self.assertTrue(self.problems(lambda r: r.update(task_index=1), arm="Q"))
        self.assertTrue(self.problems(lambda r: r.update(task_index=0), arm="A"))

    def test_arm_a_and_q_carry_no_mechanism(self):
        for arm in "AQ":
            self.assertTrue(self.problems(lambda r: r["mechanism"]["flags"].update(capture=True), arm=arm))
            self.assertTrue(self.problems(lambda r: r["mechanism_telemetry"].update(block_turns=1), arm=arm))
            self.assertTrue(self.problems(lambda r: r["turns"].append(
                {"turn_index": 2, "kind": "block", "tokens_in": 1, "tokens_out": 1, "tool_calls": 0}), arm=arm))

    def test_tokens_are_never_estimated_and_cost_is_zero(self):
        self.assertTrue(self.problems(lambda r: r["tokens"].update(cost_usd=0.01)))
        self.assertTrue(self.problems(lambda r: r["tokens"].update(source="estimated")))
        self.assertTrue(self.problems(lambda r: r["tokens"].update(source="missing")))  # but all figures present
        self.assertEqual(self.problems(lambda r: r["tokens"].update(source="missing", **{"in": None})), [])
        self.assertTrue(self.problems(lambda r: r["tokens"].update(**{"in": None})))  # null needs source missing
        self.assertTrue(self.problems(lambda r: r["tokens"].update(out=1.5)))

    def test_i2_a_ratio_over_an_empty_denominator_is_null(self):
        bad = {"aproveitamento_do_bloco": {"servidas": 0, "razao": 0.0}}
        self.assertTrue(self.problems(lambda r: r["mechanism_telemetry"].update(bad)))
        ok = {"aproveitamento_do_bloco": {"servidas": 0, "razao": None},
              "cobertura_de_captura": {"estrita": None, "denominadores": {"estrita": 0}}}
        self.assertEqual(self.problems(lambda r: r["mechanism_telemetry"].update(ok)), [])
        bad2 = {"cobertura_de_captura": {"estrita": 1.0, "denominadores": {"estrita": 0}}}
        self.assertTrue(self.problems(lambda r: r["mechanism_telemetry"].update(bad2)))

    def test_draft_enums_and_required_fields(self):
        self.assertTrue(self.problems(lambda r: r.update(draft=False)))
        self.assertTrue(self.problems(lambda r: r.update(terminated_by="crashed")))
        self.assertTrue(self.problems(lambda r: r["model"].update(runner_kind="vllm")))
        self.assertTrue(self.problems(lambda r: r["hardware"].update(accel="tpu")))
        self.assertTrue(self.problems(lambda r: r.pop("task_hash")))
        self.assertTrue(self.problems(lambda r: r.update(seed="7")))
        self.assertTrue(self.problems(lambda r: r["mechanism"]["flags"].update(llm_rescue=True)))

    def test_config_digest_is_one_stable_string_over_the_five_files(self):
        hashes = {"b": "2", "a": "1"}
        self.assertEqual(config_sha256(hashes), config_sha256({"a": "1", "b": "2"}))
        self.assertEqual(len(config_sha256(hashes)), 64)


class TestEnvironment(unittest.TestCase):
    def test_runner_kind_is_guessed_from_the_well_known_ports(self):
        self.assertEqual(environment.guess_runner_kind("http://localhost:11434/v1"), "ollama")
        self.assertEqual(environment.guess_runner_kind("http://localhost:1234/v1"), "lmstudio")
        self.assertEqual(environment.guess_runner_kind("http://localhost:8080/v1"), "llamacpp")
        self.assertEqual(environment.guess_runner_kind("http://localhost:9000/v1"), "other")

    def test_the_mechanism_digest_is_a_stable_content_hash(self):
        first = environment.tau_intent_sha()
        self.assertEqual(first, environment.tau_intent_sha())
        self.assertEqual(len(first), 64)

    def test_hardware_shape_and_overrides(self):
        hw = environment.hardware(chip="M3 Max", ram_gb=64, accel="metal")
        self.assertEqual(hw["chip"], "M3 Max")
        self.assertEqual((hw["ram_gb"], hw["accel"]), (64, "metal"))
        self.assertIn(environment.hardware()["accel"], environment.ACCELS)
        with self.assertRaises(ValueError):
            environment.hardware(accel="tpu")

    def test_ollama_digest_is_attested_locally_other_runners_give_none(self):
        models = [{"name": "qwen2.5-coder:7b", "digest": "abc123"}, {"name": "llama3:latest", "digest": "sha256:def"}]
        with StubServer([text("x")], models=models) as stub:
            self.assertEqual(environment.model_digest(stub.url, "qwen2.5-coder:7b", "ollama"), "sha256:abc123")
            self.assertEqual(environment.model_digest(stub.url, "llama3", "ollama"), "sha256:def")
            self.assertIsNone(environment.model_digest(stub.url, "unknown", "ollama"))
            self.assertIsNone(environment.model_digest(stub.url, "qwen2.5-coder:7b", "lmstudio"))
        self.assertIsNone(environment.model_digest("http://127.0.0.1:9/v1", "m", "ollama"))

    def test_preflight_reports_reachability_and_usage_without_fixing_either(self):
        with StubServer([text("ok")]) as stub:
            report = environment.preflight_endpoint(stub.url, "m", 7, timeout_s=5)
            body = stub.requests[0]
        self.assertEqual((report["reachable"], report["usage_in_stream"]), (True, True))
        self.assertEqual((body["temperature"], body["seed"]), (0, 7))
        with StubServer([text("ok")], usage=False) as stub:
            self.assertEqual(environment.preflight_endpoint(stub.url, "m", 7, timeout_s=5)["usage_in_stream"], False)
        down = environment.preflight_endpoint("http://127.0.0.1:9/v1", "m", 7, timeout_s=2)
        self.assertFalse(down["reachable"])

    def test_a_record_over_the_arenas_frame_cap_is_shrunk_in_the_open_and_the_rest_is_untouched(self):
        record = valid_record("B")
        record["oracle"]["per_test"] = [{"nodeid": f"tests/01/t.py::test_{i}", "outcome": "passed"} for i in range(40000)]
        record["oracle"]["per_test"].append({"nodeid": "tests/01/t.py::test_bad", "outcome": "failed"})
        record["mechanism_telemetry"]["recibo"] = {"x": "y" * 2000}
        message = {"type": "bench_record", "cell_id": "c1", "record": record}
        small = fit_for_wire(message, limit=200_000)
        self.assertLess(len(json.dumps(small)), 200_000)
        self.assertEqual([t["outcome"] for t in small["record"]["oracle"]["per_test"]], ["failed"])
        self.assertEqual(small["record"]["oracle"]["per_test_dropped"], 40000)
        self.assertIn("oracle.per_test (passed tests)", small["record"]["wire_truncated"])
        self.assertEqual(small["record"]["oracle"]["pass"], True)  # what the arena indexes is intact
        self.assertEqual(len(record["oracle"]["per_test"]), 40001)  # the caller's record is not mutated
        normal = {"type": "bench_record", "cell_id": "c1", "record": valid_record("A")}
        self.assertIs(fit_for_wire(normal), normal)
        progress = {"type": "bench_progress", "cell_id": "c1"}
        self.assertIs(fit_for_wire(progress), progress)

    def test_http_base_from_the_websocket_url(self):
        self.assertEqual(http_base("ws://10.0.0.5:3000/ws"), "http://10.0.0.5:3000")
        self.assertEqual(http_base("wss://arena.example/ws"), "https://arena.example")

    def test_upload_posts_the_gzip_body_and_raises_on_failure(self):
        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                seen["path"], seen["type"] = self.path, self.headers["Content-Type"]
                self.send_response(500 if seen.get("fail") else 200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp) / "c.tar.gz"
                bundle.write_bytes(b"\x1f\x8bpayload")
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                detail = upload_bundle(base, bundle, "c", "sha", "p")
                self.assertTrue(detail.startswith("HTTP 200"))
                self.assertEqual((seen["body"], seen["path"], seen["type"]),
                                 (b"\x1f\x8bpayload", "/bench/artifacts/c", "application/gzip"))
                seen["fail"] = True
                with self.assertRaises(RuntimeError):
                    upload_bundle(base, bundle, "c", "sha", "p")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
