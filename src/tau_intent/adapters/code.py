"""Code witness. Resolver/diff/blob routines moved unchanged after Wave 1."""
from __future__ import annotations
import ast
import os
import re
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from tau_intent.collect import Region, collect_events
from tau_intent.model import Anchor

_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_GIT = re.compile(r"^diff --git a/.+ b/(.+)$")
_PLUS_PLUS = re.compile(r"^\+\+\+ (?:b/)?(.+)$")

def regions_from_diff(diff: str | Iterable[Region]) -> list[Region]:
    """Parse a unified git diff, or pass through an already-built region list.

    Records both the hunk length (``size``) and the number of added/changed
    lines (``edited_lines``). The second is what ``limiar_edicao`` was always
    supposed to mean (D7): a 44-line hunk with 3 lines of context each side is
    a 38-line edit, and only the exact count says so.
    """
    if not isinstance(diff, str):
        return list(diff)
    regions: list[Region] = []
    path = ""
    current: Region | None = None
    for line in diff.splitlines():
        git = _DIFF_GIT.match(line)
        if git:
            path = git.group(1)
            current = None
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            plus = _PLUS_PLUS.match(line)
            if plus and plus.group(1) != "/dev/null":
                path = plus.group(1)
            current = None
            continue
        hunk = _HUNK.match(line)
        if hunk and path:
            start = int(hunk.group(1))
            count = int(hunk.group(2) or "1")
            end = start + max(count, 1) - 1
            current = Region(
                path=path, line_start=start, line_end=end, size=count, edited_lines=0
            )
            regions.append(current)
            continue
        if current is not None and line[:1] in {"+", "-"}:
            current.edited_lines = (current.edited_lines or 0) + 1
    return regions


def resolver_simbolo(source: str, line_start: int, line_end: int) -> str | None:
    """Innermost def/class of ``source`` that contains the whole line range.

    Read-only use of the AST, same parser ``graph.py`` builds its nodes with.
    No user code is executed and no file is written.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if node.lineno <= line_start and line_end <= end:
            span = end - node.lineno
            if best is None or span < best[0]:
                best = (span, node.name)
    return best[1] if best else None


def resolver_simbolos(regions: Iterable[Region], workspace: Path | str | None) -> list[Region]:
    """Fill ``Region.symbol`` from the post-edit tree. Idempotent, in place."""
    if workspace is None:
        return list(regions)
    root = Path(workspace)
    cache: dict[str, str | None] = {}
    out = []
    for region in regions:
        if region.path not in cache:
            candidate = root / region.path
            try:
                cache[region.path] = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                cache[region.path] = None
        source = cache[region.path]
        region.resolver = None
        if source is not None and Path(region.path).suffix == ".py":
            try:
                ast.parse(source)
            except (SyntaxError, ValueError):
                pass
            else:
                region.resolver = "stdlib-identities-v1"
        if region.resolver is not None:
            region.symbol = resolver_simbolo(source, region.line_start, region.line_end)
        out.append(region)
    return out


def simbolos_do_ast(regions: Iterable[Region], workspace: Path | str | None) -> set[str]:
    """The symbol table the gate validates ``record_intent.symbol`` against.

    Node ids in ``file::symbol`` shape, for every def/class of every file the
    diff touched. This is what replaces the supervisor's old
    ``_symbols_from_pending``, which built the known set by scraping the very
    property texts it was supposed to check (D2).
    """
    if workspace is None:
        return set()
    root = Path(workspace)
    nomes: set[str] = set()
    for path in {region.path for region in regions}:
        try:
            source = (root / path).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nomes.add(f"{path}::{node.name}")
    return nomes


def git_diff(workspace: Path) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "diff", "--no-color", "HEAD"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


class EffectObservationError(RuntimeError):
    """git could not tell us what changed.

    This is **not** an empty effect set. Returning ``[]`` on a failed ``git``
    call made a broken witness indistinguishable from an agent that changed
    nothing, and ``AUSENTE`` (an effect with no intent) could then never fire.
    """


#: Bytes read to decide whether an untracked file is text (git's own window).
_BINARY_WINDOW = 8192
#: An untracked file above this size is declared opaque instead of being read.
OPAQUE_ABOVE_BYTES = 2 * 1024 * 1024

_GIT_FLAGS = ("-c", "core.quotepath=off", "-c", "diff.noprefix=false",
              "-c", "diff.mnemonicPrefix=false", "-c", "color.ui=false")


@dataclass
class Observation:
    """What one look at the working tree saw."""

    regions: list[Region] = field(default_factory=list)
    #: Paths the agent created and git does not track yet (text or opaque).
    untracked: list[str] = field(default_factory=list)
    #: Effects whose content is not line-addressable, with the reason. They are
    #: still effects (a coarse Region, no identity) so ``AUSENTE`` can fire and
    #: the agent can satisfy it with a record_intent that names the path.
    opaque: dict[str, str] = field(default_factory=dict)


def _git(workspace: Path, *args: str) -> bytes:
    env = {**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        proc = subprocess.run(["git", *_GIT_FLAGS, *args], cwd=workspace, check=False,
                              capture_output=True, env=env)
    except OSError as exc:
        raise EffectObservationError(f"git could not be run: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise EffectObservationError(
            f"git {' '.join(args)} failed in {workspace} (exit {proc.returncode}): {detail}")
    return proc.stdout


def _opaque_region(path: str) -> Region:
    return Region(path, 0, 0, size=1, edited_lines=0, resolver=None)


#: Files the mechanism itself writes into the workspace. They are not the
#: agent's effects: the supervisor appends to the intent log, and counting that
#: write as an effect would make every captured intent demand another intent.
MECHANISM_FILES = ("intents.jsonl",)


def observe(workspace: Path, base: str = "HEAD",
            ignore: Iterable[str] = MECHANISM_FILES) -> Observation:
    """Tracked changes against ``base`` **plus** files git does not track yet.

    ``base`` defaults to HEAD; the bench passes the commit its task started
    from, so an agent that runs ``git commit`` itself cannot hide its work.
    Raises ``EffectObservationError`` when git fails. ``ignore`` names workspace
    paths the mechanism writes itself (the intent log); they are never effects.
    """
    workspace = Path(workspace)
    skip = set(ignore)
    diff = _git(workspace, "diff", "--no-color", "--no-ext-diff", "--no-renames",
                "--src-prefix=a/", "--dst-prefix=b/", base).decode("utf-8", "replace")
    obs = Observation(regions=[r for r in regions_from_diff(diff) if r.path not in skip])
    # numstat reports "-\t-\tpath" for content git treats as binary: the diff
    # above has no hunk for it, so without this the effect would vanish.
    numstat = _git(workspace, "diff", "--numstat", "-z", "--no-renames", base)
    for entry in numstat.split(b"\0"):
        parts = entry.split(b"\t", 2)
        if len(parts) == 3 and parts[0] == b"-" and parts[1] == b"-":
            path = parts[2].decode("utf-8", "replace")
            if path in skip:
                continue
            obs.opaque[path] = "binary"
            obs.regions.append(_opaque_region(path))
    listed = _git(workspace, "ls-files", "--others", "--exclude-standard", "-z")
    for raw in sorted(item for item in listed.split(b"\0") if item):
        path = raw.decode("utf-8", "replace")
        if path in skip:
            continue
        obs.untracked.append(path)
        region = _untracked_region(workspace, path, obs.opaque)
        obs.regions.append(region)
    return obs


def _untracked_region(workspace: Path, path: str, opaque: dict[str, str]) -> Region:
    full = workspace / path
    try:
        info = full.lstat()
    except OSError:
        opaque[path] = "unreadable"
        return _opaque_region(path)
    if not full.is_file() or full.is_symlink():
        opaque[path] = "symlink" if full.is_symlink() else "not-a-regular-file"
        return _opaque_region(path)
    if info.st_size > OPAQUE_ABOVE_BYTES:
        opaque[path] = "too-large"
        return _opaque_region(path)
    try:
        data = full.read_bytes()
    except OSError:
        opaque[path] = "unreadable"
        return _opaque_region(path)
    if b"\0" in data[:_BINARY_WINDOW]:
        opaque[path] = "binary"
        return _opaque_region(path)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        opaque[path] = "binary"
        return _opaque_region(path)
    # A new file is one added hunk: the same shape `git diff` gives a file that
    # was intent-to-add, without touching the index to get it.
    n = len(lines)
    return Region(path, 1, max(n, 1), size=max(n, 1), edited_lines=n)


def _blob_sha(path: Path) -> str:
    """git's blob object id of the file as it is on disk. No placeholder.

    While it was ``"0" * 40`` no anchor was verifiable against the tree.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "0" * 40
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - git's own format


