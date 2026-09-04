"""Collector: regions from git diff; tool events attach why/property/symbol.

The collector is where the evidence the gate needs is produced (G-2, G-3).
Three things it used to compute and throw away are now exposed:
``Pending.unparseable`` (V6, feeds NAO_PARSEAVEL), ``Pending.claimed_regions``
(how many distinct diff regions this call covered) and ``Pending.domain``
(feeds DOMINIO_AUSENTE). Two things it never computed are now produced:
``Region.edited_lines`` — added/changed lines, not hunk length (D7) — and
``Region.symbol``, the enclosing definition resolved from the AST, which is
the stable store identity of G-3: reformatting a file moves lines but not
the symbol.

One ``record_intent`` why may span several AST symbols in the same file
(first construction split into helpers). A declared ``symbol`` scopes the
call to hunks of that def — that is the accidental-claim guard. An empty
declared symbol claims every hunk of the listed files. The label that
distinguishes fix from refactor lives in ``why``; the collector does not
parse it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

WRITE_TOOLS = frozenset({"write", "edit"})
INTENT_TOOL = "record_intent"
BASH_TOOL = "bash"

_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_GIT = re.compile(r"^diff --git a/.+ b/(.+)$")
_PLUS_PLUS = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_REDIRECT = re.compile(r"(?:>>?|tee(?:\s+-a)?)\s+([^\s|;]+)")


@dataclass
class Region:
    path: str
    line_start: int
    line_end: int
    size: int = 0
    #: Added/changed lines in the hunk. ``None`` when unknown (never guessed
    #: here — the gate estimates from ``size`` and ``contexto_diff`` instead).
    edited_lines: int | None = None
    #: Enclosing def/class resolved from the AST of the post-edit tree. This is
    #: evidence, not identity: the line range is what git gives, the symbol is
    #: what survives a reformat.
    symbol: str | None = None

    def __post_init__(self) -> None:
        if not self.size:
            self.size = max(self.line_end - self.line_start + 1, 0)

    def key(self) -> tuple[str, int, int]:
        return (self.path, self.line_start, self.line_end)

    def node_id(self) -> str:
        return f"{self.path}::{self.symbol}" if self.symbol else self.path


@dataclass
class Pending:
    region: Region
    why: str = ""
    property: str = ""
    domain: str = ""
    #: The symbol the agent *declared* in record_intent. The gate validates it
    #: against the AST table; it is never auto-filled here, or SIMBOLO_NAO_
    #: RESOLVIDO would be unfalsifiable in exactly the way D2 describes.
    symbol: str = ""
    unparseable: bool = False
    raw_arguments: Any = None
    bytes: int = 0
    #: How many distinct diff regions this same record_intent covers.
    claimed_regions: int = 1
    trigger_log: list[str] = field(default_factory=list)
    #: Ordinal of the tool event that first wrote this region, and of the
    #: record_intent that annotated it. Feeds latencia_de_captura (G-4).
    write_turn: int | None = None
    intent_turn: int | None = None


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
        if source is not None:
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


def collect_events(
    events: Iterable[Any],
    regions: Iterable[Region],
    workspace: Path | str | None = None,
) -> dict[tuple[str, int, int], Pending]:
    """Attach why/property/symbol/domain from tool events onto git-diff regions.

    Unparseable (V6): ``_raw_arguments`` present, or local schema refused
    (missing ``path``, ``file_path`` used instead, edit without ``edits``).

    When ``workspace`` is given, ``Region.symbol`` is resolved from the AST of
    the post-edit tree (G-3) **before** intents attach, so a declared symbol
    can scope the call. The *declared* ``Pending.symbol`` is never filled
    from the AST — the gate has to be able to fail.
    """
    regions = list(regions)
    if workspace is not None:
        resolver_simbolos(regions, workspace)
    by_path = _index_regions(regions)
    pendentes: dict[tuple[str, int, int], Pending] = {}

    for ordinal, event in enumerate(events):
        name = _tool_name(event)
        args, raw, unparseable = _tool_args(event)
        if name in WRITE_TOOLS or name == INTENT_TOOL or name == BASH_TOOL:
            paths = _paths_from_args(name, args)
            if unparseable or not paths:
                unparseable = True
            matched: list[Region] = []
            seen: set[tuple[str, int, int]] = set()
            for path in paths:
                for region in _match_regions(by_path, path):
                    key = region.key()
                    if key not in seen:
                        seen.add(key)
                        matched.append(region)
            if not matched and paths:
                for path in paths:
                    region = Region(path=path, line_start=0, line_end=0)
                    matched.append(region)
                    by_path.setdefault(path, []).append(region)
            elif not matched and not paths:
                matched = [region for group in by_path.values() for region in group]
            if name == INTENT_TOOL:
                matched = _restringir_ao_simbolo(
                    matched, str(args.get("symbol") or "")
                )
            for region in matched:
                pending = pendentes.setdefault(region.key(), Pending(region=region))
                pending.trigger_log.append(name)
                if unparseable:
                    pending.unparseable = True
                    pending.raw_arguments = raw
                if name == INTENT_TOOL:
                    pending.why = str(args.get("why") or pending.why)
                    pending.property = str(args.get("property") or pending.property)
                    pending.domain = str(args.get("domain") or pending.domain)
                    pending.symbol = str(args.get("symbol") or pending.symbol)
                    pending.claimed_regions = max(len(matched), 1)
                    if pending.intent_turn is None:
                        pending.intent_turn = ordinal
                if name in WRITE_TOOLS | {BASH_TOOL} and pending.write_turn is None:
                    pending.write_turn = ordinal
                if name in WRITE_TOOLS:
                    pending.bytes += len(str(args.get("content") or ""))
                    _apply_edit_size(pending, args)

    resolver_simbolos([p.region for p in pendentes.values()], workspace)
    return pendentes


def _index_regions(regions: Iterable[Region]) -> dict[str, list[Region]]:
    indexed: dict[str, list[Region]] = {}
    for region in regions:
        indexed.setdefault(region.path, []).append(region)
    return indexed


def _restringir_ao_simbolo(matched: list[Region], declared: str) -> list[Region]:
    """Declared symbol scopes the call. Empty declared claims every listed hunk.

    Without a resolved AST name on the hunks, the collector cannot scope and
    leaves the match as it is (tests and pre-resolve paths). That is not a
    silent claim of a named def: there is no name to claim.
    """
    if not declared:
        return matched
    if not any(region.symbol for region in matched):
        return matched
    return [region for region in matched if region.symbol == declared]


def _match_regions(by_path: Mapping[str, list[Region]], path: str) -> list[Region]:
    if path in by_path:
        return list(by_path[path])
    for candidate, items in by_path.items():
        if candidate.endswith("/" + path) or path.endswith("/" + candidate) or candidate == path:
            return list(items)
    return []


def _tool_name(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("tool_name") or event.get("name") or "")
    return str(getattr(event, "tool_name", "") or getattr(event, "name", "") or "")


def _tool_args(event: Any) -> tuple[dict[str, Any], Any, bool]:
    if isinstance(event, dict):
        raw = event.get("_raw_arguments")
        args = event.get("args") or event.get("arguments") or {}
        unparseable = raw is not None or not _schema_ok(_tool_name(event), args)
        return dict(args), raw, unparseable
    raw = getattr(event, "_raw_arguments", None)
    args = getattr(event, "args", None) or getattr(event, "arguments", None) or {}
    if not isinstance(args, dict):
        return {}, raw, True
    unparseable = raw is not None or not _schema_ok(_tool_name(event), args)
    return dict(args), raw, unparseable


def _schema_ok(name: str, args: Mapping[str, Any]) -> bool:
    if "file_path" in args and "path" not in args and name in WRITE_TOOLS | {"read"}:
        return False
    if name in WRITE_TOOLS | {"read"}:
        if "path" not in args:
            return False
    if name == "edit":
        edits = args.get("edits")
        if not isinstance(edits, list) or not edits:
            return False
        for edit in edits:
            if not isinstance(edit, dict) or "oldText" not in edit or "newText" not in edit:
                return False
    if name == INTENT_TOOL:
        has_files = isinstance(args.get("files"), list) and any(args.get("files") or [])
        has_file = bool(args.get("file") or args.get("path"))
        return bool(has_file or has_files) and "why" in args
    if name == BASH_TOOL:
        return "command" in args
    return True


def _paths_from_args(name: str, args: Mapping[str, Any]) -> list[str]:
    """Paths this event claims. ``record_intent`` may span files (G-3)."""
    if name == INTENT_TOOL:
        paths: list[str] = []
        files = args.get("files")
        if isinstance(files, list):
            paths.extend(str(item) for item in files if item)
        one = str(args.get("file") or args.get("path") or "")
        if one and one not in paths:
            paths.insert(0, one)
        return paths
    if name == BASH_TOOL:
        command = str(args.get("command") or "")
        found = _REDIRECT.findall(command)
        return [found[0]] if found else []
    path = str(args.get("path") or "")
    return [path] if path else []


def _apply_edit_size(pending: Pending, args: Mapping[str, Any]) -> None:
    edits = args.get("edits") or []
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                pending.bytes += len(str(edit.get("newText") or ""))
