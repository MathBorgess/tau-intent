"""Local token counts and the two numbers that turn a threat into data (G-4, P-3).

One number per side of the loop: ``cobertura_de_captura`` for production,
``aproveitamento_do_bloco`` for consumption. Neither calls a model, neither is
an outcome, and both are reported descriptively per condition.

Everything here shares **one key space**. The old ``cobertura`` compared a
region *path* against an entry's ``node_id()`` and only worked because
``symbol`` was always ``None`` (D5): fix one and the other broke in silence.
``chave()`` is now the single normaliser, and there is a test that says so.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

TOKENIZER = "whitespace-v1"


def count_tokens(text: str) -> int:
    """Declared tokenizer for v1: split on whitespace. Never chars/4."""
    if not text or not text.strip():
        return 0
    return len(text.split())


def chave(obj: Any) -> str:
    """The one key space: ``file::symbol`` when a symbol is known, else ``file``.

    Accepts a region, an intent entry, an anchor, or a bare string, so the two
    sides of a coverage ratio can never be counted in different units.
    """
    if isinstance(obj, str):
        return obj
    anchor = getattr(obj, "anchor", None)
    if anchor is not None:
        obj = anchor
    if hasattr(obj, "node_id"):
        return str(obj.node_id())
    file = getattr(obj, "file", None) or getattr(obj, "path", None) or ""
    symbol = getattr(obj, "symbol", None)
    return f"{file}::{symbol}" if symbol else str(file)


def _arquivo(key: str) -> str:
    return key.split("::", 1)[0]


def cobertura_de_captura(
    regions: Iterable[Any],
    entries: Iterable[Any],
    *,
    por_arquivo: bool = False,
) -> float:
    """Regions with a current intent / regions touched in the session (G-4).

    ``por_arquivo`` relaxes the match to the file level, which is what the
    ratio degrades to whenever the collector could not resolve a symbol. The
    strict form is the default so that a symbol regression shows up as a drop,
    not as a silent tie.
    """
    alvos = [chave(region) for region in regions]
    if not alvos:
        return 0.0
    cobertos = {chave(entry) for entry in entries}
    if por_arquivo:
        cobertos = {_arquivo(key) for key in cobertos}
        alvos = [_arquivo(key) for key in alvos]
    return sum(1 for alvo in alvos if alvo in cobertos) / len(alvos)


#: Kept for callers written before G-4. Same key space, same maths.
cobertura = cobertura_de_captura


def latencia_de_captura(pendentes: Mapping[Any, Any] | Iterable[Any]) -> dict[str, Any]:
    """Turns between the write event and the record_intent of the same region.

    Deterministic and free: the collector already records the ordinal of both
    (``Pending.write_turn`` / ``Pending.intent_turn``). Post-hoc rationalising
    becomes visible instead of invisible — a large latency means the intent was
    written well after the code, which is the threat, not a bug.
    """
    itens = list(pendentes.values()) if isinstance(pendentes, Mapping) else list(pendentes)
    por_regiao: dict[str, int] = {}
    sem_intencao = 0
    for pending in itens:
        write = getattr(pending, "write_turn", None)
        intent = getattr(pending, "intent_turn", None)
        region = getattr(pending, "region", None)
        if intent is None:
            sem_intencao += 1
            continue
        if write is None:
            continue
        por_regiao[chave(region)] = int(intent) - int(write)
    valores = list(por_regiao.values())
    return {
        "por_regiao": por_regiao,
        "media": sum(valores) / len(valores) if valores else None,
        "maxima": max(valores) if valores else None,
        "regioes_sem_intencao": sem_intencao,
    }


def aproveitamento_do_bloco(
    servidas: Iterable[Any],
    regioes_depois: Iterable[Any] = (),
    leituras: Iterable[Any] = (),
) -> dict[str, Any]:
    """Served entries whose symbol reappears in the diff or in the reads (P-3).

    Skeleton on purpose: it is the consumption pair of ``cobertura_de_captura``
    and it is descriptive per condition — **never** evidence that the
    projection worked, and never an outcome.
    """
    chaves = [chave(entry) for entry in servidas]
    if not chaves:
        return {"servidas": 0, "reaproveitadas": 0, "razao": 0.0, "chaves": []}
    depois = {chave(region) for region in regioes_depois}
    depois |= {chave(item) for item in leituras}
    por_arquivo = {_arquivo(key) for key in depois}
    reaproveitadas = [
        key for key in chaves if key in depois or _arquivo(key) in por_arquivo
    ]
    return {
        "servidas": len(chaves),
        "reaproveitadas": len(reaproveitadas),
        "razao": len(reaproveitadas) / len(chaves),
        "chaves": sorted(set(reaproveitadas)),
    }


def superadas_omitidas(entries: Sequence[Any], correntes: Sequence[Any]) -> int:
    """Entries in the store that the current view does not serve."""
    correntes_ids = {getattr(entry, "id", id(entry)) for entry in correntes}
    return sum(1 for entry in entries if getattr(entry, "id", id(entry)) not in correntes_ids)