class CodeAdapter:
    name = "code"
    version = "code-v1"
    size_unit = "edited_lines"
    edge_types = ("contains", "imports", "invokes", "inherits")

    def __init__(self, base: str = "HEAD", ignore: Iterable[str] = MECHANISM_FILES):
        #: Revision the effects are measured against (the task's starting commit).
        self.base = base
        self.ignore = tuple(ignore)
        #: The last tree observation, for telemetry (untracked / opaque effects).
        self.last_observation: Observation | None = None

    def effects(self, workspace, supplied=None):
        if supplied is not None:
            return resolver_simbolos(regions_from_diff(supplied), workspace)
        self.last_observation = observe(Path(workspace), self.base, self.ignore)
        return resolver_simbolos(list(self.last_observation.regions), workspace)

    def collect(self, events, effects, workspace):
        return collect_events(events, effects, workspace)

    def identities(self, effects, workspace):
        return simbolos_do_ast(effects, workspace)

    def anchor(self, pending, workspace):
        r = pending.region
        return Anchor(file=r.path, symbol=r.symbol or None,
                      line_start=r.line_start, line_end=r.line_end,
                      blob_sha=_blob_sha(workspace / r.path))

    def neighbourhood(self, workspace):
        from tau_intent.adapters.code_graph import build_cached
        return build_cached(str(workspace), "worktree")

    def oracle(self, check):
        result = check()
        if type(result) is not bool:
            raise TypeError("oracle must return bool")
        return result

    def classification(self, effect):
        return Path(effect.path).suffix.lstrip(".") or "sem-extensao"


    def anchor_resolves(self, anchor, workspace):
        target = workspace / anchor.file
        if not target.is_file() or _blob_sha(target) != anchor.blob_sha:
            return False
        if anchor.symbol is None:
            return True
        return anchor.node_id() in simbolos_do_ast(
            [Region(anchor.file, anchor.line_start, anchor.line_end)], workspace)

    def validate(self, command, workspace):
        """Run an explicitly supplied local argv; record the actual exit and output."""
        import json
        import subprocess
        from tau_intent.checkpoint import ValidationEvidence
        if not isinstance(command, (list, tuple)) or not command or not all(type(s) is str for s in command):
            raise ValueError("validation command must be a non-empty argv")
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=False)
        return ValidationEvidence(json.dumps(list(command)), json.dumps({
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
