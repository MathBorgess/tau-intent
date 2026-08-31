"""v1 dumb projector: one hop, optional hub pruning, no LLM rescue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .graph import IntentGraph


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "defaults" / "project_v1.yaml"


@dataclass(frozen=True)
class ProjectionConfig:
    k: int = 1
    prune_hubs: bool = True
    llm_rescue: bool = False
    gamma: float = 0.1
    max_nodes: int = 12
    hub_lambda: float = 2.0


def whitespace_tokenize(text: str) -> list[str]:
    """Declared trivial tokenizer for v1 token accounting."""
    return text.split()


def count_tokens(text: str, tokenizer: Callable[[str], Iterable[str]] = whitespace_tokenize) -> int:
    return sum(1 for _ in tokenizer(text))


def load_projection_config(path: str | Path | None = None) -> ProjectionConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    values = _read_simple_yaml(config_path)
    return ProjectionConfig(
        k=int(values.get("k", 1)),
        prune_hubs=bool(values.get("prune_hubs", True)),
        llm_rescue=bool(values.get("llm_rescue", False)),
        gamma=float(values.get("gamma", 0.1)),
        max_nodes=int(values.get("max_nodes", 12)),
        hub_lambda=float(values.get("hub_lambda", 2.0)),
    )


def project_intents(
    intents: list[dict],
    *,
    seed_nodes: Iterable[str] = (),
    graph: IntentGraph | None = None,
    max_nodes: int | None = None,
    config_path: str | Path | None = None,
) -> list[dict]:
    config = load_projection_config(config_path)
    budget = config.max_nodes if max_nodes is None else max_nodes
    seeds = tuple(seed_nodes)

    if graph is not None and seeds:
        reachable = graph.expand(
            seeds,
            hops=config.k,
            prune_hubs=config.prune_hubs,
            lambda_factor=config.hub_lambda,
        )
    else:
        reachable = set()

    indexed_scores: list[tuple[float, int, dict]] = []
    total = len(intents)
    for index, intent in enumerate(intents):
        age = max(0, total - 1 - index)
        recency = (1.0 - config.gamma) ** age
        anchors = set(intent.get("anchors", ()))
        matched = bool(reachable) and bool(anchors & reachable)
        score = recency + (1.0 if matched else 0.0)
        indexed_scores.append((score, index, intent))

    indexed_scores.sort(key=lambda item: (item[0], item[1]), reverse=True)
    limited = indexed_scores[: max(0, budget)]
    selected = [item[2] for item in sorted(limited, key=lambda item: item[1])]
    return selected


def render_intents(intents: Iterable[dict]) -> str:
    return "\n".join(str(intent.get("text", "")) for intent in intents)


def served_token_count_full(intents: list[dict]) -> int:
    return count_tokens(render_intents(intents))


def served_token_count_projected(
    intents: list[dict],
    *,
    seed_nodes: Iterable[str] = (),
    graph: IntentGraph | None = None,
    max_nodes: int | None = None,
    config_path: str | Path | None = None,
) -> int:
    projected = project_intents(
        intents,
        seed_nodes=seed_nodes,
        graph=graph,
        max_nodes=max_nodes,
        config_path=config_path,
    )
    return served_token_count_full(projected)


def _read_simple_yaml(path: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, raw_value = line.partition(":")
        if not _:
            continue
        key = key.strip()
        value_text = raw_value.strip()
        if value_text.lower() in {"true", "false"}:
            values[key] = value_text.lower() == "true"
            continue
        try:
            if "." in value_text:
                values[key] = float(value_text)
            else:
                values[key] = int(value_text)
        except ValueError:
            values[key] = value_text
    return values
