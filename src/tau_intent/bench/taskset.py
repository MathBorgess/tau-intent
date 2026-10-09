"""Reader of a ``tg-taskset-1`` directory (contract §1), read-only.

The runner **recomputes** ``task_hash(k)`` and ``task_set_sha`` and never trusts a
stored value. The encoding is the contract's, made exact by the task-set repo and
re-implemented here on purpose (no cross-repo dependency)::

    entry(path, data) = utf8(path) || 0x00 || data                 (no length framing)
    task_hash(k)  = sha256(statement bytes || entry(p, bytes) for p under tests, sorted)
    task_set_sha  = sha256(entry(p, bytes) for every file p under taskset/, sorted)

``p`` is POSIX, relative to the tests directory (task hash) or to ``taskset/``
(set sha), sorted as a string. ``__pycache__/``, ``.pytest_cache/`` and
``*.pyc``/``*.pyo`` are never hashed or copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tau_intent.bench import TASKSET_SCHEMA

IGNORED_DIRS = ("__pycache__", ".pytest_cache")
IGNORED_SUFFIXES = (".pyc", ".pyo")
QUALIFICATION_ID = "Q0"


class TasksetError(Exception):
    """The directory is not a usable ``tg-taskset-1``."""


@dataclass(frozen=True)
class Task:
    index: int
    id: str
    statement: Path
    tests: Path
    depends_on: tuple[int, ...]
    hash: str

    def statement_text(self) -> str:
        return self.statement.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Qualification:
    id: str
    seed: Path
    statement: Path
    tests: Path
    hash: str

    def statement_text(self) -> str:
        return self.statement.read_text(encoding="utf-8")


@dataclass(frozen=True)
class TaskSet:
    root: Path
    id: str
    version: str
    language: str
    python: str
    seed: Path
    test_runner: tuple[str, ...]
    tasks: tuple[Task, ...]
    qualification: Qualification | None
    sha: str
    extra: dict = field(default_factory=dict)
    #: Optional frozen copy of the host repository's own suite (``"regression"`` in
    #: taskset.json): run after every unit as a *descriptive* layer, never part of the
    #: task's oracle, so a task set that only grows the repository around the same chain
    #: keeps the same ``task_hash`` per task.
    regression: Path | None = None
    #: Optional per-arm environment (``"environment"`` in taskset.json): ``setup`` (argv, run
    #: once per arm workspace with ENV_DIR, WORKSPACE, TASKSET_ROOT, BENCH_PYTHON), ``bin``
    #: (relative to ENV_DIR; first on the agent's PATH and the oracle's interpreter) and
    #: ``timeout_s``. A task set whose host needs compiled extensions builds them here.
    #: Optional ``build_check``: a script (relative to the task set) the bench runs with
    #: ``bash`` in the agent's tree before each session, after each editing turn and at the
    #: end; exit 0 means the package builds. Its output tail is what the agent is shown when
    #: a session starts on a broken build (``build_check_timeout_s``, default 900).
    environment: dict | None = None
    #: ``cumulative`` (default): the oracle of task k runs the tests of tasks 1..k.
    #: ``own``: it runs task k's directory only; the builder made it cumulative.
    oracle_scope: str = "cumulative"

    def task(self, index: int) -> Task:
        for task in self.tasks:
            if task.index == index:
                return task
        raise TasksetError(f"no task with index {index}")


def list_files(root: Path) -> list[tuple[str, Path]]:
    """Every file under ``root`` as (relative POSIX path, absolute path), sorted."""
    found: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            if name.endswith(IGNORED_SUFFIXES):
                continue
            absolute = Path(dirpath) / name
            found.append((absolute.relative_to(root).as_posix(), absolute))
    found.sort(key=lambda item: item[0])
    return found


def _feed(digest: "hashlib._Hash", path: str, absolute: Path) -> None:
    digest.update(path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(absolute.read_bytes())


def hash_task(statement: Path, tests: Path) -> str:
    digest = hashlib.sha256()
    digest.update(statement.read_bytes())
    for relative, absolute in list_files(tests):
        _feed(digest, relative, absolute)
    return digest.hexdigest()


def hash_taskset(root: Path) -> str:
    digest = hashlib.sha256()
    for relative, absolute in list_files(root):
        _feed(digest, relative, absolute)
    return digest.hexdigest()


def _need(manifest: dict, key: str):
    if key not in manifest:
        raise TasksetError(f"taskset.json has no {key!r}")
    return manifest[key]


def _file(root: Path, relative: str, what: str) -> Path:
    path = (root / relative)
    if not path.is_file():
        raise TasksetError(f"{what} not found: {relative}")
    return path


def _dir(root: Path, relative: str, what: str) -> Path:
    path = (root / relative)
    if not path.is_dir():
        raise TasksetError(f"{what} not found: {relative}")
    return path


def _python_ok(spec: str) -> bool:
    spec = spec.strip()
    if not spec.startswith(">="):
        return True
    try:
        wanted = tuple(int(part) for part in spec[2:].strip().split("."))
    except ValueError:
        return True
    return sys.version_info[: len(wanted)] >= wanted


def load_taskset(path: str | Path) -> TaskSet:
    root = Path(path)
    manifest_path = root / "taskset.json"
    if not manifest_path.is_file():
        raise TasksetError(f"no taskset.json in {root}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise TasksetError(f"taskset.json is not valid JSON: {exc}") from exc
    if manifest.get("schema") != TASKSET_SCHEMA:
        raise TasksetError(f"schema is {manifest.get('schema')!r}, expected {TASKSET_SCHEMA!r}")
    if manifest.get("language") != "python":
        raise TasksetError(f"language {manifest.get('language')!r} is not supported (python only)")
    python = str(manifest.get("python", ""))
    if not _python_ok(python):
        raise TasksetError(f"task set needs python {python}, running {sys.version.split()[0]}")
    runner = _need(manifest, "test_runner")
    if not isinstance(runner, list) or not runner or not all(isinstance(a, str) for a in runner):
        raise TasksetError("test_runner must be a non-empty argv list")

    tasks: list[Task] = []
    for entry in _need(manifest, "tasks"):
        index = entry.get("index")
        statement = _file(root, entry.get("statement", ""), f"statement of task {index}")
        tests = _dir(root, entry.get("tests", ""), f"tests of task {index}")
        tasks.append(Task(
            index=index, id=str(entry.get("id", f"task-{index}")), statement=statement, tests=tests,
            depends_on=tuple(entry.get("depends_on", ())), hash=hash_task(statement, tests)))
    tasks.sort(key=lambda t: t.index)
    if [t.index for t in tasks] != list(range(1, len(tasks) + 1)) or not tasks:
        raise TasksetError("task indices must be contiguous 1..K")

    qualification = None
    q = manifest.get("qualification")
    if q:
        q_statement = _file(root, q.get("statement", ""), "qualification statement")
        q_tests = _dir(root, q.get("tests", ""), "qualification tests")
        qualification = Qualification(
            id=QUALIFICATION_ID, seed=_dir(root, q.get("seed", ""), "qualification seed"),
            statement=q_statement, tests=q_tests, hash=hash_task(q_statement, q_tests))
    regression = None
    r = manifest.get("regression")
    if r:
        if not isinstance(r, dict) or not isinstance(r.get("tests"), str):
            raise TasksetError('regression must be {"tests": "<dir>"}')
        regression = _dir(root, r["tests"], "regression tests")
    scope = manifest.get("oracle_scope", "cumulative")
    if scope not in ("cumulative", "own"):
        raise TasksetError(f"oracle_scope must be cumulative or own (got {scope!r})")
    environment = manifest.get("environment")
    if environment is not None:
        setup = environment.get("setup") if isinstance(environment, dict) else None
        if not isinstance(setup, list) or not setup or not all(isinstance(a, str) for a in setup) \
                or not isinstance(environment.get("bin"), str):
            raise TasksetError('environment must be {"setup": [argv...], "bin": "<dir>", "timeout_s": <int>}')
        check = environment.get("build_check")
        if check is not None and (not isinstance(check, str) or not (root / check).is_file()):
            raise TasksetError(f"environment.build_check must be a script in the task set (got {check!r})")
        environment = {"setup": list(setup), "bin": environment["bin"],
                       "timeout_s": int(environment.get("timeout_s", 1800)),
                       **({"build_check": check,
                           "build_check_timeout_s": int(environment.get("build_check_timeout_s", 900))}
                          if check else {})}
    return TaskSet(
        root=root, id=str(_need(manifest, "id")), version=str(manifest.get("version", "")),
        language="python", python=python, seed=_dir(root, _need(manifest, "seed"), "seed"),
        test_runner=tuple(runner), tasks=tuple(tasks), qualification=qualification,
        sha=hash_taskset(root), regression=regression, environment=environment, oracle_scope=scope)
