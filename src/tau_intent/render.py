"""Human-readable gate failures and full-store serving. Independent of project.py."""

from __future__ import annotations

from typing import Any, Sequence


def render_falhas(falhas: Sequence[Any]) -> str:
    lines = [
        "O portão bloqueou o turno. Corrija as falhas abaixo e continue na mesma sessão."
    ]
    for falha in falhas:
        code = getattr(falha, "code", None) or (
            falha[0] if isinstance(falha, tuple) else str(falha)
        )
        region = getattr(falha, "region", None)
        path = getattr(region, "path", None) or getattr(region, "file", None) or region
        detail = getattr(falha, "detail", "")
        extra = f" ({detail})" if detail else ""
        lines.append(f"- {code}: {path}{extra}")
    return "\n".join(lines)


def render_tudo(entries: Sequence[Any]) -> str:
    parts: list[str] = []
    for entry in entries:
        anchor = getattr(entry, "anchor", None)
        file = getattr(anchor, "file", "") if anchor is not None else ""
        symbol = getattr(anchor, "symbol", None) if anchor is not None else None
        head = f"{file} · {symbol}" if symbol else file
        prop = str(getattr(entry, "property", "") or "")
        why = str(getattr(entry, "why", "") or "")
        chunk = [head]
        if prop:
            chunk.append(f"  Propriedade: {prop}")
        if why:
            chunk.append(f"  Por que: {why}")
        parts.append("\n".join(chunk))
    return "\n".join(parts)
