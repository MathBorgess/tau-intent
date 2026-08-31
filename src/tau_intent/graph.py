"""Static Python graph extraction for projection (PR slice #5)."""

from __future__ import annotations

from dataclasses import dataclass
import ast
from pathlib import Path
from typing import Iterable


_GRAPH_CACHE: dict[tuple[str, str], "IntentGraph"] = {}


@dataclass(frozen=True)
class GraphEdge:
    source: str
    destination: str
    kind: str


class IntentGraph:
    """Graph with typed edges and optional hub pruning for traversal."""

    def __init__(self, edges: Iterable[GraphEdge]):
        self.edges = list(edges)
        self.nodes: set[str] = set()
        self._adjacency: dict[str, set[str]] = {}
        for edge in self.edges:
            self.nodes.add(edge.source)
            self.nodes.add(edge.destination)
            self._adjacency.setdefault(edge.source, set()).add(edge.destination)
            self._adjacency.setdefault(edge.destination, set()).add(edge.source)
        for node in self.nodes:
            self._adjacency.setdefault(node, set())

    def degree(self, node: str) -> int:
        return len(self._adjacency.get(node, ()))

    def mean_degree(self) -> float:
        if not self.nodes:
            return 0.0
        return sum(self.degree(node) for node in self.nodes) / float(len(self.nodes))

    def hub_nodes(self, lambda_factor: float) -> set[str]:
        mean = self.mean_degree()
        if mean <= 0:
            return set()
        threshold = lambda_factor * mean
        return {node for node in self.nodes if self.degree(node) > threshold}

    def one_hop(
        self,
        seeds: Iterable[str],
        *,
        prune_hubs: bool = True,
        lambda_factor: float = 2.0,
    ) -> set[str]:
        del prune_hubs, lambda_factor
        seed_list = tuple(seeds)
        selected = set(seed_list)
        for seed in seed_list:
            selected.update(self._adjacency.get(seed, ()))
        return selected

    def expand(
        self,
        seeds: Iterable[str],
        *,
        hops: int,
        prune_hubs: bool = True,
        lambda_factor: float = 2.0,
    ) -> set[str]:
        hubs = self.hub_nodes(lambda_factor) if prune_hubs else set()
        seed_set = set(seeds)
        visited = set(seed_set)
        frontier = set(seed_set)
        for _ in range(max(0, hops)):
            next_frontier: set[str] = set()
            for node in frontier:
                if node in hubs:
                    continue
                for neighbor in self._adjacency.get(node, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        return visited


class _GraphBuilder(ast.NodeVisitor):
    def __init__(self, module_node: str):
        self.module_node = module_node
        self.scope: list[str] = []
        self.edges: list[GraphEdge] = []

    def _current_scope(self) -> str:
        if not self.scope:
            return self.module_node
        return f"{self.module_node}::" + ".".join(self.scope)

    def _add_contains(self, name: str) -> None:
        self.edges.append(GraphEdge(source=self._current_scope(), destination=name, kind="contains"))

    def _qualified_symbol(self, name: str) -> str:
        if not self.scope:
            return f"{self.module_node}::{name}"
        return f"{self.module_node}::" + ".".join([*self.scope, name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_node = self._qualified_symbol(node.name)
        self._add_contains(class_node)
        for base in node.bases:
            base_name = _dotted_name(base)
            if base_name:
                self.edges.append(
                    GraphEdge(source=class_node, destination=base_name, kind="inherits")
                )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        fn_node = self._qualified_symbol(node.name)
        self._add_contains(fn_node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edges.append(
                GraphEdge(source=self._current_scope(), destination=alias.name, kind="imports")
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.edges.append(
                GraphEdge(source=self._current_scope(), destination=node.module, kind="imports")
            )

    def visit_Call(self, node: ast.Call) -> None:
        target = _dotted_name(node.func)
        if target:
            self.edges.append(
                GraphEdge(source=self._current_scope(), destination=target, kind="invokes")
            )
        self.generic_visit(node)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        root = _dotted_name(node.value)
        return f"{root}.{node.attr}" if root else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return None


def build_graph(root: str | Path, *, cache_key: str | None = None) -> IntentGraph:
    base = Path(root).resolve()
    if cache_key is not None:
        cache_id = (str(base), cache_key)
        cached = _GRAPH_CACHE.get(cache_id)
        if cached is not None:
            return cached
    edges: list[GraphEdge] = []
    for py_file in sorted(base.rglob("*.py")):
        rel = py_file.relative_to(base).as_posix()
        module_node = rel
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        builder = _GraphBuilder(module_node=module_node)
        builder.visit(tree)
        edges.extend(builder.edges)
    graph = IntentGraph(edges)
    if cache_key is not None:
        _GRAPH_CACHE[(str(base), cache_key)] = graph
    return graph
