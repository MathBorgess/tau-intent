"""Bench V0.2: participants are model backends; the runner runs on the arena owner's machine.

Declared hardware, backend identity, Ollama metadata, no raw host anywhere, several
runners on one machine, and backend failures as infrastructure. Offline, against the
local stub (no live model, no network).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    READY = True
except ImportError:  # pragma: no cover - depends on the environment
    READY = False

from tau_intent.bench import environment
from tau_intent.bench.cell import CellRunner, CellSettings
from tau_intent.bench.cli import main as bench_main
from tau_intent.bench.record import validate_record
from tau_intent.bench.taskset import load_taskset
from tests.bench_support import DEMO, MODEL, DemoModel, read_records
from tests.stub_openai import StubServer, tools, call

ROOT = Path(__file__).resolve().parent.parent
SHOW = {"details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M",
                    "format": "gguf"}}
TAGS = [{"name": MODEL, "model": MODEL, "digest": "ab12" * 16}, {"name": "other:1b", "digest": "ff" * 32}]


def run_bench(out: Path, stub: StubServer, *extra: str):
    argv = ["--offline", "--arms", "B,A,C", "--seed", "7", "--k-max", "1", "--taskset", str(DEMO),
            "--out", str(out), "--provider-url", stub.url, "--model", MODEL, "--skip-pin-check", *extra]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = bench_main(argv)
    return code, buffer.getvalue()


def cell_dir_of(out: Path) -> Path:
    (cell_dir,) = [p for p in out.iterdir() if p.is_dir() and not p.name.startswith(".")]
    return cell_dir


def every_byte_of(out: Path) -> dict[str, bytes]:
    """Every file under ``out`` and, unpacked, every member of every bundle: name -> bytes."""
    seen: dict[str, bytes] = {}
    for path in sorted(out.rglob("*")):
        if path.is_file():
            seen[path.relative_to(out).as_posix()] = path.read_bytes()
            seen["<name>" + path.relative_to(out).as_posix()] = b""
            if path.name.endswith(".tar.gz"):
                with tarfile.open(path) as tar:
                    for member in tar.getmembers():
                        seen[f"{path.name}!{member.name}"] = b""
                        handle = tar.extractfile(member) if member.isfile() else None
                        if handle is not None:
                            seen[f"{path.name}!{member.name}"] = handle.read()
    return seen


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestDeclaredHardware(unittest.TestCase):
    def test_declared_never_reads_this_machine(self):
        def boom(*args, **kwargs):
            raise AssertionError("the declared hardware must not read this machine")

        with mock.patch.object(environment.platform, "system", boom), \
                mock.patch.object(environment.platform, "machine", boom), \
                mock.patch.object(environment.platform, "processor", boom), \
                mock.patch.object(environment.shutil, "which", boom), \
                mock.patch.object(environment, "_run", boom), \
                mock.patch.object(environment.Path, "read_text", boom):
            hw = environment.hardware_declared(chip="Apple M2", ram_gb=16, accel="metal")
        self.assertEqual(hw, {"source": "declared", "os": "unknown", "chip": "Apple M2", "ram_gb": 16.0,
                              "accel": "metal", "declared": {"chip": "Apple M2", "ram_gb": 16.0, "accel": "metal"}})

    def test_null_values_become_wire_placeholders_and_stay_null_in_declared(self):
        hw = environment.hardware_declared()
        # the arena's join and record schemas take no null: chip str, ram_gb >= 0, accel enum
        self.assertEqual((hw["chip"], hw["ram_gb"], hw["accel"]), ("unknown", 0, "other"))
        self.assertEqual(hw["declared"], {"chip": None, "ram_gb": None, "accel": None})
        self.assertEqual(hw["source"], "declared")
        with self.assertRaises(ValueError):
            environment.hardware_declared(accel="tpu")
        with self.assertRaises(ValueError):
            environment.hardware_declared(ram_gb=-1)

    def test_local_stays_v0_plus_its_source(self):
        hw = environment.hardware(chip="M3 Max", ram_gb=64, accel="metal")
        self.assertEqual(hw["source"], "local")
        self.assertEqual(set(hw), {"source", "os", "chip", "ram_gb", "accel"})

    def test_cli_declared_reaches_join_and_every_record_without_reading_the_machine(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                mock.patch.object(environment, "hardware", side_effect=AssertionError("read the machine")):
            out = Path(tmp)
            code, stdout = run_bench(out, stub, "--hardware-source", "declared", "--chip", "Ryzen 7",
                                     "--ram-gb", "32", "--accel", "cuda", "--backend-id", "b-ana-1a2b3c")
            records = read_records(cell_dir_of(out))
            cell = json.loads((cell_dir_of(out) / "cell.json").read_text())
        self.assertEqual(code, 0, stdout)
        self.assertEqual(len(records), 3)
        for record in records:
            self.assertEqual(validate_record(record), [])
            self.assertEqual(record["hardware"]["source"], "declared")
            self.assertEqual(record["hardware"]["chip"], "Ryzen 7")
            self.assertEqual(record["hardware"]["declared"], {"chip": "Ryzen 7", "ram_gb": 32.0, "accel": "cuda"})
            self.assertEqual(record["backend"]["backend_id"], "b-ana-1a2b3c")
        self.assertEqual(cell["bench_join"]["hardware"]["source"], "declared")

    def test_cli_declared_with_nothing_declared(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub:
            out = Path(tmp)
            code, stdout = run_bench(out, stub, "--hardware-source", "declared")
            records = read_records(cell_dir_of(out))
        self.assertEqual(code, 0, stdout)
        for record in records:
            self.assertEqual(validate_record(record), [])
            self.assertEqual(record["hardware"]["declared"], {"chip": None, "ram_gb": None, "accel": None})

    def test_default_is_local(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub:
            out = Path(tmp)
            run_bench(out, stub)
            records = read_records(cell_dir_of(out))
        self.assertTrue(all(r["hardware"]["source"] == "local" and "declared" not in r["hardware"]
                            for r in records))
        self.assertTrue(all(r["backend"]["backend_id"] is None for r in records))


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestBackendIdentity(unittest.TestCase):
    def test_transport_is_local_for_loopback_and_lan_otherwise(self):
        for url in ("http://127.0.0.1:11434/v1", "http://localhost:11434/v1", "http://[::1]:11434/v1",
                    "http://127.0.0.5:1/v1"):
            self.assertEqual(environment.transport_of(url), "local", url)
        for url in ("http://192.168.1.20:11434/v1", "http://10.0.0.5:11434/v1", "http://ana-laptop.lan:11434/v1"):
            self.assertEqual(environment.transport_of(url), "lan", url)

    def test_host_hash_is_over_the_host_alone(self):
        want = hashlib.sha256(b"192.168.1.20").hexdigest()
        self.assertEqual(environment.host_sha256("http://192.168.1.20:11434/v1"), want)
        self.assertEqual(environment.host_sha256("http://192.168.1.20:9/other"), want)

    def test_redaction_replaces_a_lan_host_and_leaves_loopback_alone(self):
        url = "http://192.168.1.20:11434/v1"
        text = "ConnectError to 192.168.1.20 (http://192.168.1.20:11434/v1)"
        out = environment.redact_host(text, url)
        self.assertNotIn("192.168.1.20", out)
        self.assertIn("backend-" + environment.host_sha256(url)[:12], out)
        self.assertEqual(environment.redact_host("127.0.0.1 here", "http://127.0.0.1:1/v1"), "127.0.0.1 here")


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestOllamaMetadata(unittest.TestCase):
    def test_reads_version_show_and_tags_from_the_origin(self):
        with StubServer([], ollama_version="0.9.1", show=SHOW, models=TAGS) as stub:
            meta = environment.ollama_metadata(stub.url, MODEL)
        self.assertEqual(meta["ollama_version"], "0.9.1")
        self.assertEqual(meta["details"], {"family": "qwen2", "parameter_size": "7.6B",
                                           "quantization_level": "Q4_K_M"})
        self.assertEqual(meta["digest"], "sha256:" + "ab12" * 16)
        self.assertEqual(meta["errors"], [])

    def test_a_missing_piece_is_none_and_named_by_class_only(self):
        with StubServer([], ollama_version="0.9.1") as stub:
            meta = environment.ollama_metadata(stub.url, MODEL, timeout_s=1.0)
        self.assertEqual(meta["ollama_version"], "0.9.1")
        self.assertIsNone(meta["details"])
        self.assertIsNone(meta["digest"])
        self.assertEqual(sorted(e.split(":")[0] for e in meta["errors"]), ["/api/show", "/api/tags"])
        self.assertTrue(all(e.split(": ")[1].isidentifier() for e in meta["errors"]))  # a class name, no host

    def test_unreachable_provider_is_all_none_and_fast(self):
        with StubServer([]) as stub:
            url = stub.url
        started = time.monotonic()
        meta = environment.ollama_metadata(url, MODEL, timeout_s=1.0)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual((meta["ollama_version"], meta["details"], meta["digest"]), (None, None, None))
        self.assertEqual(len(meta["errors"]), 3)

    def test_cell_records_details_version_digest_and_calls_the_api_once(self):
        with tempfile.TemporaryDirectory() as tmp, \
                StubServer(DemoModel(), ollama_version="0.9.1", show=SHOW, models=TAGS) as stub:
            out = Path(tmp)
            code, stdout = run_bench(out, stub, "--runner-kind", "ollama")
            records = read_records(cell_dir_of(out))
            cell = json.loads((cell_dir_of(out) / "cell.json").read_text())
            paths = list(stub.paths)
        self.assertEqual(code, 0, stdout)
        self.assertEqual(paths.count("/api/version"), 1)
        self.assertEqual(paths.count("/api/show"), 1)
        for record in records:
            self.assertEqual(validate_record(record), [])
            self.assertEqual(record["model"]["details"],
                             {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"})
            self.assertEqual(record["model"]["digest"], "sha256:" + "ab12" * 16)
            self.assertEqual(record["backend"], {
                "backend_id": None, "transport": "local", "ollama_version": "0.9.1",
                "provider_host_sha256": hashlib.sha256(b"127.0.0.1").hexdigest()})
            # throughput telemetry: descriptive, on every agent turn
            agent_turns = [t for t in record["turns"] if t["kind"] != "rescue"]
            self.assertTrue(agent_turns)
            for turn in agent_turns:
                self.assertIsInstance(turn["latency_ms"], int)
                self.assertIsInstance(turn["ttft_ms"], int)
        self.assertEqual(cell["ollama"]["ollama_version"], "0.9.1")

    def test_a_digest_passed_on_the_command_line_wins(self):
        with tempfile.TemporaryDirectory() as tmp, \
                StubServer(DemoModel(), ollama_version="0.9.1", show=SHOW, models=TAGS) as stub:
            out = Path(tmp)
            run_bench(out, stub, "--runner-kind", "ollama", "--digest", "sha256:" + "cd" * 32)
            records = read_records(cell_dir_of(out))
        self.assertTrue(all(r["model"]["digest"] == "sha256:" + "cd" * 32 for r in records))

    def test_other_runner_kinds_are_not_asked_for_the_ollama_api(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(), ollama_version="0.9.1", show=SHOW) as stub:
            out = Path(tmp)
            run_bench(out, stub, "--runner-kind", "lmstudio")
            records = read_records(cell_dir_of(out))
            paths = list(stub.paths)
        self.assertNotIn("/api/version", paths)
        self.assertTrue(all("details" not in r["model"] and r["backend"]["ollama_version"] is None for r in records))


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestTheRawHostNeverLeaves(unittest.TestCase):
    HOST = "127.0.0.2"  # all of 127/8 is this machine; the test says it is a LAN address

    def test_no_file_name_or_byte_of_the_bundle_carries_the_host(self):
        real = environment.is_loopback
        try:
            with StubServer(DemoModel(), host=self.HOST, ollama_version="0.9.1", show=SHOW, models=TAGS) as stub:
                pass
        except OSError:  # pragma: no cover - platforms without the 127/8 aliases
            self.skipTest("cannot bind 127.0.0.2")
        with tempfile.TemporaryDirectory() as tmp, \
                StubServer(DemoModel(), host=self.HOST, ollama_version="0.9.1", show=SHOW, models=TAGS) as stub, \
                mock.patch.object(environment, "is_loopback", lambda host: host != self.HOST and real(host)):
            self.assertIn(self.HOST, stub.url)
            out = Path(tmp)
            code, stdout = run_bench(out, stub, "--runner-kind", "ollama", "--backend-id", "b-x-123456",
                                     "--keep-workspaces")
            files = every_byte_of(out)
            records = read_records(cell_dir_of(out))
        self.assertEqual(code, 0, stdout)
        self.assertGreater(len(files), 20)
        self.assertTrue(any(name.endswith(".tar.gz") for name in files))
        self.assertNotIn(self.HOST, stdout)
        for name, data in files.items():
            self.assertNotIn(self.HOST, name)
            self.assertNotIn(self.HOST.encode(), data, name)
        for record in records:
            self.assertEqual(record["backend"]["transport"], "lan")
            self.assertEqual(record["backend"]["provider_host_sha256"],
                             hashlib.sha256(self.HOST.encode()).hexdigest())
            self.assertNotIn(self.HOST, json.dumps(record))
        cell = json.loads(next(v for k, v in files.items() if k.endswith("/cell.json")))
        self.assertIn("backend-" + hashlib.sha256(self.HOST.encode()).hexdigest()[:12], cell["provider_url"])


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestSeveralRunnersOnOneMachine(unittest.TestCase):
    def test_three_cells_at_once_are_independent_and_complete(self):
        home_before = Path.home() / ".gitconfig"
        before = home_before.read_bytes() if home_before.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_home = tmp / "home"
            fake_home.mkdir()
            stubs = [StubServer(DemoModel(), ollama_version=f"0.9.{n}", show=SHOW, models=TAGS) for n in range(3)]
            for stub in stubs:
                stub.__enter__()
            try:
                env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT),
                       "HOME": str(fake_home), "NO_NETWORK": "1"}
                env.pop("GIT_CONFIG_GLOBAL", None)
                procs = []
                for n, stub in enumerate(stubs):
                    out = tmp / f"out-{n}"
                    cmd = [sys.executable, "-m", "tau_intent.bench.cli", "--offline", "--arms", "B,A,C",
                           "--seed", "7", "--k-max", "2", "--taskset", str(DEMO), "--out", str(out),
                           "--provider-url", stub.url, "--model", MODEL, "--runner-kind", "ollama",
                           "--hardware-source", "declared", "--backend-id", f"b-{n}-000000",
                           "--skip-pin-check"]
                    procs.append(subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=subprocess.PIPE,
                                                  stderr=subprocess.STDOUT, text=True))
                outputs = [p.communicate(timeout=240)[0] for p in procs]
            finally:
                for stub in stubs:
                    stub.__exit__(None, None, None)
            for proc, output in zip(procs, outputs):
                self.assertEqual(proc.returncode, 0, output)
            seen_cells = set()
            for n, stub in enumerate(stubs):
                out = tmp / f"out-{n}"
                cell_dir = cell_dir_of(out)
                seen_cells.add(str(cell_dir))
                records = read_records(cell_dir)
                self.assertEqual(len(records), 6)
                self.assertEqual([(r["arm_id"], r["task_index"]) for r in records],
                                 [("B", 1), ("A", 1), ("C", 1), ("B", 2), ("A", 2), ("C", 2)])
                for record in records:
                    self.assertEqual(validate_record(record), [])
                    self.assertTrue(record["oracle"]["pass"])
                    self.assertEqual(record["backend"]["backend_id"], f"b-{n}-000000")
                    self.assertEqual(record["backend"]["ollama_version"], f"0.9.{n}")
                for arm in "ABC":
                    self.assertTrue((cell_dir / "arms" / arm / "repo.bundle").is_file())
                self.assertTrue((cell_dir / "cell.json").is_file())
                self.assertTrue(list(out.glob("*.tar.gz")))
                self.assertFalse((out / ".workspaces").exists(), "workspaces are cleaned and live under --out")
                self.assertGreater(len(stub.chat_requests()), 6)  # each process talked to its own backend only
            self.assertEqual(len(seen_cells), 3)
            # no global git config was written, not in the process's HOME nor in the real one
            self.assertFalse((fake_home / ".gitconfig").exists())
            self.assertFalse((fake_home / ".config" / "git").exists())
        after = home_before.read_bytes() if home_before.exists() else None
        self.assertEqual(before, after)

    def test_workspace_roots_are_unique_and_under_out(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub:
            out = Path(tmp)
            run_bench(out, stub, "--keep-workspaces")
            roots = sorted((out / ".workspaces").iterdir())
        self.assertEqual(len(roots), 3)  # one per arm, kept on request, none in the shared temp dir
        self.assertEqual(len({r.name for r in roots}), 3)

    def test_the_runner_listens_on_no_port(self):
        source = "".join(p.read_text() for p in (ROOT / "src" / "tau_intent" / "bench").glob("*.py"))
        self.assertNotIn(".bind(", source)
        self.assertNotIn("serve(", source)


def make_cell(out: Path, stub: StubServer, *, backend_id: str = "b-1", kind: str = "ollama") -> CellRunner:
    ts = load_taskset(DEMO)
    join = {"participant_id": backend_id, "runner_version": environment.runner_version(),
            "tau_intent_sha": environment.tau_intent_sha(), "task_set_sha": ts.sha,
            "model": {"id": MODEL, "digest": None, "runner_kind": kind},
            "hardware": environment.hardware_declared()}
    settings = CellSettings(out_dir=out, taskset=ts, provider_url=stub.url, model=MODEL, runner_kind=kind,
                            participant_id=backend_id, join=join, backend_id=backend_id, skip_preflight=True)
    emitted: list[dict] = []
    runner = CellRunner(settings, emitted.append)
    runner.emitted = emitted  # type: ignore[attr-defined]
    return runner


ASSIGN = {"cell_id": "cell-v02", "mode": "bench", "arms": ["B", "A", "C"], "seed": 7, "k_max": 2,
          "deadline_s": 30, "max_productive_turns": 8}


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestBackendFailuresAreInfrastructure(unittest.TestCase):
    def test_a_backend_that_dies_mid_cell_ends_the_cell_without_retries_or_hanging(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(), die_after=3) as stub:
            runner = make_cell(Path(tmp), stub)
            started = time.monotonic()
            outcome = runner.run(dict(ASSIGN))
            elapsed = time.monotonic() - started
            requests_seen = len(stub.requests)
            records = read_records(outcome.cell_dir)
            emitted = runner.emitted
            has_cell_json = (outcome.cell_dir / "cell.json").is_file()
            has_bundle = bool(list(Path(tmp).glob("*.tar.gz")))
        self.assertLess(elapsed, ASSIGN["deadline_s"] * 2)
        # B/1 completed (calls 0-1); A/1 lost its call 3 (reset); the call was never repeated
        self.assertEqual(requests_seen, 4)
        self.assertEqual([r["terminated_by"] for r in records], ["completed", "error", "error", "error", "error", "error"])
        self.assertEqual([(r["arm_id"], r["task_index"]) for r in records],
                         [("B", 1), ("A", 1), ("C", 1), ("B", 2), ("A", 2), ("C", 2)])
        self.assertIsNone(records[0]["error"])
        for record in records[1:]:
            self.assertEqual(validate_record(record), [])
            self.assertEqual(record["error"]["kind"], "backend_unreachable")
            self.assertTrue(record["error"]["detail"])
        self.assertRegex(records[1]["error"]["detail"], r"^(RemoteProtocolError|ReadError|ConnectError)")
        self.assertTrue(outcome.truncated)
        done = [m for m in emitted if m["type"] == "bench_cell_done"]
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["records"], done[0]["truncated"]), (6, True))
        self.assertIn("backend_unreachable", [m.get("code") for m in emitted if m["type"] == "bench_error"])
        self.assertTrue(has_cell_json and has_bundle)  # manifest and bundle are still written

    def test_a_backend_that_never_answers_is_bounded_by_the_deadline(self):
        def silent(index, body):
            return tools(call("bash", {"command": "true"}), delay=30)

        with tempfile.TemporaryDirectory() as tmp, StubServer(silent) as stub:
            runner = make_cell(Path(tmp), stub)
            started = time.monotonic()
            outcome = runner.run({**ASSIGN, "arms": ["A"], "k_max": 1, "deadline_s": 2})
            elapsed = time.monotonic() - started
            (record,) = read_records(outcome.cell_dir)
        self.assertLess(elapsed, 20)
        self.assertEqual(record["terminated_by"], "deadline")
        self.assertIsNone(record["error"])

    def test_an_http_error_is_a_provider_error_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer([], status=lambda i: 500) as stub:
            runner = make_cell(Path(tmp), stub)
            outcome = runner.run({**ASSIGN, "arms": ["A"], "k_max": 1})
            (record,) = read_records(outcome.cell_dir)
            seen = len(stub.requests)
        self.assertEqual(seen, 1, "a failed call must not be repeated: retries would change the treatment")
        self.assertEqual(record["terminated_by"], "error")
        self.assertEqual(record["error"]["kind"], "provider_error")
        self.assertEqual(validate_record(record), [])

    def test_refused_connection_on_the_first_unit_is_an_error_unit_then_the_rest_is_not_run(self):
        with StubServer([]) as stub:
            url_stub = stub
        # the stub is closed: its port refuses connections
        with tempfile.TemporaryDirectory() as tmp:
            runner = make_cell(Path(tmp), url_stub)
            started = time.monotonic()
            outcome = runner.run(dict(ASSIGN))
            elapsed = time.monotonic() - started
            records = read_records(outcome.cell_dir)
        self.assertLess(elapsed, 60)
        self.assertEqual(len(records), 6)
        self.assertTrue(all(r["terminated_by"] == "error" and r["error"]["kind"] == "backend_unreachable"
                            for r in records))
        self.assertIn("ConnectError", records[0]["error"]["detail"])
        self.assertTrue(all(validate_record(r) == [] for r in records))
        self.assertTrue(all("not run" in r["error"]["detail"] for r in records[1:]))


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestRecordContractV02(unittest.TestCase):
    def base(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub:
            run_bench(Path(tmp), stub)
            return read_records(cell_dir_of(Path(tmp)))[0]

    def test_terminated_by_error_requires_an_error_and_other_endings_forbid_it(self):
        record = self.base()
        self.assertEqual(validate_record(record), [])
        bad = {**record, "terminated_by": "error", "error": None}
        self.assertTrue(validate_record(bad))
        bad = {**record, "terminated_by": "error", "error": {"kind": "whatever", "detail": "x"}}
        self.assertTrue(validate_record(bad))
        good = {**record, "terminated_by": "error", "error": {"kind": "backend_unreachable", "detail": "x"}}
        self.assertEqual(validate_record(good), [])
        bad = {**record, "error": {"kind": "backend_unreachable", "detail": "x"}}
        self.assertTrue(validate_record(bad))

    def test_hardware_source_and_backend_are_checked(self):
        record = self.base()
        self.assertTrue(validate_record({**record, "hardware": {**record["hardware"], "source": "guessed"}}))
        self.assertTrue(validate_record({**record, "backend": {**record["backend"], "transport": "wan"}}))
        self.assertTrue(validate_record({**record, "backend": {**record["backend"], "provider_host_sha256": "x"}}))
        self.assertTrue(validate_record({**record, "turns": [{"turn_index": 1, "kind": "productive",
                                                              "latency_ms": -1}]}))


if __name__ == "__main__":
    unittest.main()
