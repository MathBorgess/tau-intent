"""One git repository per arm: the evolution data of the mini repo (contract §5).

Each arm workspace is initialised from the task set's ``seed/`` (commit ``seed``)
and gets **one commit per task** after the agent finishes, untracked files
included, whether or not the oracle passed. That commit series is the dataset.

Isolation from the participant's machine: a private ``HOME``, no system or global
git config (a signing hook or a template must not change the data), a fixed
author. ``.git/info/exclude`` keeps bytecode and the mechanism's own files out of
the commits without adding a tracked ``.gitignore`` the agent would see as an
effect of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tau_intent.bench.taskset import IGNORED_DIRS, IGNORED_SUFFIXES

AUTHOR = ("tau-intent-bench", "bench@tau-intent.invalid")
EXCLUDES = ("__pycache__/", "*.pyc", "*.pyo", ".pytest_cache/", "intents.jsonl")


class GitError(RuntimeError):
    pass


def _env(home: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
           if key in os.environ}
    env.update({
        "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
        "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1],
        "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
    })
    return env


def git(cwd: Path, home: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-c", "core.quotepath=off", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=_env(home), capture_output=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): "
                       f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return proc.stdout.decode("utf-8", "replace")


@dataclass
class Evolution:
    commit_before: str
    commit_after: str
    files_changed: int
    insertions: int
    deletions: int
    untracked_created: list[str]

    @property
    def edit_size(self) -> int:
        return self.insertions + self.deletions

    def as_dict(self) -> dict:
        return {"commit_before": self.commit_before, "commit_after": self.commit_after,
                "files_changed": self.files_changed, "insertions": self.insertions,
                "deletions": self.deletions, "edit_size": self.edit_size,
                "untracked_created": self.untracked_created}


class ArmWorkspace:
    """``root/workspace`` is the agent's cwd; ``root/home`` is its private HOME."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "workspace"
        self.home = self.root / "home"

    # ------------------------------------------------------------------ setup
    def create(self, seed: Path) -> str:
        self.home.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seed, self.path, ignore=shutil.ignore_patterns(
            *IGNORED_DIRS, *[f"*{s}" for s in IGNORED_SUFFIXES], ".git"))
        self._git("init", "-q", "-b", "main")
        exclude = self.path / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(EXCLUDES) + "\n", encoding="utf-8")
        return self.commit("seed")

    def _git(self, *args: str, check: bool = True) -> str:
        return git(self.path, self.home, *args, check=check)

    # ---------------------------------------------------------------- history
    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def commit(self, message: str) -> str:
        """Commit everything (untracked included); empty commits keep the series 1:1."""
        self._git("add", "-A")
        self._git("commit", "-q", "--allow-empty", "--no-verify", "-m", message)
        return self.head()

    def evolution(self, before: str, after: str) -> Evolution:
        files = insertions = deletions = 0
        numstat = self._git("diff", "--numstat", "--no-renames", before, after)
        for line in numstat.splitlines():
            added, removed, _ = (line.split("\t", 2) + ["", ""])[:3]
            files += 1
            insertions += int(added) if added.isdigit() else 0
            deletions += int(removed) if removed.isdigit() else 0
        created = [p for p in self._git("diff", "--name-only", "--diff-filter=A", "--no-renames",
                                        before, after).splitlines() if p]
        return Evolution(before, after, files, insertions, deletions, sorted(created))

    def patch(self, before: str, after: str) -> str:
        return self._git("diff", "--binary", "--no-color", "--no-ext-diff", "--no-renames", before, after)

    def bundle(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._git("bundle", "create", str(destination), "--all")

    def log(self) -> list[str]:
        return self._git("log", "--reverse", "--format=%s").splitlines()

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def safe_name(value: str) -> str:
    return _SAFE.sub("_", value)[:80] or "x"
