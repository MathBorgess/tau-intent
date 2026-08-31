"""PR4-only fallbacks used when collect/gate/tools from earlier slices are absent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


@dataclass
class Region:
    path: str
    line_start: int = 0
    line_end: int = 0
    size: int = 1


@dataclass
class Pending:
    region: Region
    why: str = ""
    property: str = ""
    domain: str = ""
    unparseable: bool = False
    trigger_log: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateConfig:
    n_max: int = 3
    limiar_edicao: int = 40


@dataclass(frozen=True)
class Falha:
    code: str
    region: object
    detail: str = ""


@dataclass(frozen=True)
class Veredito:
    tipo: str
    falhas: tuple = ()

    @classmethod
    def passa(cls) -> "Veredito":
        return cls("PASSA")

    @classmethod
    def bloqueia(cls, falhas: Sequence[Falha]) -> "Veredito":
        return cls("BLOQUEIA", tuple(falhas))

    @classmethod
    def escalar(cls, falhas: Sequence[Falha]) -> "Veredito":
        return cls("ESCALAR", tuple(falhas))


def regions_from_diff(diff: str | Iterable[Region]) -> list[Region]:
    if not isinstance(diff, str):
        return list(diff)
    regions: list[Region] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
        elif line.startswith("@@"):
            plus = line.split("+", 1)[-1].split(" ", 1)[0]
            start_s, _, count_s = plus.partition(",")
            try:
                start = int(start_s)
                count = int(count_s or "1")
            except ValueError:
                continue
            regions.append(
                Region(path=path, line_start=start, line_end=start + max(count, 1) - 1, size=count)
            )
    return regions


def collect_events(events: Iterable[Any], regions: Iterable[Region]) -> dict:
    pendentes: dict[str, Pending] = {}
    region_list = list(regions)
    by_path = {r.path: r for r in region_list}
    for event in events:
        name = getattr(event, "tool_name", "") or (
            event.get("tool_name") if isinstance(event, dict) else ""
        )
        args = getattr(event, "args", None) or (event.get("args") if isinstance(event, dict) else {}) or {}
        path = str(args.get("path") or args.get("file") or "")
        region = by_path.get(path) or (region_list[0] if region_list else Region(path=path or "unknown"))
        pending = pendentes.setdefault(region.path, Pending(region=region))
        if name == "record_intent":
            pending.why = str(args.get("why") or "")
            pending.property = str(args.get("property") or "")
            pending.domain = str(args.get("domain") or "")
        if getattr(event, "_raw_arguments", None) is not None:
            pending.unparseable = True
    return pendentes


def portao(
    regions: Sequence[object],
    pendentes: Mapping[object, object],
    symbols: Sequence[str] | set[str],
    cfg: GateConfig,
    bloqueios: int,
) -> Veredito:
    del symbols
    falhas = []
    for region in regions:
        path = getattr(region, "path", region)
        pending = pendentes.get(path) or pendentes.get(getattr(region, "key", lambda: path)())
        if pending is None:
            falhas.append(Falha("AUSENTE", region))
            continue
        why = str(getattr(pending, "why", "") or "")
        if not why:
            falhas.append(Falha("AUSENTE", region))
    if not falhas:
        return Veredito.passa()
    if bloqueios >= cfg.n_max:
        return Veredito.escalar(falhas)
    return Veredito.bloqueia(falhas)


def catalog(*, capture: bool) -> list[dict]:
    names = ["read", "write", "edit", "bash"]
    if capture:
        names.append("record_intent")
    return [{"name": name} for name in names]
