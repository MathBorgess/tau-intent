"""Deterministic structural gate. Pure function: no I/O, no tau, no model.

H15 / G-8: the gate never judges prose. ``why`` and ``property`` are natural
language for capture and for the derived view; every code below is fed by
evidence derived from **code and schema** — the diff, the AST symbol table,
JSON parse status, typed fields. There is no regex over ``why``, no stopword
list, no citation grammar. The lexical path (``GENERICAS``, ``GENERICA``,
``_STOP``, ``_cited_symbols``) was deleted, not disabled (G-1.1, G-1.2, D8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

#: The structural taxonomy (G-8 + G-2). Declared here, frozen in ``gate.yaml``.
#: ANCORA_AMBIGUA was deleted: grouping is authorship (the why), not AST names.
CODIGOS = (
    "AUSENTE",
    "NAO_PARSEAVEL",
    "SIMBOLO_NAO_RESOLVIDO",
    "EDICAO_GRANDE_SEM_SIMBOLO",
    "DOMINIO_AUSENTE",
)


@dataclass(frozen=True)
class GateConfig:
    """Every number the gate reads lives here (G-0).

    ``contexto_diff`` used to be implicit: ``_region_size`` counted the whole
    hunk, context lines included, so ``limiar_edicao`` did not mean what any
    note assumed (D7 / G-1.3). It is now declared, and the collector may
    override the estimate with an exact ``edited_lines`` count.
    """

    n_max: int = 3
    limiar_edicao: int = 51
    contexto_diff: int = 3
    versao: str = "gate-v2-estrutural"
    codigos: tuple[str, ...] = field(default=CODIGOS)


@dataclass(frozen=True)
class Falha:
    code: str
    region: object
    detail: str = ""


@dataclass(frozen=True)
class Veredito:
    tipo: str
    falhas: tuple[Falha, ...] = ()
    nao_avaliaveis: tuple[Falha, ...] = ()

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
    """Run the structural checks over touched regions.

    ``regions`` come from a git diff (the caller supplies them; this function
    does not run git). ``pendentes`` maps a region key or path to a collector
    ``Pending``-shaped object. ``symbols`` is a **precomputed symbol table**
    from the AST — plain names and/or ``file::symbol`` node ids; this function
    never parses a file and never reads the filesystem.

    Codes, and the evidence each one is made of:

    ``AUSENTE``                   diff x collector: region with no intent
    ``NAO_PARSEAVEL``             tool-call JSON: ``_raw_arguments`` / schema refused
    ``SIMBOLO_NAO_RESOLVIDO``     AST: ``symbol`` set but not resolvable in ``file``
    ``EDICAO_GRANDE_SEM_SIMBOLO`` diff + AST: identity over limiar, no resolved symbol
    ``DOMINIO_AUSENTE``           schema: ``domain`` empty (presence, not semantics)

    AtomicCommitBench (2607.03332): a median episode is 12 hunks / 6 files,
    not 12 intents and not 12× the line threshold. Spanning files is allowed.
    One why may span several AST symbols in the same file — first construction
    routinely splits a feature into helpers. Grouping is the why (a label such
    as fix/refactor lives there); the gate does not split on AST names.
    ``limiar_edicao`` (51, declared) is compared to edited lines **summed per
    (file, symbol)**, not per hunk, not per episode, and not per intent.
    """
    known = set(symbols)
    falhas: list[Falha] = []
    nao_avaliaveis: list[Falha] = []
    totais = _totais_editados(regions, cfg)

    for region in regions:
        resolver = (region.get("resolver", "fornecido") if isinstance(region, dict)
                    else getattr(region, "resolver", "fornecido"))
        fina_disponivel = resolver is not None and (bool(_region_symbol(region)) or resolver == "fornecido")
        if resolver is None:
            nao_avaliaveis.extend(Falha(code, region, "fonte de identidades indisponível")
                                  for code in ("SIMBOLO_NAO_RESOLVIDO", "EDICAO_GRANDE_SEM_SIMBOLO"))
        elif not fina_disponivel:
            nao_avaliaveis.append(Falha("EDICAO_GRANDE_SEM_SIMBOLO", region,
                                       "efeito sem identidade fina observável"))
        pending = _lookup(pendentes, region)
        if pending is None:
            falhas.append(Falha("AUSENTE", region))
            continue
        if _flag(pending, "unparseable"):
            falhas.append(Falha("NAO_PARSEAVEL", region, _detail_raw(pending)))
            continue
        if not _field(pending, "why").strip():
            falhas.append(Falha("AUSENTE", region))
            continue

        symbol = _field(pending, "symbol")
        resolvido = _resolve(symbol, region, known)
        if resolver is not None and symbol and not resolvido:
            falhas.append(Falha("SIMBOLO_NAO_RESOLVIDO", region, symbol))

        total = totais[_chave_edicao(region)]
        if fina_disponivel and total > cfg.limiar_edicao and not resolvido:
            falhas.append(
                Falha(
                    "EDICAO_GRANDE_SEM_SIMBOLO",
                    region,
                    f"{total} {getattr(region, 'size_unit', 'unidades')}",
                )
            )

        if not _field(pending, "domain").strip():
            falhas.append(Falha("DOMINIO_AUSENTE", region))

    tipo = "PASSA" if not falhas else ("ESCALAR" if bloqueios >= cfg.n_max else "BLOQUEIA")
    return Veredito(tipo, tuple(falhas), tuple(nao_avaliaveis))


avaliar = portao
evaluate_gate = portao


def _chave_edicao(region: object) -> tuple[str, str]:
    """Identity the line threshold is measured against: (file, AST symbol)."""
    return _region_path(region), _region_symbol(region)


def _totais_editados(
    regions: Sequence[object], cfg: GateConfig
) -> dict[tuple[str, str], int]:
    """Sum edited lines per (file, symbol). Twelve 8-line hunks of ``f`` are 96.

    AtomicCommitBench counts hunks and files, not lines. A median 12-hunk /
    6-file episode with small hunks stays under ``limiar_edicao`` per identity.
    One rewritten function split across hunks does not. The declared 51 is the
    paper's mean hunks/episode, used as the line threshold — units stay lines.
    """
    totais: dict[tuple[str, str], int] = {}
    for region in regions:
        key = _chave_edicao(region)
        totais[key] = totais.get(key, 0) + _region_size(region, cfg)
    return totais


def _region_symbol(region: object) -> str:
    value = getattr(region, "symbol", None)
    if value is None and isinstance(region, dict):
        value = region.get("symbol")
    return str(value or "")


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


def _region_key(region: object) -> tuple:
    if callable(getattr(region, "key", None)):
        return region.key()
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
    if callable(getattr(region, "span", None)):
        return region.span()
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


def _region_size(region: object, cfg: GateConfig) -> int:
    """Lines added or changed — not hunk length (D7 / G-1.3).

    If the collector supplied an exact ``edited_lines`` count, trust it. Only
    when it did not do we fall back to the hunk length minus the declared
    ``contexto_diff`` on both sides, which is an estimate and is documented as
    one.
    """
    units = _int_attr(region, "edited_units")
    if units is not None:
        return max(units, 0)
    exact = _int_attr(region, "edited_lines")
    if exact is None:
        exact = _int_attr(region, "linhas_editadas")
    if exact is not None:
        return max(exact, 0)

    size = _int_attr(region, "size")
    if size is None:
        start, end = _region_span(region)
        size = max(end - start + 1, 0)
    return max(size - 2 * cfg.contexto_diff, 0)


def _int_attr(region: object, name: str) -> int | None:
    value = getattr(region, name, None)
    if value is None and isinstance(region, dict):
        value = region.get(name)
    if value is None:
        return None
    return int(value)


def _ranges_overlap(left: object, right: object) -> bool:
    ls, le = _region_span(left)
    rs, re_ = _region_span(right)
    if (ls, le) == (0, 0) or (rs, re_) == (0, 0):
        return True
    return ls <= re_ and rs <= le


def _field(pending: object, name: str) -> str:
    if isinstance(pending, dict):
        return str(pending.get(name) or "")
    return str(getattr(pending, name, "") or "")


def _flag(pending: object, name: str) -> bool:
    if isinstance(pending, dict):
        return bool(pending.get(name))
    return bool(getattr(pending, name, False))


def _detail_raw(pending: object) -> str:
    raw = pending.get("raw_arguments") if isinstance(pending, dict) else getattr(
        pending, "raw_arguments", None
    )
    return "" if raw is None else str(raw)[:120]


def _resolve(symbol: str, region: object, known: set[str]) -> bool:
    """Does ``symbol`` resolve inside ``region``'s file, per the AST table?"""
    if not symbol:
        return False
    witnessed = _region_symbol(region)
    if witnessed and symbol != witnessed:
        return False
    if symbol in known:
        return True
    path = _region_path(region)
    return bool(path) and f"{path}::{symbol}" in known
