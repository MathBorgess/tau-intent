"""Pure gate checks for synthetic edit blocks."""

import re

GENERICA_RE = re.compile(r"\b(?:melhora|corrige|refatora|ajusta|atualiza)\b", re.IGNORECASE)


def _extract_identifiers(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))


def evaluate_gate(
    blocks: list[dict],
    symbols: set[str],
    blocked_count: int,
    n_max: int,
    large_edit_threshold: int = 12,
) -> dict:
    failures: list[dict] = []

    for index, block in enumerate(blocks):
        pending_assertion = bool(block.get("pending_assertion"))
        why = str(block.get("why", ""))
        prop = str(block.get("property", ""))
        size = int(block.get("size", 0))

        if not pending_assertion:
            failures.append({"code": "AUSENTE", "index": index, "path": block.get("path")})
            continue
        if GENERICA_RE.search(why):
            failures.append({"code": "GENERICA", "index": index, "path": block.get("path")})

        if prop.strip():
            cited_symbols = _extract_identifiers(prop)
            if cited_symbols and not any(symbol in symbols for symbol in cited_symbols):
                failures.append(
                    {"code": "PROPERTY_SEM_SIMBOLO", "index": index, "path": block.get("path")}
                )

        if size > large_edit_threshold and not prop.strip():
            failures.append(
                {"code": "EDICAO_GRANDE_SEM_PROPERTY", "index": index, "path": block.get("path")}
            )

    if not failures:
        verdict = "PASSA"
    elif blocked_count >= n_max:
        verdict = "ESCALAR"
    else:
        verdict = "BLOQUEIA"

    return {"verdict": verdict, "failures": failures}
