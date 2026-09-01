"""Compatibility re-export. The V1 graph lives in graph.py."""

from tau_intent.graph import Graph, build, build_graph

__all__ = ["Graph", "GraphBuilder", "build_graph"]


class GraphBuilder:
    def build(self, root):
        return build(root)
