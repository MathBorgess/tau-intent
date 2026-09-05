"""Deterministic typed neighbourhood, independent of the effect substrate."""
from __future__ import annotations
from collections import defaultdict
EDGE_TYPES = ("contains", "imports", "invokes", "inherits", "depends_on")

class Graph:
    """Minimal multi-digraph. Avoids a networkx dependency in v1."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self._out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._in: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._degree: dict[str, int] = defaultdict(int)

    def add_node(self, node_id: str, **attrs: object) -> None:
        self.nodes.setdefault(node_id, {}).update(attrs)

    def add_edge(self, src: str, dst: str, key: str) -> None:
        self.add_node(src)
        self.add_node(dst)
        self._out[src].append((dst, key))
        self._in[dst].append((src, key))
        self._degree[src] += 1
        self._degree[dst] += 1

    def degree(self, node_id: str) -> int:
        return int(self._degree.get(node_id, 0))

    def neighbors(
        self, node_id: str, edge_types: tuple[str, ...] | None = None
    ) -> list[tuple[str, str, str]]:
        """Return (other, edge_type, direction) with direction in {saida, entrada}."""
        allowed = set(edge_types or EDGE_TYPES)
        out = [
            (dst, key, "saida")
            for dst, key in self._out.get(node_id, [])
            if key in allowed
        ]
        incoming = [
            (src, key, "entrada")
            for src, key in self._in.get(node_id, [])
            if key in allowed
        ]
        return out + incoming


def marcar_onipresentes(graph: Graph, lam: float = 3.0) -> set[str]:
    """Nodes whose degree exceeds lam × mean degree are destinations, not bridges."""
    if not graph.nodes:
        return set()
    graus = [graph.degree(node_id) for node_id in graph.nodes]
    media = sum(graus) / max(len(graus), 1)
    return {node_id for node_id in graph.nodes if graph.degree(node_id) > lam * media}

