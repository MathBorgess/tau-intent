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

#: Two token units live side by side and must never be mixed (P-4).
#: ``whitespace-v1`` is the declared unit of the *projection budget*: it is local,
#: deterministic and provider-independent, which is what a frozen budget needs.
#: ``provider_usage`` is the unit of the *outcome* (Q3): what the endpoint billed
#: per call. Neither is ever estimated from the other.
OUTCOME_TOKEN_UNIT = "provider_usage"
BUDGET_TOKEN_UNIT = TOKENIZER
USAGE_PROVIDER = "provider_usage"
USAGE_MISSING = "missing"


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
    regions: Iterable[Any], entries: Iterable[Any],
) -> dict[str, Any]:
    """Fine witness coverage and target coverage are different populations.

    Fine coverage counts regions whose witness actually resolved an identity.
    Target coverage counts distinct coarse targets. Neither substitutes for the
    other; an empty denominator is unknown, never success or failure.
    """
    regions, entries = list(regions), list(entries)
    finas = [r for r in regions if getattr(r, "resolver", "fornecido") is not None
             and "::" in chave(r)]
    cobertos = {chave(e) for e in entries}
    alvos = {_arquivo(chave(r)) for r in regions}
    cobertos_alvos = {_arquivo(k) for k in cobertos}
    n = sum(chave(r) in cobertos for r in finas)
    coarse = len(alvos & cobertos_alvos)
    return {
        "estrita": n / len(finas) if finas else None,
        "por_arquivo": coarse / len(alvos) if alvos else None,
        "fracao_resolvida": len(finas) / len(regions) if regions else None,
        "numeradores": {"estrita": n, "por_arquivo": coarse,
                         "fracao_resolvida": len(finas)},
        "denominadores": {"estrita": len(finas), "por_arquivo": len(alvos),
                           "fracao_resolvida": len(regions)},
        "granularidade": {"simbolo": len(finas), "alvo": len(regions)-len(finas)},
    }


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
        "denominador": len(valores),
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
        return {"servidas": 0, "reaproveitadas": 0, "razao": None, "chaves": [], "criterio": "simbolo"}
    depois = {chave(region) for region in regioes_depois}
    depois |= {chave(item) for item in leituras}
    por_arquivo = {_arquivo(key) for key in depois}
    # An entry anchored on a symbol is reused only if that symbol changed; a
    # file-level entry has no finer key, so the file decides. Matching every
    # entry by file made the ratio 1 in any one-file host (frontier review T9).
    reaproveitadas = [
        key for key in chaves
        if key in depois or ("::" not in key and _arquivo(key) in por_arquivo)
    ]
    return {
        "servidas": len(chaves),
        "reaproveitadas": len(reaproveitadas),
        "razao": len(reaproveitadas) / len(chaves),
        "chaves": sorted(set(reaproveitadas)),
        "criterio": "simbolo",
    }


def superadas_omitidas(entries: Sequence[Any], correntes: Sequence[Any]) -> int:
    """Entries in the store that the current view does not serve."""
    correntes_ids = {getattr(entry, "id", id(entry)) for entry in correntes}
    return sum(1 for entry in entries if getattr(entry, "id", id(entry)) not in correntes_ids)


def uso_do_provedor(message: Any) -> dict[str, int] | None:
    """Tokens one provider call reported, or ``None`` when it reported none.

    ``tokens_in`` is the whole prompt (fresh + cache read + cache write): there is
    no cache discount in the outcome (RUNBOOK §6). ``tokens_out`` is the
    completion, reasoning included. tau fills a zeroed ``Usage`` when the endpoint
    sent no usage chunk, and a real response never has zero prompt *and* zero
    completion tokens, so the all-zero case is reported as missing, not as free.
    """
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    try:
        entrada = int(usage.input) + int(usage.cache_read) + int(usage.cache_write)
        saida = int(usage.output)
    except (AttributeError, TypeError, ValueError):
        return None
    if entrada == 0 and saida == 0:
        return None
    return {"tokens_in": entrada, "tokens_out": saida}


def linha_de_turno(index: int, kind: str, uso: dict[str, int] | None, tool_calls: int,
                   timing: Any = None) -> dict[str, Any]:
    """One row per provider call. ``timing`` (tau's ``ResponseTiming``, measured on the
    provider stream) adds ``latency_ms`` and ``ttft_ms``: throughput telemetry, descriptive,
    never an outcome. Without it the row is the V1 row, unchanged."""
    row = {
        "turn_index": index,
        "kind": kind,
        "tokens_in": None if uso is None else uso["tokens_in"],
        "tokens_out": None if uso is None else uso["tokens_out"],
        "tool_calls": tool_calls,
    }
    if timing is not None:
        row["latency_ms"] = getattr(timing, "total_duration_ms", None)
        row["ttft_ms"] = getattr(timing, "time_to_first_output_ms", None)
    return row


def resumir_tokens(
    turnos: Iterable[Mapping[str, Any]],
    chamadas_rescue: Iterable[Mapping[str, Any]] = (),
    *,
    chamada_interrompida: bool = False,
) -> dict[str, Any]:
    """Outcome tokens of one (arm, task), from per-call provider usage only.

    Agent calls and rescue calls (accepted or discarded: a rejected rewrite still
    cost the model) are summed separately. If any call of a side returned no
    usage, that side is ``None`` and ``source`` is ``"missing"``: a partial sum
    would read as a measurement. Nothing is ever estimated.
    """
    def soma(linhas: list[Mapping[str, Any]]) -> tuple[int | None, int | None]:
        if any(l.get("tokens_in") is None or l.get("tokens_out") is None for l in linhas):
            return None, None
        return (sum(int(l["tokens_in"]) for l in linhas),
                sum(int(l["tokens_out"]) for l in linhas))

    agente = [t for t in turnos if t.get("kind") != "rescue"]
    resgate = list(chamadas_rescue)
    entrada, saida = soma(agente)
    r_entrada, r_saida = soma(resgate)
    completo = None not in (entrada, saida, r_entrada, r_saida)
    out: dict[str, Any] = {
        "in": entrada,
        "out": saida,
        "rescue_in": r_entrada,
        "rescue_out": r_saida,
        "source": USAGE_PROVIDER if completo else USAGE_MISSING,
        "cost_usd": 0,
        "unit": OUTCOME_TOKEN_UNIT,
        "budget_unit": BUDGET_TOKEN_UNIT,
    }
    if chamada_interrompida:
        # The cut call spent tokens nobody reported: the sums are a lower bound.
        out["incomplete_call"] = True
    return out
