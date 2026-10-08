"""One bench cell (machine x model): its arms, interleaved by task index.

Protocol of a cell (design §4, contract §2-§5):

* **Interleaved order.** ``k = 1`` for each arm in the owner's order, then
  ``k = 2``, ... so a truncation cuts every arm at the same ``k`` and the pair
  stays balanced.
* **One workspace per arm**, a git repository born from ``seed/``; **one commit per
  task** after the agent finishes, untracked files included, whether or not the
  oracle passed. The trajectory follows the state the arm itself produced: a failed
  task is data, not a reset.
* **One session per task**, no compaction: a fresh tau harness for every (arm, task).
* **A deadline and a productive-turn cap per (arm, task)**, both from the assignment.
* **Oracle outside the workspace**: hidden tests of tasks 1..k in a temporary directory.
* **Qualification** (``mode: qualification``): only Q0, plain tau, at most two attempts,
  ``arm_id: "Q"``.
* **Frontier strand** (``provider_api`` other than ``openai-completions``): the same
  cell over a vendor's native protocol, through a local credential proxy. Two things
  change, both declared in ``cell.json``: a unit lost to infrastructure (quota spent,
  credential refused, provider or proxy down) may be **discarded and run again from
  the state before it** (``infra_retries``; the discarded attempt is tagged in the arm's
  repository and listed in the record, its tokens included), and a task set may carry
  a frozen **host regression** suite, run after every unit as a descriptive layer.

Everything runs in a worker thread (see ``client.py``): the rescue provider and the
oracle block, and the arena's WebSocket keep-alive must not.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
import tarfile
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tau_intent import pin
from tau_intent import provider_api as api_mod
from tau_intent.adapters.code import CodeAdapter
from tau_intent.bench import environment, record as rec
from tau_intent.bench.gitws import ArmWorkspace, safe_name
from tau_intent.bench.oracle import OracleError, check_runner, run_oracle, run_regression
from tau_intent.bench.taskset import Qualification, Task, TaskSet, TasksetError, load_taskset
from tau_intent.cli import flags_from_args
from tau_intent.config import config_hashes
from tau_intent.harness_factory import ProviderSpec, build_harness, system_prompt_sha256
from tau_intent.rescue_provider import sumarizador_local, sumarizador_nativo
from tau_intent.store import IntentStore
from tau_intent.supervisor import ArmIsolationError, montar, run_task
from tau_intent.telemetry import resumir_tokens, uso_do_provedor

Emit = Callable[[dict[str, Any]], None]

ASSIGN_KEYS = ("cell_id", "mode", "arms", "seed", "k_max", "deadline_s", "max_productive_turns")
MAX_QUALIFICATION_ATTEMPTS = 2
#: After this many consecutive units lost to the backend, the cell stops asking it.
MAX_CONSECUTIVE_BACKEND_FAILURES = 2
#: HTTP status of the provider (through the proxy) -> infrastructure ``error.kind``.
#: Read only on a native-protocol cell: the local strand keeps V0.2's classification.
INFRA_STATUS = {429: "quota_exhausted", 401: "credentials_unavailable", 403: "credentials_unavailable",
                500: "provider_unavailable", 502: "provider_unavailable", 503: "provider_unavailable",
                504: "provider_unavailable", 529: "provider_unavailable"}
#: A provider can also fail *inside* a 200 stream (Anthropic ``overloaded_error``, a Codex
#: ``response.failed`` for a rate limit, Gemini ``RESOURCE_EXHAUSTED``): then only the
#: provider's own error text says it was infrastructure. Native cells only, in this order.
INFRA_TEXT = ((re.compile(r"rate.?limit|usage.?limit|quota|resource.?exhausted|too many requests", re.I),
               "quota_exhausted"),
              (re.compile(r"overloaded|service.?unavailable|server.?error|temporarily unavailable", re.I),
               "provider_unavailable"))


class CellError(Exception):
    """The cell cannot start or must stop: reported as ``bench_error``, never swallowed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class CellSettings:
    out_dir: Path
    taskset: TaskSet
    provider_url: str
    model: str
    runner_kind: str
    participant_id: str
    join: dict[str, Any]
    pin_hash: str | None = None
    api_key: str = "local"
    oracle_timeout_s: int = 300
    rescue_timeout_s: float | None = None
    keep_workspaces: bool = False
    skip_preflight: bool = False
    #: The participant backend this process serves (V0.2); stored as ``backend.backend_id``.
    backend_id: str | None = None
    #: ``upload(bundle_path, cell_id, sha256) -> detail``; raises on failure.
    upload: Callable[[Path, str, str], str] | None = None
    # ---- frontier strand (defaults = the local strand, unchanged)
    provider_api: str = api_mod.OPENAI_COMPLETIONS
    sampling: str = api_mod.SAMPLING_STAMPED
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    #: A unit lost to infrastructure is discarded and run again, up to this many times.
    #: 0 keeps V0.2's rule (never retried): what is lost is recorded as error.
    infra_retries: int = 0
    #: Wait before retry n is ``min(infra_wait_s * 2**(n-1), infra_max_wait_s)``.
    infra_wait_s: float = 60.0
    infra_max_wait_s: float = 3600.0
    #: Label of the strand in ``cell.json`` (``None``: the local strand).
    strand: str | None = None
    #: Anthropic only: prepend the subscription identity block (declared, off by default).
    anthropic_oauth_identity: bool = False

    def spec(self, seed: int, timeout_s: float) -> ProviderSpec:
        return ProviderSpec(self.provider_url, self.model, seed, timeout_s=timeout_s, api_key=self.api_key,
                            api=self.provider_api, sampling=self.sampling,
                            reasoning_effort=self.reasoning_effort, max_output_tokens=self.max_output_tokens,
                            anthropic_oauth_identity=self.anthropic_oauth_identity)

    @property
    def native(self) -> bool:
        return self.provider_api != api_mod.OPENAI_COMPLETIONS


