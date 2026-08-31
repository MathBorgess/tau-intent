"""PR4-only local fallbacks for integration tests when PR2/PR3 modules are absent."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


ALLOW = "PERMITE"
BLOCK = "BLOQUEIA"


def collect_intent_from_git_diff(repo_path: str, *, why: str = "change", property_name: str = "property") -> dict[str, Any] | None:
    """Build a minimal intent payload using changed files from git diff."""
    output = subprocess.check_output(
        ["git", "-C", repo_path, "diff", "--name-only"],
        text=True,
    )
    anchors = [line.strip() for line in output.splitlines() if line.strip()]
    if not anchors:
        return None
    return {
        "why": why,
        "property": property_name,
        "anchors": anchors,
    }


def gate_eval(intent: dict[str, Any] | None) -> dict[str, Any]:
    """Pure local gate fallback: block if why/property missing."""
    failures: list[dict[str, str]] = []
    if intent is None:
        failures.append({"code": "AUSENTE", "message": "intent ausente"})
    else:
        if not intent.get("why"):
            failures.append({"code": "GENERICA", "message": "why ausente"})
        if not intent.get("property"):
            failures.append({"code": "PROPERTY_SEM_SIMBOLO", "message": "property ausente"})
    return {"code": BLOCK if failures else ALLOW, "failures": failures}


def append_intent_jsonl(intents_path: str, intent: dict[str, Any]) -> None:
    """Append one intent record to a JSONL file."""
    path = Path(intents_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(intent, ensure_ascii=False) + "\n")
