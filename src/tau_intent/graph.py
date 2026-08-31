"""Typed AST graph. No user code is executed."""

from __future__ import annotations

import ast
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

EDGE_TYPES = ("contains", "imports", "invokes", "inherits")


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


def build(root: Path) -> Graph:
    root = Path(root)
    graph = Graph()
    files = [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]
    file_ids = {str(path.relative_to(root)) for path in files}
    for path in files:
        fid = str(path.relative_to(root))
        graph.add_node(fid, kind="file")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alvo in _resolve_import(node, fid, file_ids):
                    graph.add_edge(fid, alvo, key="imports")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sid = f"{fid}::{node.name}"
                graph.add_node(sid, kind=type(node).__name__, lineno=node.lineno)
                graph.add_edge(fid, sid, key="contains")
                for base in getattr(node, "bases", []):
                    graph.add_edge(sid, _name(base), key="inherits")
                for chamada in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                    graph.add_edge(sid, _name(chamada.func), key="invokes")
    return graph


@lru_cache(maxsize=8)
def build_cached(root: str, commit_sha: str) -> Graph:
    del commit_sha
    return build(Path(root))


def build_graph(root: str | Path, *, cache_key: str | None = None) -> Graph:
    if cache_key is not None:
        return build_cached(str(Path(root)), cache_key)
    return build(Path(root))


def marcar_onipresentes(graph: Graph, lam: float = 3.0) -> set[str]:
    """Nodes whose degree exceeds lam × mean degree are destinations, not bridges."""
    if not graph.nodes:
        return set()
    graus = [graph.degree(node_id) for node_id in graph.nodes]
    media = sum(graus) / max(len(graus), 1)
    return {node_id for node_id in graph.nodes if graph.degree(node_id) > lam * media}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return type(node).__name__


def _resolve_import(node: ast.AST, fid: str, file_ids: set[str]) -> list[str]:
    targets: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            targets.extend(_match_module(alias.name, file_ids))
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level:
            parts = Path(fid).parts[:-1]
            climb = max(node.level - 1, 0)
            if climb:
                parts = parts[:-climb] if climb <= len(parts) else ()
            prefix = ".".join(parts)
            module = f"{prefix}.{module}".strip(".") if module else prefix
        targets.extend(_match_module(module, file_ids))
        for alias in node.names:
            targets.extend(_match_module(f"{module}.{alias.name}" if module else alias.name, file_ids))
    return targets


def _match_module(module: str, file_ids: set[str]) -> list[str]:
    if not module:
        return []
    as_path = module.replace(".", "/") + ".py"
    as_pkg = module.replace(".", "/") + "/__init__.py"
    found = [candidate for candidate in (as_path, as_pkg) if candidate in file_ids]
    return found