@dataclass
class Unit:
    arm_id: str
    index: int  # task index; 0 for the qualification round
    task: Task | Qualification
    attempt: int = 1

    @property
    def label(self) -> str:
        return f"{self.arm_id}/task-{self.index:02d}" if self.arm_id != "Q" else f"Q/attempt-{self.attempt}"


@dataclass
class CellOutcome:
    cell_id: str
    cell_dir: Path
    records: list[dict[str, Any]]
    truncated: bool
    bundle: Path | None
    manifest_sha256: str | None
    upload: str | None
    fatal: str | None = None


def validate_assign(assign: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ASSIGN_KEYS if key not in assign]
    if missing:
        raise CellError("bad_assign", f"bench_assign is missing {missing}")
    cell_id = assign["cell_id"]
    if not isinstance(cell_id, str) or not cell_id or safe_name(cell_id) != cell_id:
        raise CellError("bad_assign", f"cell_id must be [A-Za-z0-9_.-]+ (got {cell_id!r})")
    if assign["mode"] not in ("qualification", "bench"):
        raise CellError("bad_assign", f"mode {assign['mode']!r}")
    arms = assign["arms"]
    if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms) \
            or any(a not in ("A", "B", "C") for a in arms):
        raise CellError("bad_assign", f"arms must be a non-empty list of distinct A/B/C (got {arms!r})")
    for key in ("seed", "k_max", "deadline_s", "max_productive_turns"):
        value = assign[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise CellError("bad_assign", f"{key} must be an int")
    if assign["k_max"] < 1 or assign["deadline_s"] < 1 or assign["max_productive_turns"] < 1:
        raise CellError("bad_assign", "k_max, deadline_s and max_productive_turns must be >= 1")
    return assign


def plan(assign: dict[str, Any], taskset: TaskSet) -> list[Unit]:
    """The ordered units of the cell."""
    if assign["mode"] == "qualification":
        if taskset.qualification is None:
            raise CellError("no_qualification", "the task set has no qualification task Q0")
        return [Unit("Q", 0, taskset.qualification, attempt=n + 1)
                for n in range(MAX_QUALIFICATION_ATTEMPTS)]
    k_eff = min(assign["k_max"], len(taskset.tasks))
    return [Unit(arm, task.index, task) for task in taskset.tasks[:k_eff] for arm in assign["arms"]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _event_json(event: Any) -> Any:
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json", by_alias=True)
    if dataclasses.is_dataclass(event):
        return dataclasses.asdict(event)
    return {"repr": repr(event)}


class CellRunner:
    def __init__(self, settings: CellSettings, emit: Emit, stop: threading.Event | None = None,
                 log: Callable[[str], None] = lambda message: None) -> None:
        self.s = settings
        self.emit = emit
        self.stop = stop or threading.Event()
        self._log = log
        self.log = lambda message: log(self._s(message))
        self._workspaces: dict[str, ArmWorkspace] = {}
        self._tmp_roots: list[Path] = []

    def _s(self, text: str) -> str:
        """The backend's raw host never leaves this process (V0.2): scrub every text we write."""
        return environment.redact_host(text, self.s.provider_url)

    # ------------------------------------------------------------------ entry
    def run(self, assign: dict[str, Any]) -> CellOutcome:
        assign = validate_assign(dict(assign))
        cell_id = assign["cell_id"]
        cell_dir = self.s.out_dir / cell_id
        if cell_dir.exists() and any(cell_dir.iterdir()):
            raise CellError("cell_exists", f"{cell_dir} already has data; refusing to mix two runs")
        cell_dir.mkdir(parents=True, exist_ok=True)
        self.cell_id, self.cell_dir, self.assign = cell_id, cell_dir, assign

        # The runner recomputes, never trusts: the task set must still be the one it joined with.
        try:
            taskset = load_taskset(self.s.taskset.root)
        except TasksetError as exc:
            raise CellError("taskset_invalid", str(exc)) from exc
        if taskset.sha != self.s.taskset.sha:
            raise CellError("taskset_changed", "the task set changed on disk after bench_join "
                                               f"({self.s.taskset.sha[:12]} -> {taskset.sha[:12]})")
        self.taskset = taskset
        try:
            check_runner(taskset)
        except OracleError as exc:
            raise CellError("oracle_unavailable", str(exc)) from exc

        started_at = rec.now_iso()
        preflight = {"skipped": True}
        if not self.s.skip_preflight and self.s.native:
            preflight = self._preflight_native(assign)
        elif not self.s.skip_preflight:
            preflight = environment.preflight_endpoint(
                self.s.provider_url, self.s.model, assign["seed"], api_key=self.s.api_key,
                timeout_s=max(60.0, float(assign["deadline_s"])))
            preflight["error"] = None if preflight["error"] is None else self._s(preflight["error"])
            if not preflight["reachable"]:
                raise CellError("provider_unreachable", self._s(
                    f"{self.s.provider_url} did not answer: {preflight['error']}"))
            if not preflight["usage_in_stream"]:
                self.log("warning: the endpoint returned no usage in the stream; tokens will be "
                         "recorded as missing (never estimated)")
        self._describe_backend()
        units = plan(assign, taskset)
        self.records: list[dict[str, Any]] = []
        self.unit_rows: list[dict[str, Any]] = []
        fatal: str | None = None
        truncated = False
        qualification_passed: bool | None = None
        stopped = False
        backend_failures = 0  # consecutive units lost to the backend
        last_label = ""

        for position, unit in enumerate(units):
            if unit.arm_id == "Q" and qualification_passed:
                break  # Q0 passed: no second attempt
            if self.stop.is_set() or fatal is not None:
                stopped = True
                for left in units[position:]:
                    if left.arm_id == "Q" and qualification_passed:
                        continue
                    self._append(self._stopped_record(left, "stopped"), left)
                truncated = True
                break
            if backend_failures and (backend_failures >= MAX_CONSECUTIVE_BACKEND_FAILURES
                                     or not environment.backend_reachable(self.s.provider_url)):
                # Infrastructure, not data: the backend is gone. Nothing is retried; what is
                # left is recorded as error (never as a failed attempt) and the cell closes.
                detail = f"not run: the backend stayed unreachable after {last_label}"
                self._error("backend_unreachable", f"{detail}; remaining units recorded as error")
                for left in units[position:]:
                    if left.arm_id == "Q" and qualification_passed:
                        continue
                    self._append(self._stopped_record(
                        left, "error", {"kind": "backend_unreachable", "detail": detail}), left)
                truncated = True
                break
            try:
                row = self._run_unit_with_retries(unit)
            except ArmIsolationError as exc:
                fatal = f"arm isolation violated in {unit.label}: {exc}"
                self._error("arm_isolation", fatal)
                row = None
            except OracleError as exc:
                fatal = f"oracle could not run in {unit.label}: {exc}"
                self._error("oracle_unavailable", fatal)
                row = None
            if row is None:
                self._append(self._stopped_record(unit, "error", {"kind": "instrument_error",
                                                                  "detail": self._s(fatal or "")[:300]}), unit)
                truncated = True
                continue
            last_label = unit.label
            lost = (row.get("error") or {}).get("kind") in rec.INFRA_ERROR_KINDS
            backend_failures = backend_failures + 1 if lost else 0
            if unit.arm_id == "Q":
                qualification_passed = bool(row["oracle"]["pass"])

        ended_at = rec.now_iso()
        manifest_sha, bundle, upload_detail = self._finalize(
            assign, started_at, ended_at, preflight, truncated, fatal, qualification_passed)
        self._cleanup()
        self.emit({"type": "bench_cell_done", "cell_id": cell_id, "records": len(self.records),
                   "manifest_sha256": manifest_sha, "truncated": bool(truncated or stopped)})
        return CellOutcome(cell_id, cell_dir, self.records, bool(truncated or stopped), bundle,
                           manifest_sha, upload_detail, fatal)

    # ------------------------------------------------------------------- unit
    def _workspace(self, unit: Unit) -> ArmWorkspace:
        key = unit.arm_id if unit.arm_id != "Q" else f"Q{unit.attempt}"
        if key not in self._workspaces:
            # Unique and under this process's own --out: concurrent runners on one machine
            # share no temp path (V0.2). Outside the cell dir, so it never enters the bundle.
            base = self.s.out_dir / ".workspaces"
            base.mkdir(parents=True, exist_ok=True)
            root = Path(tempfile.mkdtemp(prefix=f"{self.cell_id}-{key}-", dir=base))
            self._tmp_roots.append(root)
            ws = ArmWorkspace(root)
            seed = unit.task.seed if isinstance(unit.task, Qualification) else self.taskset.seed
            ws.create(seed)
            self._workspaces[key] = ws
        return self._workspaces[key]

    def _unit_dir(self, unit: Unit) -> Path:
        if unit.arm_id == "Q":
            return self.cell_dir / "qualification" / f"attempt-{unit.attempt}"
        return self.cell_dir / "arms" / unit.arm_id / f"task-{unit.index:02d}"

    def _arm_dir(self, unit: Unit) -> Path:
        if unit.arm_id == "Q":
            return self.cell_dir / "qualification" / f"attempt-{unit.attempt}"
        return self.cell_dir / "arms" / unit.arm_id

    def _progress(self, unit: Unit, phase: str, turn: int | None = None,
                  tokens: tuple[int, int] | None = None) -> None:
        message: dict[str, Any] = {"type": "bench_progress", "cell_id": self.cell_id,
                                   "arm_id": unit.arm_id, "task_index": unit.index, "phase": phase}
        if turn is not None:
            message["turn"] = turn
        if tokens is not None:
            message["tokens_in"], message["tokens_out"] = tokens
        self.emit(message)

    def _error(self, code: str, message: str) -> None:
        message = self._s(message)
        self.log(f"error [{code}]: {message}")
        self.emit({"type": "bench_error", "cell_id": self.cell_id, "code": code, "message": message})

    def _describe_backend(self) -> None:
        """Once per cell: what the provider says about itself (Ollama only), plus ``backend``.

        Ollama attests its version, the model's details and digest; the digest passed on
        the command line wins. Nothing here carries the raw host.
        """
        model = dict(self.s.join.get("model") or {})
        self.ollama: dict[str, Any] | None = None
        if self.s.runner_kind == "ollama":
            self.ollama = environment.ollama_metadata(self.s.provider_url, self.s.model)
            model["details"] = self.ollama["details"]
            if not model.get("digest") and self.ollama["digest"]:
                model["digest"] = self.ollama["digest"]
        if self.s.native:
            model.update(self.s.spec(self.assign["seed"], 1.0).describe())
        self.model_block = model
        self.backend = environment.backend_block(
            self.s.provider_url, self.s.backend_id, (self.ollama or {}).get("ollama_version"))

    def _run_unit(self, unit: Unit) -> tuple[dict[str, Any], dict[str, Any]]:
        assign = self.assign
        ws = self._workspace(unit)
        unit_dir = self._unit_dir(unit)
        unit_dir.mkdir(parents=True, exist_ok=True)
        arm_dir = self._arm_dir(unit)
        flags = flags_from_args(["--arm", rec.FLAG_ARM_BY_ARM_ID[unit.arm_id]])
        statement = unit.task.statement_text()
        task_id = unit.task.id
        before = ws.head()
        store = IntentStore(arm_dir)
        started_at = rec.now_iso()
        self.log(f"{unit.label}: start ({task_id})")
        self._progress(unit, "start")

        state = {"turn": 0, "in": 0, "out": 0, "known": True}
        transcript = (unit_dir / "transcript.jsonl").open("w", encoding="utf-8")
        seq = {"n": 0}

        def on_event(event: Any) -> None:
            kind = getattr(event, "type", None)
            if kind == "message_update":
                return  # token-by-token duplicates of message_end
            seq["n"] += 1
            transcript.write(self._s(json.dumps({"seq": seq["n"], "t": rec.now_iso(), "event": _event_json(event)},
                                                ensure_ascii=False, default=str)) + "\n")
            transcript.flush()
            if kind == "turn_end":
                state["turn"] += 1
                uso = uso_do_provedor(getattr(event, "message", None))
                if uso is None:
                    state["known"] = False
                else:
                    state["in"] += uso["tokens_in"]
                    state["out"] += uso["tokens_out"]
                self._progress(unit, "turn", state["turn"],
                               (state["in"], state["out"]) if state["known"] else None)

        spec = self.s.spec(assign["seed"], float(assign["deadline_s"]))

        async def session() -> Any:
            harness = build_harness(ws.path, flags, spec, home=ws.home, max_retries=0)
            try:
                summarizer = None
                if flags.llm_rescue and self.s.native:
                    summarizer = sumarizador_nativo(spec, timeout_s=self.s.rescue_timeout_s, wire=harness.wire)
                elif flags.llm_rescue:
                    summarizer = sumarizador_local(
                        self.s.provider_url, self.s.model, assign["seed"], api_key=self.s.api_key,
                        timeout_s=self.s.rescue_timeout_s, wire=harness.wire)
                result = await run_task(
                    ws.path, flags, prompt=statement, task_id=f"task-{unit.index:02d}",
                    max_productive_turns=assign["max_productive_turns"], harness=harness, store=store,
                    summarizer_fn=summarizer, adapter=CodeAdapter(base=before),
                    modelo_produtor=self.s.model, modelo_consumidor=self.s.model,
                    deadline_s=float(assign["deadline_s"]), on_event=on_event)
                return result, summarizer
            finally:
                net_errors.extend(harness.wire.network_errors)
                statuses.extend(harness.wire.statuses)
                await harness.aclose()

        net_errors: list[dict[str, str]] = []
        statuses: list[int] = []
        result = summarizer = None
        failure: Exception | None = None
        try:
            result, summarizer = asyncio.run(session())
        except ArmIsolationError:
            raise
        except Exception as exc:  # noqa: BLE001 - an instrument failure is recorded, not hidden
            failure = exc
            self._error("unit_error", f"{unit.label}: {type(exc).__name__}: {exc}"[:500])
        finally:
            transcript.close()

        after = ws.commit(f"task-{unit.index:02d}" if unit.arm_id != "Q" else f"q0-attempt-{unit.attempt}")
        if not flags.capture and store.path.exists():
            raise ArmIsolationError(f"{store.path} exists for an arm with capture off")

        self._progress(unit, "oracle")
        oracle = run_oracle(self.taskset, unit.index, ws.path, timeout_s=self.s.oracle_timeout_s)
        regression = None
        if unit.arm_id != "Q":
            regression = run_regression(self.taskset, ws.path, timeout_s=self.s.oracle_timeout_s)
        evolution = ws.evolution(before, after)

        # ---- artifacts of this unit
        (unit_dir / "diff.patch").write_text(ws.patch(before, after), encoding="utf-8")
        (unit_dir / "oracle.json").write_text(json.dumps(oracle, indent=2, ensure_ascii=False), encoding="utf-8")
        if regression is not None:
            (unit_dir / "regression.json").write_text(json.dumps(regression, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")
        served = montar("", statement, result.bloco if result else "")
        (unit_dir / "prompt.txt").write_text(served, encoding="utf-8")
        tel = result.telemetry if result else {}
        terminated = "error" if failure is not None else tel.get("encerramento", "error")
        manifest = {
            "arm_id": unit.arm_id, "task_index": unit.index, "task_id": task_id,
            "flags": rec.flags_dict(flags),
            "run": result.manifest if result else None,
            "bench": {"deadline_s": assign["deadline_s"], "max_productive_turns": assign["max_productive_turns"],
                      "seed": assign["seed"], "model": self.s.model, "provider_url": self._s(self.s.provider_url),
                      "system_prompt_sha256": system_prompt_sha256(),
                      "rescue_model": self.s.model if flags.llm_rescue else None,
                      "attempt": unit.attempt,
                      **({"protocol": spec.describe()} if self.s.native else {})},
            "error": None if failure is None else self._s(f"{type(failure).__name__}: {failure}"),
        }
        (unit_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                                                encoding="utf-8")

        if result is None:
            tokens = {"in": None, "out": None, "rescue_in": None, "rescue_out": None,
                      "source": "missing", "cost_usd": 0}
            turns: list[dict[str, Any]] = []
            verdict, productive, blocks = "ERRO", 0, 0
        else:
            tokens, turns = tel["tokens"], tel["turnos"]
            verdict, productive, blocks = result.verdict, result.productive_turns, result.block_turns
        error = self._unit_error(terminated, failure, result, net_errors, statuses)
        rel = unit_dir.relative_to(self.cell_dir).as_posix()
        record = self._record(
            unit, started_at, rec.now_iso(), terminated, tokens, turns,
            rec.mechanism_telemetry(tel, verdict, productive, blocks), oracle, evolution.as_dict(),
            {"bundle": f"{self.cell_id}.tar.gz",
             "paths": {"transcript": f"{rel}/transcript.jsonl", "diff": f"{rel}/diff.patch",
                       "manifest": f"{rel}/manifest.json", "oracle": f"{rel}/oracle.json",
                       "prompt": f"{rel}/prompt.txt"}},
            manifest_run=result.manifest if result else None, error=error)
        if regression is not None:
            record["artifacts"]["paths"]["regression"] = f"{rel}/regression.json"
            # The record keeps only the host tests that did not pass; regression.json has them all.
            block = rec.oracle_block(regression)
            block["per_test"] = [t for t in block.get("per_test", []) if t["outcome"] != "passed"]
            block["per_test_scope"] = "not_passed"
            record["host_regression"] = block
        return record, state

    def _finish_unit(self, unit: Unit, record: dict[str, Any], state: dict[str, Any]) -> None:
        self._append(record, unit)
        self._progress(unit, "done", state["turn"] or None,
                       (state["in"], state["out"]) if state["known"] and state["turn"] else None)
        oracle = record["oracle"]
        self.log(f"{unit.label}: {record['terminated_by']}, oracle {'PASS' if oracle['pass'] else 'FAIL'} "
                 f"({oracle['passed']} passed, {oracle['failed']} failed, {oracle['errors']} errors)")

    # --------------------------------------------------- infrastructure retries
    def _run_unit_with_retries(self, unit: Unit) -> dict[str, Any]:
        """``_run_unit``, and on a native cell a unit lost to infrastructure is run again.

        The lost attempt is undone before the next one: the arm's repository goes back
        to the commit before the unit (the attempt's commit is kept under a tag), the
        arm's intent store goes back to its bytes before the unit, and the attempt's
        artifacts move to ``<unit>.infra-<n>/``. Nothing of it is hidden: the final
        record lists every discarded attempt with its error and its tokens.
        """
        ws = self._workspace(unit)
        before = ws.head()
        snapshot = self._arm_snapshot(unit)
        retries: list[dict[str, Any]] = []
        while True:
            record, state = self._run_unit(unit)
            kind = (record.get("error") or {}).get("kind")
            retry = (kind in rec.INFRA_ERROR_KINDS and len(retries) < self.s.infra_retries
                     and not self.stop.is_set())
            if not retry:
                if retries:
                    record["infra_retries"] = retries
                self._finish_unit(unit, record, state)
                return record
            n = len(retries) + 1
            wait = min(self.s.infra_wait_s * 2 ** (n - 1), self.s.infra_max_wait_s)
            tag = f"infra/{safe_name(unit.label.replace('/', '-'))}/attempt-{n}"
            lost_commit = ws.discard_attempt(before, tag)
            parked = self._park_attempt(unit, n)
            self._restore_arm(unit, snapshot)
            retries.append({"attempt": n, "kind": kind, "detail": record["error"]["detail"],
                            "tokens": record["tokens"], "turns": len(record["turns"]),
                            "started_at": record["started_at"], "ended_at": record["ended_at"],
                            "commit": lost_commit, "tag": tag, "artifacts": parked, "waited_s": wait})
            self._error("infra_retry", f"{unit.label}: {kind}; attempt {n} discarded "
                                       f"({record['error']['detail'][:120]}); retrying in {wait:.0f}s")
            if self.stop.wait(wait):
                stopped = self._stopped_record(unit, "stopped")
                stopped["infra_retries"] = retries
                self._append(stopped, unit)
                return stopped

    def _arm_snapshot(self, unit: Unit) -> dict[str, bytes]:
        """The files directly in the arm's directory (the intent store) before a unit."""
        arm_dir = self._arm_dir(unit)
        if unit.arm_id == "Q" or not arm_dir.is_dir():
            return {}
        return {p.name: p.read_bytes() for p in arm_dir.iterdir() if p.is_file()}

    def _restore_arm(self, unit: Unit, snapshot: dict[str, bytes]) -> None:
        arm_dir = self._arm_dir(unit)
        if unit.arm_id == "Q" or not arm_dir.is_dir():
            return
        for path in arm_dir.iterdir():
            if path.is_file() and path.name not in snapshot:
                path.unlink()
        for name, data in snapshot.items():
            (arm_dir / name).write_bytes(data)

    def _park_attempt(self, unit: Unit, n: int) -> str:
        unit_dir = self._unit_dir(unit)
        target = unit_dir.with_name(f"{unit_dir.name}.infra-{n}")
        if unit_dir.exists():
            unit_dir.rename(target)
        return target.relative_to(self.cell_dir).as_posix()

    def _preflight_native(self, assign: dict[str, Any]) -> dict[str, Any]:
        spec = self.s.spec(assign["seed"], max(60.0, float(assign["deadline_s"])))
        preflight = environment.preflight_native(spec, timeout_s=max(60.0, float(assign["deadline_s"])))
        if not preflight["reachable"]:
            raise CellError("provider_unreachable", self._s(
                f"{self.s.provider_url} did not answer: {preflight['error']}"))
        status = preflight.get("status") or 0
        if status >= 400:
            kind = INFRA_STATUS.get(status, "provider_refused")
            hint = ""
            if (self.s.provider_api == api_mod.ANTHROPIC_MESSAGES and not self.s.anthropic_oauth_identity
                    and status in (400, 401, 403)):
                hint = (" (if the subscription only serves Claude Code, declare --anthropic-oauth-identity: "
                        "one identity sentence before the agent's prompt, same in every arm)")
            raise CellError(kind, f"the preflight request was refused (HTTP {status}): {preflight['error']}{hint}")
        if preflight["sampling_ok"] is False:
            raise CellError("sampling_not_on_wire", f"the request body did not carry the declared sampling "
                                                    f"policy {self.s.sampling!r}")
        if not preflight["usage_in_stream"]:
            self.log("warning: the provider reported no usage; tokens will be recorded as missing "
                     "(never estimated)")
        return preflight

    def _unit_error(self, terminated: str, failure: Exception | None, result: Any,
                    net_errors: list[dict[str, str]], statuses: list[int] | None = None) -> dict[str, str] | None:
        """``error`` of a unit that ended in ``error``: what broke, as infrastructure or not.

        A transport failure on the agent's own calls (refused, reset, timeout, closed
        mid-stream) is ``backend_unreachable``: the treatment never completed, and it was
        not retried. Anything else the provider said is ``provider_error``; an exception of
        this instrument is ``instrument_error``.
        """
        if terminated != "error":
            return None
        if net_errors:
            last = net_errors[-1]
            return {"kind": "backend_unreachable", "detail": self._s(f"{last['type']}: {last['detail']}")[:300]}
        if failure is not None:
            return {"kind": "instrument_error", "detail": self._s(f"{type(failure).__name__}: {failure}")[:300]}
        said = (result.telemetry.get("erro_de_provedor") if result else None) or "unknown"
        refused = [code for code in statuses or [] if code >= 400]
        if self.s.native and refused and refused[-1] in INFRA_STATUS:
            return {"kind": INFRA_STATUS[refused[-1]], "detail": self._s(f"HTTP {refused[-1]}: {said}")[:300]}
        if self.s.native:
            for pattern, kind in INFRA_TEXT:
                if pattern.search(str(said)):
                    return {"kind": kind, "detail": self._s(f"in-stream: {said}")[:300]}
        return {"kind": "provider_error", "detail": self._s(str(said))[:300]}

    # ----------------------------------------------------------------- record
    def _record(self, unit: Unit, started_at: str, ended_at: str, terminated: str, tokens: dict[str, Any],
                turns: list[dict[str, Any]], telemetry: dict[str, Any], oracle: dict[str, Any],
                evolution: dict[str, Any], artifacts: dict[str, Any], *,
                manifest_run: dict[str, Any] | None = None, flags: Any = None,
                error: dict[str, str] | None = None) -> dict[str, Any]:
        flags = flags or flags_from_args(["--arm", rec.FLAG_ARM_BY_ARM_ID[unit.arm_id]])
        hashes = (manifest_run or {}).get("config_sha256") or config_hashes()
        return {
            "schema_version": "gambiarra-coleta-2", "draft": True,
            "cell_id": self.cell_id, "participant_id": self.s.participant_id,
            "session_pin_hash": self.s.pin_hash,
            "arm_id": unit.arm_id, "harness_id": rec.HARNESS_BY_ARM[unit.arm_id],
            "task_set_sha": self.taskset.sha, "task_index": unit.index, "task_id": unit.task.id,
            "task_hash": unit.task.hash,
            "model": self.model_block, "hardware": self.s.join["hardware"], "backend": self.backend,
            "arm_order": list(self.assign["arms"]), "seed": self.assign["seed"],
            "mechanism": {
                "tau_intent_sha": self.s.join["tau_intent_sha"],
                "tau_ai_version": environment.tau_ai_version() or pin.PINNED_VERSION,
                "config_sha256": rec.config_sha256(hashes), "config_files": hashes,
                "system_prompt_sha256": system_prompt_sha256(),
                "runner_version": self.s.join["runner_version"],
                "flags": rec.flags_dict(flags)},
            "oracle": rec.oracle_block(oracle), "evolution": evolution, "tokens": tokens, "turns": turns,
            "mechanism_telemetry": telemetry, "terminated_by": terminated, "error": error,
            "started_at": started_at, "ended_at": ended_at, "artifacts": artifacts,
        }

    def _stopped_record(self, unit: Unit, why: str, error: dict[str, str] | None = None) -> dict[str, Any]:
        """A unit the runner never ran: complete in shape, zero in content, never guessed."""
        key = unit.arm_id if unit.arm_id != "Q" else f"Q{unit.attempt}"
        ws = self._workspaces.get(key)
        head = ws.head() if ws else None
        now = rec.now_iso()
        evolution = {"commit_before": head, "commit_after": head, "files_changed": 0, "insertions": 0,
                     "deletions": 0, "edit_size": 0, "untracked_created": []}
        tokens = {"in": 0, "out": 0, "rescue_in": 0, "rescue_out": 0, "source": "provider_usage", "cost_usd": 0}
        telemetry = {"verdict": None, "productive_turns": 0, "block_turns": 0, "bloco_vazio": None,
                     "tokens_served": 0, "nao_avaliaveis": [], "servidas": [], "not_run": True}
        if why == "error" and error is None:
            error = {"kind": "not_run", "detail": "the unit was not run"}
        return self._record(unit, now, now, why, tokens, [], telemetry, rec.zero_oracle(), evolution,
                            {"bundle": f"{self.cell_id}.tar.gz", "paths": {}}, error=error)

    def _append(self, record: dict[str, Any], unit: Unit) -> None:
        problems = rec.validate_record(record)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        if problems:
            # A record that contradicts the contract never reaches the dataset.
            with (self.cell_dir / "records.invalid.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"problems": problems, "record": record}, ensure_ascii=False) + "\n")
            self._error("record_invalid", f"{unit.label}: {'; '.join(problems)}"[:500])
        else:
            with (self.cell_dir / "records.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line)
            self.emit({"type": "bench_record", "cell_id": self.cell_id, "record": record})
        if not problems:
            self.records.append(record)
        self.unit_rows.append({"unit": unit.label, "terminated_by": record["terminated_by"],
                               "oracle_pass": record["oracle"]["pass"],
                               "commit_after": record["evolution"].get("commit_after"),
                               "valid": not problems})

    # --------------------------------------------------------------- finalize
    def _finalize(self, assign: dict[str, Any], started_at: str, ended_at: str, preflight: dict[str, Any],
                  truncated: bool, fatal: str | None, qualification_passed: bool | None
                  ) -> tuple[str | None, Path | None, str | None]:
        cell_dir = self.cell_dir
        (cell_dir / "records.jsonl").touch()
        for key, ws in self._workspaces.items():
            target = (cell_dir / "qualification" / f"attempt-{key[1:]}" if key.startswith("Q")
                      else cell_dir / "arms" / key) / "repo.bundle"
            ws.bundle(target)
        files = {p.relative_to(cell_dir).as_posix(): _sha256(p)
                 for p in sorted(cell_dir.rglob("*")) if p.is_file() and p.name != "cell.json"}
        cell = {
            "schema": "tau-intent-bench-cell/1", "draft": True,
            "bench_assign": assign, "bench_join": self.s.join,
            "task_set": {"id": self.taskset.id, "version": self.taskset.version, "sha": self.taskset.sha,
                         "task_hashes": {str(t.index): t.hash for t in self.taskset.tasks},
                         "qualification_hash": self.taskset.qualification.hash if self.taskset.qualification else None,
                         "k_available": len(self.taskset.tasks),
                         "k_run": min(assign["k_max"], len(self.taskset.tasks))},
            "provider_url": self._s(self.s.provider_url), "model": self.s.model,
            "model_block": self.model_block, "backend": self.backend,
            **({"strand": self.s.strand} if self.s.strand else {}),
            **({"protocol": self.s.spec(assign["seed"], float(assign["deadline_s"])).describe(),
                "infra_retry_policy": {"retries": self.s.infra_retries, "wait_s": self.s.infra_wait_s,
                                       "max_wait_s": self.s.infra_max_wait_s},
                "host_regression": self.taskset.regression is not None} if self.s.native else {}),
            "ollama": self.ollama,
            "preflight": preflight,
            "pin": {"dist": pin.PINNED_DIST, "version": pin.PINNED_VERSION, "sha256": pin.PINNED_SHA256},
            "started_at": started_at, "ended_at": ended_at, "units": self.unit_rows,
            "records": len(self.records), "truncated": truncated, "fatal": fatal,
            "qualification": None if qualification_passed is None else {"passed": qualification_passed},
            "files": files,
        }
        cell_path = cell_dir / "cell.json"
        cell_path.write_text(json.dumps(cell, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        manifest_sha = _sha256(cell_path)
        bundle = self.s.out_dir / f"{self.cell_id}.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for path in sorted(cell_dir.rglob("*")):
                if path.is_file():
                    tar.add(path, arcname=path.relative_to(cell_dir).as_posix())
        upload_detail: str | None = None
        if self.s.upload is not None:
            try:
                upload_detail = self.s.upload(bundle, self.cell_id, _sha256(bundle))
                self.log(f"bundle uploaded: {upload_detail}")
            except Exception as exc:  # noqa: BLE001 - the bundle stays on disk
                upload_detail = f"FAILED: {type(exc).__name__}: {exc}"
                self._error("upload_failed", f"{upload_detail}; the bundle is kept at {bundle}")
        self.log(f"bundle kept at {bundle}")
        (self.s.out_dir / f"{self.cell_id}.upload.json").write_text(
            json.dumps({"bundle": str(bundle), "sha256": _sha256(bundle), "upload": upload_detail}, indent=2),
            encoding="utf-8")
        return manifest_sha, bundle, upload_detail

    def _cleanup(self) -> None:
        if self.s.keep_workspaces:
            return
        import shutil
        for root in self._tmp_roots:
            shutil.rmtree(root, ignore_errors=True)
        try:
            (self.s.out_dir / ".workspaces").rmdir()  # only if empty
        except OSError:
            pass
