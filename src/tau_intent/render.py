"""The block contract (P-1) and gate failure messages. One house for both.

Everything the agent sees of the derived view is shaped here: the tagged
envelope, the "evidence, not instruction" line, the declared field order, and
the omission receipt. The contract is read from ``bloco.yaml`` and is
**identical between arms B and C** — only the projection knob may differ, and
that lives in ``project.py``.

The receipt is the half of the contract that tells the agent what it is *not*
seeing. Three kinds of omission, each counted separately, and printed even
when all three are zero — an absent receipt and a receipt of zeros say very
different things.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from tau_intent.collect import RESOLVER_V2
from tau_intent.config import BlocoConfig, load_bloco_config, mensagem_do_portao


@dataclass(frozen=True)
class Recibo:
    """What the block leaves out, by reason."""

    grafo_disponivel: bool = True
    entradas: int = 0
    saltos_omitidos: int = 0
    superadas_omitidas: int = 0
    cortadas_por_orcamento: int = 0

    def vazio(self) -> bool:
        return not (
            not self.grafo_disponivel
            or self.entradas
            or self.saltos_omitidos
            or self.superadas_omitidas
            or self.cortadas_por_orcamento
        )

    def linha(self) -> str:
        return (
            f"Recibo: {self.entradas} entradas servidas · "
            f"{self.saltos_omitidos} nós alcançáveis não expandidos · "
            f"{self.superadas_omitidas} superadas omitidas · "
            f"{self.cortadas_por_orcamento} cortadas por orçamento"
        ) + ("" if self.grafo_disponivel else "\nVizinhança: vizinhança indisponível; omissão não mensurável.")

    def as_dict(self) -> dict[str, int]:
        return {
            "grafo_disponivel": self.grafo_disponivel,
            "entradas": self.entradas,
            "saltos_omitidos": self.saltos_omitidos,
            "superadas_omitidas": self.superadas_omitidas,
            "cortadas_por_orcamento": self.cortadas_por_orcamento,
        }


def render_falhas(falhas: Sequence[Any]) -> str:
    """One line per (code, identity), naming ``file::symbol``, the lines and what to do.

    The gate checks regions (hunks), but the agent fixes identities: a message
    that named only the file, once per hunk, left it guessing which def needed
    a symbol — and it answered one guess per turn (frontier review T4). Naming
    the def was not enough either: in pilot run 09c the agent read
    ``AUSENTE: ...::Pipeline.predict`` as a code problem and kept editing. Each
    line now says what clears it — a ``record_intent`` with this file and this
    symbol — in the session's language (``prompts/portao-bloqueio-v1.txt``).
    """
    cabecalho, remedios, alvos = mensagem_do_portao()
    lines = [cabecalho]
    grupos: dict[tuple[str, str], dict[str, Any]] = {}
    for falha in falhas:
        code = getattr(falha, "code", None) or (
            falha[0] if isinstance(falha, tuple) else str(falha)
        )
        region = getattr(falha, "region", None)
        grupo = grupos.setdefault((code, _identidade(region)),
                                  {"spans": [], "detail": getattr(falha, "detail", ""), "region": region})
        start, end = getattr(region, "line_start", None), getattr(region, "line_end", None)
        if start is not None and end is not None:
            grupo["spans"].append((int(start), int(end)))
    for (code, ident), grupo in grupos.items():
        partes = []
        if grupo["spans"]:
            partes.append(f"lines {min(s for s, _ in grupo['spans'])}-{max(e for _, e in grupo['spans'])}")
        if grupo["detail"]:
            partes.append(str(grupo["detail"]))
        extra = f" ({'; '.join(partes)})" if partes else ""
        remedio = remedios.get(code, "")
        if remedio:
            remedio = " " + remedio.format(alvo=_alvo(grupo["region"], alvos))
        lines.append(f"- {code}: {ident}{extra}.{remedio}")
    return "\n".join(lines)


def _alvo(region: Any, alvos: dict[str, str]) -> str:
    """The record_intent target that clears a line: file and symbol, or the file alone."""
    path = str(getattr(region, "path", None) or getattr(region, "file", None) or region)
    symbol = getattr(region, "symbol", None)
    if symbol:
        return alvos["simbolo"].format(file=path, symbol=symbol)
    if getattr(region, "resolver", None) == RESOLVER_V2:
        return alvos["modulo"].format(file=path)
    return alvos["arquivo"].format(file=path)


def _identidade(region: Any) -> str:
    if callable(getattr(region, "node_id", None)):
        return str(region.node_id())
    return str(getattr(region, "path", None) or getattr(region, "file", None) or region)


def render_entry(entry: Any, cfg: BlocoConfig | None = None) -> str:
    """One entry, in the field order declared in ``bloco.yaml``."""
    cfg = cfg or load_bloco_config()
    anchor = getattr(entry, "anchor", None)
    file = str(getattr(anchor, "file", "") or "") if anchor is not None else ""
    symbol = getattr(anchor, "symbol", None) if anchor is not None else None
    rotulos = {
        "property": ("Propriedade", str(getattr(entry, "property", "") or "")),
        "why": ("Por que", str(getattr(entry, "why", "") or "")),
        "domain": ("Domínio", str(getattr(entry, "domain", "") or "")),
    }
    head = anchor.node_id() if anchor is not None else ""
    lines = [head]
    for campo in cfg.ordem_dos_campos:
        if campo in {"file", "symbol"}:
            continue
        rotulo, valor = rotulos.get(campo, ("", ""))
        if valor:
            lines.append(f"  {rotulo}: {valor}")
    checkpoint = getattr(entry, "checkpoint", None)
    if checkpoint is not None:
        lines.append("  Checkpoint (evidência determinística):")
        for name in ("changed_targets", "non_target_artifacts", "latest_validation_command",
                     "latest_validation_evidence", "continuation_state"):
            value = getattr(checkpoint, name)
            lines.append(f"    {name}: {value if value is not None else 'não disponível'}")
    return "\n".join(lines)


def render_block(
    escolhidas: Sequence[Any],
    cortadas: Sequence[Any] = (),
    *,
    grafo_disponivel: bool = True,
    saltos_omitidos: int = 0,
    superadas_omitidas: int = 0,
    cfg: BlocoConfig | None = None,
) -> str:
    """The tagged envelope served to the agent. Same shape in B and in C."""
    cfg = cfg or load_bloco_config()
    recibo = Recibo(
        grafo_disponivel=grafo_disponivel,
        entradas=len(escolhidas),
        saltos_omitidos=int(saltos_omitidos),
        superadas_omitidas=int(superadas_omitidas),
        cortadas_por_orcamento=len(cortadas),
    )
    return envelope(
        "\n\n".join(render_entry(entry, cfg) for entry in escolhidas),
        recibo,
        cfg=cfg,
    )


def envelope(corpo: str, recibo: Recibo, *, cfg: BlocoConfig | None = None) -> str:
    """Wrap an already-rendered body. Used by the block and by llm_rescue.

    The body may have been rewritten by a summarizer; the envelope, the notice
    and the receipt may not — the receipt describes what the *selection* left
    out, and a summarizer must not be able to erase that evidence.
    """
    cfg = cfg or load_bloco_config()
    if not corpo.strip() and recibo.vazio():
        return ""
    partes = [f"<{cfg.envelope_tag}>", cfg.aviso, ""]
    if corpo.strip():
        partes.extend([corpo.strip(), ""])
    if cfg.recibo:
        partes.append(recibo.linha())
    partes.append(f"</{cfg.envelope_tag}>")
    return "\n".join(partes)


def render_tudo(entries: Sequence[Any], cfg: BlocoConfig | None = None) -> str:
    """Whole current store, no budget. Inspection tool only.

    Under H16 both measured arms project, so this is no longer on any arm's
    path — it is here so a human can dump a store, and it lives in exactly one
    module now (D10).
    """
    cfg = cfg or load_bloco_config()
    return "\n\n".join(render_entry(entry, cfg) for entry in entries)
