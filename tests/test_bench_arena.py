"""S6: the runner against a minimal in-process fake arena (WebSocket + HTTP).

The fake arena speaks the protocol of contract §3: it receives ``register`` and
``bench_join``, sends ``bench_assign`` / ``bench_stop``, collects the runner's
messages and takes the bundle on ``POST /bench/artifacts/:cellId``. The model is
the same scripted local stub as in the offline tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    import websockets  # noqa: F401
    READY = True
except ImportError:  # pragma: no cover - depends on the environment
    READY = False

from tau_intent.bench.cli import main as bench_main
from tau_intent.bench.record import validate_record
from tests.bench_support import DEMO, MODEL, DemoModel
from tests.stub_openai import StubServer

PIN = "4242"


class FakeArena:
    """Holds everything the runner sent; ``script(msg, arena)`` reacts to it."""

    def __init__(self, assigns, *, script=None, upload_status=200, drop_first_connection=False):
        self.assigns = assigns
        self.script = script or (lambda msg, arena: None)
        self.upload_status = upload_status
        self.drop_first_connection = drop_first_connection
        self.received: list[dict] = []
        self.registers: list[dict] = []
        self.joins: list[dict] = []
        self.uploads: list[dict] = []
        self.events: list[tuple[str, float]] = []
        self.connections = 0
        self.ws_port = 0
        self.http_port = 0
        self._ws = None
        self._loop = None
        self._ready = threading.Event()

    # ---- websocket side (own loop in a thread)
    async def _handler(self, ws):
        self.connections += 1
        self.registers.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "heartbeat", "ts": 1}))  # noise before `registered`
        await ws.send(json.dumps({"type": "registered", "session_id": "s-1"}))
        self.joins.append(json.loads(await ws.recv()))
        if self.drop_first_connection and self.connections == 1:
            await ws.close()
            return
        self._ws = ws
        for assign in self.assigns:
            await ws.send(json.dumps(assign))
        try:
            async for raw in ws:
                message = json.loads(raw)
                self.received.append(message)
                self.events.append((message["type"], time.monotonic()))
                result = self.script(message, self)
                if asyncio.iscoroutine(result):
                    await result
        except Exception:  # noqa: BLE001 - a closing socket ends the arena's reading
            pass

    def send(self, message):
        """Send from any thread."""
        asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(message)), self._loop)

    def _run_ws(self):
        from websockets.asyncio.server import serve

        async def main():
            self._loop = asyncio.get_running_loop()
            async with serve(self._handler, "127.0.0.1", 0) as server:
                self.ws_port = server.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop.wait()

        self._stop = None

        async def wrapper():
            self._stop = asyncio.Event()
            self._stop_loop = asyncio.get_running_loop()
            await main()

        asyncio.run(wrapper())

    # ---- http side
    def _start_http(self):
        arena = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                arena.uploads.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
                arena.events.append(("upload", time.monotonic()))
                payload = json.dumps({"ok": arena.upload_status == 200}).encode()
                self.send_response(arena.upload_status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()

    def __enter__(self):
        self._start_http()
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()
        assert self._ready.wait(10)
        return self

    def __exit__(self, *exc):
        self._stop_loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)
        self.httpd.shutdown()
        self.httpd.server_close()

    def of(self, kind):
        return [m for m in self.received if m["type"] == kind]


def assign(cell_id="cell-1", mode="bench", arms=("B", "A"), k_max=2, **extra):
    return {"type": "bench_assign", "cell_id": cell_id, "mode": mode, "arms": list(arms), "seed": 7,
            "k_max": k_max, "deadline_s": 60, "max_productive_turns": 8, **extra}


def run_runner(arena: FakeArena, stub: StubServer, out: Path, *extra: str) -> tuple[int, str]:
    argv = ["--server", f"ws://127.0.0.1:{arena.ws_port}/ws", "--http-url", f"http://127.0.0.1:{arena.http_port}",
            "--pin", PIN, "--participant-id", "p-7", "--nickname", "Ana", "--provider-url", stub.url,
            "--model", MODEL, "--taskset", str(DEMO), "--out", str(out), "--skip-pin-check", "--once", *extra]
    buffer = io.StringIO()
    result: dict = {}

    def target():
        with contextlib.redirect_stdout(buffer):
            result["code"] = bench_main(argv)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=90)  # a runner that never finishes is a failed test, not a hung suite
    if thread.is_alive():
        raise AssertionError("the runner did not finish in 90 s\n" + buffer.getvalue())
    return result["code"], buffer.getvalue()


@unittest.skipUnless(READY, "needs pytest, tau-ai and websockets (pip install .[bench])")
class TestAgainstAFakeArena(unittest.TestCase):
    def test_full_cell_register_join_progress_records_done_and_upload(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(arms=("B", "A", "C"))]) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
            cell_json = (Path(tmp) / "cell-1" / "cell.json").read_bytes()
        self.assertEqual(code, 0, stdout)
        register, join = arena.registers[0], arena.joins[0]
        self.assertEqual(register, {"type": "register", "participant_id": "p-7", "nickname": "Ana",
                                    "pin": PIN, "runner": "tau-intent", "model": MODEL})
        self.assertEqual(join["type"], "bench_join")
        self.assertEqual(arena.connections, 1)
        self.assertEqual(set(join), {"type", "participant_id", "runner_version", "tau_intent_sha",
                                     "task_set_sha", "model", "hardware"})
        self.assertEqual(join["participant_id"], register["participant_id"])
        self.assertEqual(join["model"]["runner_kind"], "other")  # the stub's port is not a known runner's
        self.assertEqual(set(join["hardware"]), {"os", "chip", "ram_gb", "accel"})
        self.assertEqual(len(join["task_set_sha"]), 64)

        records = [m["record"] for m in arena.of("bench_record")]
        self.assertEqual([(r["arm_id"], r["task_index"]) for r in records],
                         [("B", 1), ("A", 1), ("C", 1), ("B", 2), ("A", 2), ("C", 2)])
        self.assertTrue(all(m["cell_id"] == "cell-1" for m in arena.of("bench_record")))
        self.assertTrue(all(validate_record(r) == [] for r in records))
        self.assertTrue(all(r["participant_id"] == "p-7" and r["session_pin_hash"] ==
                            hashlib.sha256(PIN.encode()).hexdigest() for r in records))

        progress = arena.of("bench_progress")
        self.assertTrue({"start", "turn", "oracle", "done"} <= {m["phase"] for m in progress})
        turn = [m for m in progress if m["phase"] == "turn"][0]
        self.assertEqual(set(turn) - {"type"}, {"cell_id", "arm_id", "task_index", "phase", "turn",
                                               "tokens_in", "tokens_out"})
        (done,) = arena.of("bench_cell_done")
        self.assertEqual((done["records"], done["truncated"]), (6, False))
        self.assertEqual(done["manifest_sha256"], hashlib.sha256(cell_json).hexdigest())
        self.assertEqual(arena.of("bench_error"), [])

        (upload,) = arena.uploads
        self.assertEqual(upload["path"], "/bench/artifacts/cell-1")
        self.assertEqual(upload["headers"]["content-type"], "application/gzip")
        self.assertEqual(hashlib.sha256(upload["body"]).hexdigest(), upload["headers"]["x-bench-sha256"])
        self.assertEqual(upload["headers"]["x-participant-id"], "p-7")
        self.assertEqual(upload["body"][:2], b"\x1f\x8b")
        with tarfile.open(fileobj=io.BytesIO(upload["body"])) as tar:
            self.assertIn("records.jsonl", tar.getnames())
        order = [name for name, _ in arena.events]
        self.assertLess(order.index("upload"), order.index("bench_cell_done"))  # done means everything is stored

    def test_qualification_assignment_runs_only_q0(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(q_first_attempt_wrong=True)) as stub, \
                FakeArena([assign(cell_id="q-1", mode="qualification", arms=("A",))]) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
        self.assertEqual(code, 0, stdout)
        records = [m["record"] for m in arena.of("bench_record")]
        self.assertEqual([(r["arm_id"], r["task_index"], r["oracle"]["pass"]) for r in records],
                         [("Q", 0, False), ("Q", 0, True)])
        self.assertEqual({m["arm_id"] for m in arena.of("bench_progress")}, {"Q"})
        self.assertEqual(arena.of("bench_cell_done")[0]["records"], 2)

    def test_stop_finishes_the_current_unit_marks_the_rest_stopped_and_still_uploads(self):
        def script(message, arena):
            if message["type"] == "bench_progress" and message["arm_id"] == "A" and message["phase"] == "start":
                arena.send({"type": "bench_stop", "cell_id": "cell-1"})

        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel(slow_plain_arm=1.0)) as stub, \
                FakeArena([assign()], script=script) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
        self.assertEqual(code, 0, stdout)
        records = [m["record"] for m in arena.of("bench_record")]
        self.assertEqual([(r["arm_id"], r["task_index"], r["terminated_by"]) for r in records],
                         [("B", 1, "completed"), ("A", 1, "completed"), ("B", 2, "stopped"), ("A", 2, "stopped")])
        for record in records[2:]:
            self.assertEqual(validate_record(record), [])
            self.assertFalse(record["oracle"]["pass"])
            self.assertEqual(record["turns"], [])
        (done,) = arena.of("bench_cell_done")
        self.assertEqual((done["records"], done["truncated"]), (4, True))
        self.assertEqual(len(arena.uploads), 1)

    def test_a_second_assignment_for_a_running_cell_is_refused(self):
        def script(message, arena):
            if message["type"] == "bench_progress" and message["phase"] == "start" and not getattr(arena, "sent", 0):
                arena.sent = 1
                arena.send(assign(cell_id="cell-2"))

        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(arms=("A",), k_max=1)], script=script) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
            self.assertFalse((Path(tmp) / "cell-2").exists())
        self.assertEqual(code, 0, stdout)
        (error,) = arena.of("bench_error")
        self.assertEqual((error["cell_id"], error["code"]), ("cell-2", "cell_running"))
        self.assertEqual(arena.of("bench_cell_done")[0]["cell_id"], "cell-1")

    def test_a_refused_assignment_is_reported_and_the_runner_stays_up_for_the_next_one(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(cell_id="bad", arms=("Z",)), assign(cell_id="good", arms=("A",), k_max=1)]) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
        self.assertEqual(code, 0, stdout)
        (error,) = arena.of("bench_error")
        self.assertEqual((error["cell_id"], error["code"]), ("bad", "bad_assign"))
        self.assertEqual([m["cell_id"] for m in arena.of("bench_cell_done")], ["good"])

    def test_failed_upload_is_reported_and_the_bundle_stays_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(arms=("A",), k_max=1)], upload_status=500) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
            self.assertTrue((Path(tmp) / "cell-1.tar.gz").is_file())
            self.assertIn("cell-1.tar.gz", stdout)
            kept = json.loads((Path(tmp) / "cell-1.upload.json").read_text())
        self.assertEqual(code, 0, stdout)
        self.assertEqual(arena.of("bench_error")[0]["code"], "upload_failed")
        self.assertTrue(kept["upload"].startswith("FAILED"))
        self.assertEqual(len(arena.of("bench_record")), 1)  # the records were not lost either

    def test_connection_drop_before_the_assignment_is_survived_by_reconnecting(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(arms=("A",), k_max=1)], drop_first_connection=True) as arena:
            code, stdout = run_runner(arena, stub, Path(tmp))
        self.assertEqual(code, 0, stdout)
        self.assertEqual(len(arena.registers), 2)  # registered again after the reconnect
        self.assertEqual(len(arena.of("bench_record")), 1)

    def test_runner_never_sends_a_record_the_contract_forbids(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer(DemoModel()) as stub, \
                FakeArena([assign(arms=("A", "B"), k_max=1)]) as arena:
            run_runner(arena, stub, Path(tmp))
        for message in arena.of("bench_record"):
            record = message["record"]
            self.assertEqual(record["tokens"]["cost_usd"], 0)
            self.assertIs(record["draft"], True)


if __name__ == "__main__":
    unittest.main()
