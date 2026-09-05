"""Code witness. Resolver/diff/blob routines moved unchanged after Wave 1."""
from __future__ import annotations
import ast
import re
import hashlib
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

    def effects(self, workspace, supplied=None):
        return resolver_simbolos(regions_from_diff(
            supplied if supplied is not None else git_diff(workspace)), workspace)

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
