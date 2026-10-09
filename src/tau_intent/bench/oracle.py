"""The oracle of task k (contract §1), run outside the agent's workspace.

Hidden tests of tasks 1..k (regression included) are copied into a fresh
temporary directory **outside** the workspace, as ``tests/<NN>/`` (``tests/q/``
for Q0). The task set's ``test_runner`` runs there with cwd = that directory,
``PYTHONPATH=<workspace>`` and the single extra argument ``tests``; a leading
``python`` is replaced by the interpreter in use. Exit code 0 = pass. Per-test
results come from ``--junitxml``.

``OracleError`` means the oracle could not be run at all (pytest missing, bad
layout): that is a failure of the instrument, never a failed task.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from tau_intent.bench.taskset import TaskSet, TasksetError, list_files

DEFAULT_TIMEOUT_S = 300


class OracleError(Exception):
    """The oracle could not run (distinct from the oracle failing)."""


def oracle_dirs(taskset: TaskSet, k: int) -> list[tuple[str, Path]]:
    """``[(label, tests dir)]`` whose union is the oracle of task ``k`` (0 = Q0)."""
    if k == 0:
        if taskset.qualification is None:
            raise OracleError("this task set has no qualification task")
        return [("q", taskset.qualification.tests)]
    if taskset.oracle_scope == "own":
        return [(f"{k:02d}", taskset.task(k).tests)]
    return [(f"{t.index:02d}", t.tests) for t in taskset.tasks if t.index <= k]


def _copy_tests(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for relative, absolute in list_files(source):
        target = destination.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(absolute, target)


def _nodeid(tmp: Path, classname: str, name: str) -> str:
    if not classname and name:
        parts = name.split(".")
        for cut in range(len(parts), 0, -1):
            if tmp.joinpath(*parts[:cut]).with_suffix(".py").is_file():
                return "/".join(parts[:cut]) + ".py"
    parts = classname.split(".") if classname else []
    for cut in range(len(parts), 0, -1):
        if tmp.joinpath(*parts[:cut]).with_suffix(".py").is_file():
            return "/".join(parts[:cut]) + ".py::" + "::".join(parts[cut:] + [name])
    return "::".join(parts + [name])


def _parse_junit(path: Path, tmp: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    results = []
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome = "passed"
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                break
        results.append({"nodeid": _nodeid(tmp, case.get("classname", ""), case.get("name", "")),
                        "outcome": outcome})
    return results


def check_runner(taskset: TaskSet, python: str | None = None) -> None:
    """Fail early, with a clear message, when the oracle's interpreter cannot run it."""
    runner = list(taskset.test_runner)
    exe = python or sys.executable
    if runner and runner[0] == "python":
        runner[0] = exe
    probe = [runner[0], "-m", "pytest", "--version"] if "pytest" in runner else [runner[0], "--version"]
    try:
        proc = subprocess.run(probe, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OracleError(f"cannot start the test runner {runner[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise OracleError("the oracle needs pytest in this environment "
                          f"(pip install 'tau-intent[bench]'): {(proc.stderr or proc.stdout).strip()[:200]}")


def run_oracle(taskset: TaskSet, k: int, workspace: Path, *, python: str | None = None,
               timeout_s: int = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    workspace = Path(os.path.abspath(workspace))
    if not workspace.is_dir():
        raise OracleError(f"workspace is not a directory: {workspace}")
    try:
        pairs = oracle_dirs(taskset, k)
    except TasksetError as exc:
        raise OracleError(str(exc)) from exc
    return _run_tests(taskset, pairs, workspace, python=python, timeout_s=timeout_s)


def run_snapshot(taskset: TaskSet, k: int, workspace: Path, *, python: str | None = None,
                 timeout_s: int = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Task k's own tests, mid-session (Q6: turns to green). The agent never sees them.

    ``TAU_INTENT_ORACLE_MODE=snapshot`` lets the task set's conftest narrow the run
    (for SWE-Milestone: only the milestone's own fail-to-pass tests).
    """
    workspace = Path(os.path.abspath(workspace))
    return _run_tests(taskset, [(f"{k:02d}", taskset.task(k).tests)], workspace, python=python,
                      timeout_s=timeout_s, mode="snapshot")


def run_regression(taskset: TaskSet, workspace: Path, *, python: str | None = None,
                   timeout_s: int = DEFAULT_TIMEOUT_S) -> dict[str, Any] | None:
    """The host repository's frozen suite against the workspace, or ``None`` if the
    task set declares none. Same isolation as the oracle (copied out, never the
    agent's own copy of the tests); descriptive, never part of ``oracle.pass``."""
    if taskset.regression is None:
        return None
    workspace = Path(os.path.abspath(workspace))
    if not workspace.is_dir():
        raise OracleError(f"workspace is not a directory: {workspace}")
    return _run_tests(taskset, [("host", taskset.regression)], workspace, python=python, timeout_s=timeout_s)


def run_build_check(taskset: TaskSet, workspace: Path, *, python: str | None = None,
                    home: Path | None = None) -> dict[str, Any] | None:
    """The task set's build check in the agent's tree; ``None`` when it declares none.

    It runs as the agent's shell would (the arm's interpreter directory first on PATH,
    cwd = the working tree), so a broken build here is the one the agent would see. It
    may rebuild into the tree's ignored build directory, exactly as the agent's own
    ``import`` does; it never edits a tracked file.
    """
    spec = taskset.environment or {}
    script = spec.get("build_check")
    if not script:
        return None
    env = dict(os.environ)
    if python is not None:
        env_bin = os.path.dirname(os.path.abspath(python))
        env["PATH"] = env_bin + os.pathsep + env.get("PATH", os.defpath)
        env["VIRTUAL_ENV"] = os.path.dirname(env_bin)
    if home is not None:
        env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TASKSET_ROOT"] = str(taskset.root)
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(["bash", str(taskset.root / script)], cwd=workspace, env=env,
                              capture_output=True, text=True,
                              timeout=spec.get("build_check_timeout_s", 900))
        code, output = proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        timed_out, code, output = True, -1, ""
    return {"ok": code == 0 and not timed_out, "exit_code": code, "timed_out": timed_out,
            "duration_s": round(time.monotonic() - started, 3),
            "output_tail": "\n".join(output.splitlines()[-30:])}


def _run_tests(taskset: TaskSet, pairs: list[tuple[str, Path]], workspace: Path, *,
               python: str | None, timeout_s: int, mode: str = "oracle") -> dict[str, Any]:
    runner = list(taskset.test_runner)
    if runner and runner[0] == "python":
        runner[0] = python or sys.executable
    tmp = Path(tempfile.mkdtemp(prefix="oracle-"))
    try:
        if os.path.commonpath([str(tmp), str(workspace)]) == str(workspace):
            raise OracleError("temporary oracle directory ended up inside the workspace")
        for label, source in pairs:
            _copy_tests(source, tmp / "tests" / label)
        junit = tmp / "junit.xml"
        env = dict(os.environ)
        if python is not None:
            # The arm's own interpreter (task set ``environment``): its directory goes first on
            # PATH, as in the agent's shell. An editable build that rebuilds on import calls
            # tools such as ``cython`` by name; without this the first import after a Cython
            # edit failed with exit 127 (pilot of 2026-10-09).
            env_bin = os.path.dirname(os.path.abspath(python))
            env["PATH"] = env_bin + os.pathsep + env.get("PATH", os.defpath)
            env["VIRTUAL_ENV"] = os.path.dirname(env_bin)
        env["PYTHONPATH"] = str(workspace)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["TAU_INTENT_ORACLE_MODE"] = mode
        # Concurrent runners: pytest's tmp_path base and any scratch file stay in this run's own dir.
        (tmp / "scratch").mkdir()
        env["TMPDIR"] = str(tmp / "scratch")
        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(runner + ["--junitxml=" + str(junit), "tests"], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=timeout_s)
            code, output = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            timed_out, code, output = True, -1, ""
        except FileNotFoundError as exc:
            raise OracleError(f"cannot start the test runner: {exc}") from exc
        duration = time.monotonic() - started
        if "No module named pytest" in output:
            raise OracleError(f"pytest is not installed for {runner[0]}")
        per_test = _parse_junit(junit, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    def count(outcome: str) -> int:
        return sum(1 for t in per_test if t["outcome"] == outcome)

    return {
        "pass": code == 0 and not timed_out,
        "exit_code": code,
        "timed_out": timed_out,
        "passed": count("passed"),
        "failed": count("failed"),
        "errors": count("error"),
        "duration_s": round(duration, 3),
        "per_test": per_test,
        "output_tail": "\n".join(output.splitlines()[-25:]),
    }
