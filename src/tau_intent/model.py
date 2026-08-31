from dataclasses import dataclass


@dataclass(frozen=True)
class Anchor:
    path: str
    start_line: int
    end_line: int

    def overlaps(self, other: "Anchor") -> bool:
        return (
            self.path == other.path
            and self.start_line <= other.end_line
            and other.start_line <= self.end_line
        )


@dataclass(frozen=True)
class IntentEntry:
    id: str
    why: str
    property: str | None
    anchors: tuple[Anchor, ...]
    supersedes: tuple[str, ...] = ()
