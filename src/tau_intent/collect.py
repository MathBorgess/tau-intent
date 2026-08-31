"""Collector: regions from git diff; tool events only attach why/property."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
        if not self.size:
            self.size = max(self.line_end - self.line_start + 1, 0)

    def key(self) -> tuple[str, int, int]:
        return (self.path, self.line_start, self.line_end)


@dataclass
class Pending:
    region: Region
    why: str = ""
    property: str = ""
    domain: str = ""
    unparseable: bool = False
    raw_arguments: Any = None
    bytes: int = 0
    trigger_log: list[str] = field(default_factory=list)


def regions_from_diff(diff: str | Iterable[Region]) -> list[Region]:
    """Parse a unified git diff, or pass through an already-built region list."""
    if not isinstance(diff, str):
        return list(diff)
    regions: list[Region] = []
    path = ""
    for line in diff.splitlines():
        git = _DIFF_GIT.match(line)
        if git:
            path = git.group(1)
            continue
        plus = _PLUS_PLUS.match(line)
        if plus and plus.group(1) != "/dev/null":
            path = plus.group(1)
            continue
        hunk = _HUNK.match(line)
        if hunk and path:
            start = int(hunk.group(1))
            count = int(hunk.group(2) or "1")
            end = start + max(count, 1) - 1
            regions.append(Region(path=path, line_start=start, line_end=end, size=count))
    return regions


def collect_events(
    events: Iterable[Any],
    regions: Iterable[Region],
) -> dict[tuple[str, int, int], Pending]:
    """Attach why/property from tool events onto git-diff regions.

    Unparseable (V6): ``_raw_arguments`` present, or local schema refused
    (missing ``path``, ``file_path`` used instead, edit without ``edits``).
    """
    by_path = _index_regions(regions)
    pendentes: dict[tuple[str, int, int], Pending] = {}

    for event in events:
        name = _tool_name(event)
        args, raw, unparseable = _tool_args(event)
        if name in WRITE_TOOLS or name == INTENT_TOOL or name == BASH_TOOL:
            path = _path_from_args(name, args)
            if unparseable or not path:
                unparseable = True
            matched = (
                _match_regions(by_path, path)
                if path
                else [region for group in by_path.values() for region in group]
            )
            if not matched and path:
                region = Region(path=path, line_start=0, line_end=0)
                matched = [region]
                by_path.setdefault(path, []).append(region)
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
                if name in WRITE_TOOLS:
                    pending.bytes += len(str(args.get("content") or ""))
                    _apply_edit_size(pending, args)
    return pendentes


def _index_regions(regions: Iterable[Region]) -> dict[str, list[Region]]:
    indexed: dict[str, list[Region]] = {}
    for region in regions:
        indexed.setdefault(region.path, []).append(region)
    return indexed


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
        return "file" in args and "why" in args
    if name == BASH_TOOL:
        return "command" in args
    return True


def _path_from_args(name: str, args: Mapping[str, Any]) -> str:
    if name == INTENT_TOOL:
        return str(args.get("file") or args.get("path") or "")
    if name == BASH_TOOL:
        command = str(args.get("command") or "")
        found = _REDIRECT.findall(command)
        return found[0] if found else ""
    return str(args.get("path") or "")


def _apply_edit_size(pending: Pending, args: Mapping[str, Any]) -> None:
    edits = args.get("edits") or []
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                pending.bytes += len(str(edit.get("newText") or ""))
