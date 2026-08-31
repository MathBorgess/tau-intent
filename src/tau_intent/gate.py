"""Deterministic gate. Pure function: no I/O, no tau, no model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

GENERICAS = re.compile(r"^(melhora|corrige|refatora|ajusta|atualiza)\b", re.I)

_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "not",
        "must",
        "never",
        "return",
        "none",
        "true",
        "false",
        "this",
        "that",
        "with",
        "from",
        "into",
        "when",
        "then",
        "else",
        "raises",
        "raise",
        "empty",
        "partial",
        "dict",
        "list",
        "str",
        "int",
        "com",
        "que",
        "para",
        "nao",
        "uma",
        "uma",
        "os",
        "as",
        "de",
        "do",
        "da",
        "em",
        "um",
        "no",
        "na",
        "por",
        "seu",
        "sua",
    }
)


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
    falhas: tuple[Falha, ...] = ()

    @classmethod
    def passa(cls) -> "Veredito":
        return cls("PASSA")

    @classmethod
    def bloqueia(cls, falhas: Sequence[Falha]) -> "Veredito":
        return cls("BLOQUEIA", tuple(falhas))

    @classmethod
    def escalar(cls, falhas: Sequence[Falha]) -> "Veredito":
        return cls("ESCALAR", tuple(falhas))


def portao(
    regions: Sequence[object],
    pendentes: Mapping[object, object],
    symbols: Sequence[str] | set[str],
    cfg: GateConfig,
    bloqueios: int,
) -> Veredito:
    """Run the four deterministic checks over touched regions.

    ``regions`` come from a git diff (caller supplies them; this function
    does not run git). ``pendentes`` maps a region-key or path to an object
    with ``why`` / ``property`` attributes (or a mapping with those keys).
    ``symbols`` is a precomputed name set from AST; this function does not
    parse files.
    """
    known = set(symbols)
    falhas: list[Falha] = []
    for region in regions:
        pending = _lookup(pendentes, region)
        if pending is None or not _field(pending, "why").strip():
            falhas.append(Falha("AUSENTE", region))
            continue
        why = _field(pending, "why")
        prop = _field(pending, "property")
        if GENERICAS.match(why.strip()):
            falhas.append(Falha("GENERICA", region, why))
        cited = _cited_symbols(prop)
        if cited and not cited <= known:
            falhas.append(Falha("PROPERTY_SEM_SIMBOLO", region, prop))
        if _region_size(region) > cfg.limiar_edicao and not prop.strip():
            falhas.append(Falha("EDICAO_GRANDE_SEM_PROPERTY", region))

    if not falhas:
        return Veredito.passa()
    if bloqueios >= cfg.n_max:
        return Veredito.escalar(falhas)
    return Veredito.bloqueia(falhas)


avaliar = portao
evaluate_gate = portao


def _lookup(pendentes: Mapping[object, object], region: object) -> object | None:
    key = _region_key(region)
    if key in pendentes:
        return pendentes[key]
    path = _region_path(region)
    if path in pendentes:
        return pendentes[path]
    for candidate in pendentes.values():
        cand_region = getattr(candidate, "region", candidate)
        if _region_path(cand_region) == path and _ranges_overlap(region, cand_region):
            return candidate
    return None


def _region_key(region: object) -> object:
    path = _region_path(region)
    start, end = _region_span(region)
    return (path, start, end)


def _region_path(region: object) -> str:
    if isinstance(region, (tuple, list)) and region:
        return str(region[0])
    for name in ("path", "file"):
        value = getattr(region, name, None)
        if value:
            return str(value)
    if isinstance(region, dict):
        return str(region.get("path") or region.get("file") or "")
    return str(region)


def _region_span(region: object) -> tuple[int, int]:
    start = getattr(region, "line_start", None)
    end = getattr(region, "line_end", None)
    if start is None:
        start = getattr(region, "start_line", None)
    if end is None:
        end = getattr(region, "end_line", None)
    if isinstance(region, dict):
        start = start or region.get("line_start") or region.get("start_line")
        end = end or region.get("line_end") or region.get("end_line")
    if isinstance(region, (tuple, list)) and len(region) >= 3:
        start, end = region[1], region[2]
    return int(start or 0), int(end or 0)


def _region_size(region: object) -> int:
    size = getattr(region, "size", None)
    if size is None and isinstance(region, dict):
        size = region.get("size")
    if size is not None:
        return int(size)
    start, end = _region_span(region)
    return max(end - start + 1, 0)


def _ranges_overlap(left: object, right: object) -> bool:
    ls, le = _region_span(left)
    rs, re = _region_span(right)
    if (ls, le) == (0, 0) or (rs, re) == (0, 0):
        return True
    return ls <= re and rs <= le


def _field(pending: object, name: str) -> str:
    if isinstance(pending, dict):
        return str(pending.get(name) or "")
    return str(getattr(pending, name, "") or "")


def _cited_symbols(property_text: str) -> set[str]:
    text = property_text or ""
    dotted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", text)
    camel = re.findall(r"\b[A-Z][A-Za-z0-9_]+", text)
    snake = re.findall(r"\b[a-z][a-z0-9]*_[A-Za-z0-9_]+", text)
    return set(dotted) | set(camel) | set(snake)
