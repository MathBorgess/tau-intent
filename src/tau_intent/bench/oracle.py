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
    runner = list(taskset.test_runner)
    if runner and runner[0] == "python":
        runner[0] = python or sys.executable
    try:
        pairs = oracle_dirs(taskset, k)
    except TasksetError as exc:
        raise OracleError(str(exc)) from exc

    tmp = Path(tempfile.mkdtemp(prefix="oracle-"))
    try:
        if os.path.commonpath([str(tmp), str(workspace)]) == str(workspace):
            raise OracleError("temporary oracle directory ended up inside the workspace")
        for label, source in pairs:
            _copy_tests(source, tmp / "tests" / label)
        junit = tmp / "junit.xml"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
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
