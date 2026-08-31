"""Render helpers for gate failures."""

from __future__ import annotations


def render_falhas(falhas: list[dict[str, str]]) -> str:
    """Render gate failures as a short follow_up message."""
    if not falhas:
        return "Gate bloqueou sem detalhes."
    lines = ["Gate BLOQUEIA. Corrija:"]
    for falha in falhas:
        code = falha.get("code", "FALHA")
        message = falha.get("message", "")
        lines.append(f"- {code}: {message}".rstrip())
    return "\n".join(lines)
