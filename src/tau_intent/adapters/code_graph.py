"""Typed AST graph. No user code is executed.

The cache key includes the **state of the tree**, not only the commit SHA
(P-6 / D11). Within one session the interesting pair is pre-edit and post-edit
at the same SHA — and the post-edit tree is precisely where the gate's symbol
table comes from, so a cache that cannot tell them apart returns the symbols of
the file as it was before the agent wrote it.
"""

from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from pathlib import Path

from tau_intent.neighbourhood import Graph, marcar_onipresentes

EDGE_TYPES = ("contains", "imports", "invokes", "inherits")




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


def estado_da_arvore(root: str | Path) -> str:
    """Digest of the working tree as it is on disk right now.

    Content-based, not mtime-based: mtime granularity loses edits that land in
    the same clock tick, which is exactly the pre/post-edit pair we need to
    distinguish. Cost is one read per .py file, the same files ``build`` is
    about to parse anyway.
    """
    root = Path(root)
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _build_cached(root: str, commit_sha: str, tree_state: str) -> Graph:
    del commit_sha, tree_state  # part of the key, not of the build
    return build(Path(root))


def build_cached(root: str, commit_sha: str, tree_state: str | None = None) -> Graph:
    """Cached build. ``tree_state`` defaults to the digest of the tree on disk."""
    state = estado_da_arvore(root) if tree_state is None else tree_state
    return _build_cached(str(Path(root)), commit_sha, state)


def build_graph(
    root: str | Path,
    *,
    cache_key: str | None = None,
    tree_state: str | None = None,
) -> Graph:
    if cache_key is not None:
        return build_cached(str(Path(root)), cache_key, tree_state)
    return build(Path(root))


def cache_info():
    """Hits/misses of the graph cache. The build cost the P-6 wants measured."""
    return _build_cached.cache_info()




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

