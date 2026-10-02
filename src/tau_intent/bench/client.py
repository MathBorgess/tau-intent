"""The arena side of the runner: WebSocket session, HTTP upload, offline rehearsal.

Why a thread: a cell blocks (the rescue provider is a synchronous HTTP call, the
oracle is a subprocess, a local model can take minutes per turn). The arena pings
the runner every 30 s and drops a connection that misses pongs, so the cell runs
in a worker thread and the event loop that owns the socket is never blocked.

Messages from the worker travel through a thread-safe queue; if the socket drops
the unsent ones are kept and re-sent after a reconnect (``register`` and
``bench_join`` are sent again). Records are written to ``records.jsonl`` first, so
nothing depends on the LAN staying up.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from tau_intent.bench import RUNNER_NAME
from tau_intent.bench.cell import CellError, CellOutcome, CellRunner, CellSettings, validate_assign

Log = Callable[[str], None]


# ---------------------------------------------------------------------- upload
def http_base(ws_url: str) -> str:
    """``ws://host:3000/ws`` -> ``http://host:3000`` (``wss`` -> ``https``)."""
    parsed = urlparse(ws_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
    return urlunparse((scheme, parsed.netloc, "", "", "", ""))


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def upload_bundle(base_url: str, bundle: Path, cell_id: str, sha256: str, participant_id: str,
                  timeout_s: float = 600.0) -> str:
    """``POST /bench/artifacts/:cellId`` with the gzip body. Raises on any failure."""
    size = bundle.stat().st_size
    with bundle.open("rb") as handle:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/bench/artifacts/{cell_id}", data=handle, method="POST",
            headers={"Content-Type": "application/gzip", "Content-Length": str(size),
                     "X-Bench-Sha256": sha256, "X-Participant-Id": participant_id})
        try:
            with _DIRECT.open(request, timeout=timeout_s) as response:
                body = response.read(300).decode("utf-8", "replace")
                return f"HTTP {response.status} {body}".strip()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} {exc.read(200).decode('utf-8', 'replace')}") from exc


# ---------------------------------------------------------------------- online
@dataclasses.dataclass
class OnlineConfig:
    server: str
    pin: str
    participant_id: str
    nickname: str
    model: str
    join: dict[str, Any]
    settings: CellSettings
    once: bool = False
    log: Log = print
    reconnect_max_s: float = 30.0
    #: Base URL of the arena's HTTP side; default: the WebSocket URL on http(s).
    http_url: str | None = None


#: The arena's WebSocket frames are capped at 1 MiB; stay clear of the cap.
WIRE_LIMIT_BYTES = 900_000
REGISTER_TIMEOUT_S = 15.0


def register_message(cfg: OnlineConfig) -> dict[str, Any]:
    return {"type": "register", "participant_id": cfg.participant_id, "nickname": cfg.nickname,
            "pin": cfg.pin, "runner": RUNNER_NAME, "model": cfg.model}


def join_message(cfg: OnlineConfig) -> dict[str, Any]:
    return {"type": "bench_join", **cfg.join}


