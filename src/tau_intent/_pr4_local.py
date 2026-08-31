"""Compatibility shims for Copilot extra files on PR slice 4."""

from __future__ import annotations

from tau_intent.cli import flags_from_args, main, parse_args
from tau_intent.supervisor import BLOQUEIA, LIBERA, PERMITE, run_task as run_supervisor

__all__ = [
    "BLOQUEIA",
    "LIBERA",
    "PERMITE",
    "flags_from_args",
    "main",
    "parse_args",
    "run_supervisor",
]
