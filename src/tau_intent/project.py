"""Dumb 1-hop projector. YAML is read, not fitted. llm_rescue stays off."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tau_intent.graph import Graph, marcar_onipresentes

try:
    from tau_intent.telemetry import TOKENIZER, count_tokens
except ImportError:
    TOKENIZER = "whitespace-v1"

    def count_tokens(text: str) -> int:
        return len(text.split()) if text and text.strip() else 0

DEFAULTS_PATH = Path(__file__).with_name("projection.yaml")
FALLBACK_PATH = Path(__file__).parent / "defaults" / "project_v1.yaml"
DEFAULTS = {
    "k": 1,
    "prune_hubs": True,
    "llm_rescue": False,
    "gamma": 0.1,
    "max_nodes": 200,
    "lambda_grau": 3.0,
}


@dataclass(frozen=True)
class ProjectConfig:
    gamma: float = 0.1
    max_nodes: int = 200
    lambda_grau: float = 3.0
    prune_hubs: bool = True
    llm_rescue: bool = False
    up_depth: int = 1
    down_depth: int = 1
    token_budget: int = 1500
    edge_types: tuple[str, ...] = ("contains", "imports", "invokes", "inherits")


def load_project_config(path: Path | None = None) -> ProjectConfig:
    chosen = Path(path) if path is not None else DEFAULTS_PATH
    if not chosen.exists() and FALLBACK_PATH.exists():
        chosen = FALLBACK_PATH
    raw = _load_yaml(chosen)
    lam = raw.get("lambda_grau", raw.get("hub_lambda", raw.get("lambda", 3.0)))
    return ProjectConfig(
        gamma=float(raw.get("gamma", 0.1)),
        max_nodes=int(raw.get("max_nodes", 200)),
        lambda_grau=float(lam),
        prune_hubs=_as_bool(raw.get("prune_hubs", True)),
        llm_rescue=_as_bool(raw.get("llm_rescue", False)),
        up_depth=int(raw.get("up_depth", raw.get("k", 1))),
        down_depth=int(raw.get("down_depth", raw.get("k", 1))),
        token_budget=int(raw.get("token_budget", 1500)),
    )


load_projection_config = load_project_config


def projetar(
    graph: Graph,
    entries: Sequence[Any],
    ancoras: Sequence[str],
    cfg: ProjectConfig,
    orcamento_token: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Project current intents around task anchors.

    llm_rescue is never invoked in v1 even if the YAML bit is true.
    """
    budget = cfg.token_budget if orcamento_token is None else orcamento_token
    hubs = marcar_onipresentes(graph, cfg.lambda_grau) if cfg.prune_hubs else set()
    alcancados = expandir(
        graph,
        ancoras,
        cfg.edge_types,
        cfg.up_depth,
        cfg.down_depth,
        cfg.max_nodes,
        hubs,
    )
    scored = []
    for entry in entries:
        node = _node_id(entry)
        if node not in alcancados:
            continue
        why = str(getattr(entry, "why", "") or "")
        prop = str(getattr(entry, "property", "") or "")
        if not (why or prop):
            continue
        h = alcancados[node]
        recency = _recencia(entry, entries)
        tipo = 1.0 if prop else 0.7
        peso = (cfg.gamma**h) * recency * tipo
        scored.append((peso, entry))

    scored.sort(key=lambda item: -item[0])
    escolhidas: list[Any] = []
    cortadas: list[Any] = []
    for peso, entry in scored:
        candidate = list(escolhidas) + [entry]
        tokens = count_tokens(render_block(candidate, []))
        if tokens <= budget:
            escolhidas.append(entry)
        else:
            cortadas.append(entry)

    # v1: llm_rescue off. Do not call a model even if the YAML bit is true.
    bloco = render_block(escolhidas, cortadas)
    tel = {
        "tokenizer": TOKENIZER,
        "tokens_served": count_tokens(bloco),
        "n_escolhidas": len(escolhidas),
        "n_cortadas": len(cortadas),
        "n_alcancados": len(alcancados),
        "llm_rescue": False,
    }
    return bloco, tel


def expandir(
    graph: Graph,
    ancoras: Iterable[str],
    edge_types: Sequence[str],
    up_depth: int,
    down_depth: int,
    max_nodes: int,
    hubs: set[str],
) -> dict[str, int]:
    alcancados: dict[str, int] = {a: 0 for a in ancoras if a}
    fila: deque[tuple[str, int]] = deque((a, 0) for a in alcancados)
    types = tuple(edge_types)
    while fila and len(alcancados) < max_nodes:
        v, h = fila.popleft()
        if h >= max(up_depth, down_depth):
            continue
        for w, _key, direcao in graph.neighbors(v, types):
            limite = up_depth if direcao == "entrada" else down_depth
            if h >= limite or w in alcancados:
                continue
            alcancados[w] = h + 1
            if w in hubs:
                continue
            fila.append((w, h + 1))
    return alcancados


def render_entry(entry: Any) -> str:
    anchor = getattr(entry, "anchor", None)
    file = getattr(anchor, "file", "") if anchor is not None else ""
    symbol = getattr(anchor, "symbol", None) if anchor is not None else None
    head = f"{file} · {symbol}" if symbol else file
    prop = str(getattr(entry, "property", "") or "")
    why = str(getattr(entry, "why", "") or "")
    lines = [head]
    if prop:
        lines.append(f"  Propriedade: {prop}")
    if why:
        lines.append(f"  Por que: {why}")
    return "\n".join(lines)


def render_block(escolhidas: Sequence[Any], cortadas: Sequence[Any]) -> str:
    if not escolhidas:
        return ""
    body = "\n".join(render_entry(e) for e in escolhidas)
    return (
        "── Intenção registrada nas regiões que esta tarefa toca ──\n\n"
        f"{body}\n\n"
        f"({len(escolhidas)} entradas · {len(cortadas)} cortadas por orçamento)"
    )


def render_tudo(entries: Sequence[Any]) -> str:
    return "\n".join(render_entry(e) for e in entries)


def _node_id(entry: Any) -> str:
    anchor = getattr(entry, "anchor", None)
    if anchor is not None and hasattr(anchor, "node_id"):
        return str(anchor.node_id())
    return str(getattr(anchor, "file", "") or "")


def _recencia(entry: Any, entries: Sequence[Any]) -> float:
    ts = str(getattr(entry, "ts", "") or "")
    file = getattr(getattr(entry, "anchor", None), "file", "")
    newer = sum(
        1
        for other in entries
        if getattr(getattr(other, "anchor", None), "file", "") == file
        and str(getattr(other, "ts", "") or "") > ts
    )
    return 1.0 / (1.0 + newer)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Tiny YAML subset: ``key: value`` scalars. Not a general parser."""
    data: dict[str, Any] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.endswith(":") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
            continue
        try:
            data[key] = int(value) if "." not in value else float(value)
        except ValueError:
            data[key] = value
    return data
