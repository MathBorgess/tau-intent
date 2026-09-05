"""Compatibility surface; code graph construction is loaded only on demand."""
from tau_intent.neighbourhood import Graph, marcar_onipresentes, EDGE_TYPES


def __getattr__(name):
    if name not in {"build", "estado_da_arvore", "build_cached", "build_graph", "cache_info", "_build_cached"}:
        raise AttributeError(name)
    from tau_intent.adapters import code_graph
    return getattr(code_graph, name)
