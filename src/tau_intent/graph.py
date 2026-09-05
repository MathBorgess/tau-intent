"""Compatibility surface; code graph construction is loaded only on demand."""
from tau_intent.neighbourhood import Graph, marcar_onipresentes, EDGE_TYPES


def __getattr__(name):
    from tau_intent.adapters import code_graph
    return getattr(code_graph, name)