async def run_online(cfg: OnlineConfig) -> int:
    import websockets

    loop = asyncio.get_running_loop()
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    unsent: list[dict[str, Any]] = []
    state: dict[str, Any] = {"cell_id": None, "stop": None, "finished": 0, "failed": 0}

    def emit(message: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(outbox.put_nowait, message)

    def finished(outcome: str) -> None:
        """``ok`` / ``failed`` (ran, hit a fatal) / ``refused`` (never started)."""
        state["cell_id"], state["stop"] = None, None
        if outcome != "refused":
            state["finished" if outcome == "ok" else "failed"] += 1

    def start_cell(assign: dict[str, Any]) -> None:
        stop = threading.Event()
        state["cell_id"], state["stop"] = assign.get("cell_id"), stop
        settings = dataclasses.replace(
            cfg.settings,
            upload=lambda bundle, cell_id, sha: upload_bundle(
                cfg.http_url or http_base(cfg.server), bundle, cell_id, sha, cfg.participant_id))

        def work() -> None:
            outcome_kind = "failed"
            try:
                outcome = CellRunner(settings, emit, stop, cfg.log).run(assign)
                outcome_kind = "ok" if outcome.fatal is None else "failed"
            except CellError as exc:
                outcome_kind = "refused"
                emit({"type": "bench_error", "cell_id": assign.get("cell_id") or "unknown",
                      "code": exc.code, "message": str(exc)})
                cfg.log(f"cell refused [{exc.code}]: {exc}")
            except Exception as exc:  # noqa: BLE001 - the arena must hear about a crash
                emit({"type": "bench_error", "cell_id": assign.get("cell_id") or "unknown",
                      "code": "runner_crash", "message": f"{type(exc).__name__}: {exc}"[:500]})
                cfg.log(f"cell crashed: {type(exc).__name__}: {exc}")
            finally:
                loop.call_soon_threadsafe(finished, outcome_kind)

        threading.Thread(target=work, name=f"cell-{assign.get('cell_id')}", daemon=True).start()

    def handle(raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        kind = message.get("type")
        if kind == "bench_assign":
            if state["cell_id"] is not None:
                # A new assignment for a running cell is refused: the owner must stop first.
                emit({"type": "bench_error", "cell_id": message.get("cell_id") or state["cell_id"],
                      "code": "cell_running",
                      "message": f"cell {state['cell_id']} is still running; send bench_stop first"})
                return
            try:
                # Cheap and synchronous on purpose: a malformed assignment is refused
                # before it can occupy the runner (and block the next, valid one).
                validate_assign(dict(message))
            except CellError as exc:
                emit({"type": "bench_error", "cell_id": message.get("cell_id") or "unknown",
                      "code": exc.code, "message": str(exc)})
                cfg.log(f"assignment refused [{exc.code}]: {exc}")
                return
            cfg.log(f"assigned {message.get('cell_id')}: mode={message.get('mode')} arms={message.get('arms')}")
            start_cell(message)
        elif kind == "bench_stop":
            if state["cell_id"] is not None and message.get("cell_id") == state["cell_id"]:
                cfg.log(f"stop requested for {state['cell_id']}: finishing the current (arm, task)")
                state["stop"].set()
        elif kind == "error":
            cfg.log(f"server error: {message.get('code')}: {message.get('message')}")
            cell_dir = cfg.settings.out_dir / str(message.get("cell_id") or "")
            if message.get("cell_id") and cell_dir.is_dir():
                with (cell_dir / "server_errors.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        # heartbeat, challenge, world messages: not ours

    async def pump(ws: Any) -> None:
        while True:
            message = unsent.pop(0) if unsent else await outbox.get()
            try:
                await ws.send(json.dumps(fit_for_wire(message), ensure_ascii=False))
            except Exception:
                unsent.insert(0, message)
                raise

    delay = 1.0
    while True:
        try:
            async with websockets.connect(cfg.server, max_size=None) as ws:
                delay = 1.0
                await ws.send(json.dumps(register_message(cfg)))
                # The arena answers `register` with `registered`; `bench_join` before
                # that is refused (bench_not_registered). Anything else that arrives
                # meanwhile (heartbeat) waits its turn.
                early: list[str | bytes] = []
                while True:
                    raw = await asyncio.wait_for(ws.recv(), REGISTER_TIMEOUT_S)
                    try:
                        reply = json.loads(raw)
                    except ValueError:
                        continue
                    if reply.get("type") == "registered":
                        break
                    if reply.get("type") == "error":
                        raise ConnectionError(f"register refused: {reply.get('message') or reply.get('code')}")
                    early.append(raw)
                await ws.send(json.dumps(join_message(cfg)))
                for raw in early:
                    handle(raw)
                cfg.log(f"connected to {cfg.server} as {cfg.participant_id}; waiting for bench_assign")
                sender = asyncio.create_task(pump(ws))
                receiver = asyncio.create_task(_receive(ws, handle))
                try:
                    while True:
                        if cfg.once and (state["finished"] or state["failed"]) and state["cell_id"] is None \
                                and outbox.empty() and not unsent:
                            await asyncio.sleep(0.3)  # let the last frame leave
                            return 0 if not state["failed"] else 1
                        done, _ = await asyncio.wait({sender, receiver}, timeout=0.2,
                                                     return_when=asyncio.FIRST_COMPLETED)
                        if done:
                            for task in done:
                                task.result()  # raises the connection error, if any
                            raise ConnectionError("connection closed by the arena")
                finally:
                    sender.cancel()
                    receiver.cancel()
        except (OSError, ConnectionError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as exc:
            if cfg.once and (state["finished"] or state["failed"]) and state["cell_id"] is None:
                return 0 if not state["failed"] else 1
            cfg.log(f"connection lost ({type(exc).__name__}: {exc}); retrying in {delay:.0f}s"
                    f"{' (a cell is still running; its records are safe on disk)' if state['cell_id'] else ''}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, cfg.reconnect_max_s)


def fit_for_wire(message: dict[str, Any], limit: int = WIRE_LIMIT_BYTES) -> dict[str, Any]:
    """Keep a frame under the arena's 1 MiB cap without losing what it indexes.

    Only ``bench_record`` can grow. The full record is already in ``records.jsonl``
    and in the bundle; what goes on the wire is shrunk in a declared order and says
    so in ``wire_truncated`` (never silently).
    """
    def size(m: dict[str, Any]) -> int:
        return len(json.dumps(m, ensure_ascii=False).encode("utf-8"))

    if message.get("type") != "bench_record" or size(message) <= limit:
        return message
    record = json.loads(json.dumps(message["record"]))
    dropped: list[str] = []

    def candidate() -> dict[str, Any]:
        record["wire_truncated"] = list(dropped)
        return {**message, "record": record}

    oracle = record.get("oracle") or {}
    per_test = oracle.get("per_test") or []
    if per_test:
        oracle["per_test"] = [t for t in per_test if t.get("outcome") != "passed"][:200]
        oracle["per_test_dropped"] = len(per_test) - len(oracle["per_test"])
        dropped.append("oracle.per_test (passed tests)")
    telemetry = record.get("mechanism_telemetry") or {}
    for key in sorted((k for k in telemetry if k not in ("verdict", "productive_turns", "block_turns",
                                                         "bloco_vazio", "tokens_served")),
                      key=lambda k: -len(json.dumps(telemetry[k], default=str))):
        if size(candidate()) <= limit:
            break
        telemetry.pop(key)
        dropped.append(f"mechanism_telemetry.{key}")
    if size(candidate()) > limit and record.get("turns"):
        record["turns"] = []
        dropped.append("turns")
    return candidate()


async def _receive(ws: Any, handle: Callable[[str | bytes], None]) -> None:
    async for raw in ws:
        handle(raw)


# --------------------------------------------------------------------- offline
def run_offline(settings: CellSettings, assign: dict[str, Any], log: Log = print) -> CellOutcome:
    """The owner's own rehearsal (E0): no server, same cell, same records, same bundle."""
    def emit(message: dict[str, Any]) -> None:
        if message["type"] == "bench_progress" and message["phase"] in ("start", "done"):
            log(f"  {message['arm_id']} task {message['task_index']}: {message['phase']}")

    return CellRunner(settings, emit, threading.Event(), log).run(assign)
