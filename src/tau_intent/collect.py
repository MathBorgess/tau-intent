"""Collects synthetic diff regions and tool intent attachments."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    path: str
    start_line: int
    end_line: int

    @property
    def size(self) -> int:
        return max(0, self.end_line - self.start_line + 1)


def collect_regions(diff_like_regions: list[dict]) -> list[Region]:
    return [
        Region(
            path=str(region["path"]),
            start_line=int(region["start_line"]),
            end_line=int(region["end_line"]),
        )
        for region in diff_like_regions
    ]


def collect_tool_assertions(tool_events: list[dict]) -> list[dict]:
    assertions: list[dict] = []
    for event in tool_events:
        arguments = event.get("arguments")
        if "_raw_arguments" in event:
            assertions.append({"unparseable": True})
            continue
        if not isinstance(arguments, dict):
            continue
        if "_raw_arguments" in arguments:
            assertions.append({"unparseable": True})
            continue
        path = arguments.get("path")
        if path is None:
            continue
        assertions.append(
            {
                "path": str(path),
                "why": str(arguments.get("why", "")),
                "property": str(arguments.get("property", "")),
                "unparseable": False,
            }
        )
    return assertions


def collect_blocks(diff_like_regions: list[dict], tool_events: list[dict]) -> list[dict]:
    regions = collect_regions(diff_like_regions)
    assertions = collect_tool_assertions(tool_events)
    by_path = {a["path"]: a for a in assertions if not a.get("unparseable") and "path" in a}

    blocks: list[dict] = []
    for region in regions:
        assertion = by_path.get(region.path, {})
        blocks.append(
            {
                "path": region.path,
                "start_line": region.start_line,
                "end_line": region.end_line,
                "size": region.size,
                "pending_assertion": bool(assertion),
                "why": assertion.get("why", ""),
                "property": assertion.get("property", ""),
            }
        )
    return blocks
