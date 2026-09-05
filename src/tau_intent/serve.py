"""Read-only generic retrieval: one budgeted neighbourhood projection per result.

Queries name known anchor IDs literally. A caller may supply a deterministic
query-to-anchor mapper; no model, embedding or benchmark dependency is implied.
"""
from __future__ import annotations
from dataclasses import replace
from tau_intent.project import load_project_config, projetar
from tau_intent.store import IntentStore
from tau_intent.telemetry import count_tokens


class IntentRetrieval:
    def __init__(self, store, adapter, workspace, cfg=None, query_anchors=None):
        self.store = store
        self.adapter = adapter
        self.workspace = workspace
        self.cfg = cfg or load_project_config()
        if self.cfg.llm_rescue:
            raise ValueError('read-only retrieval requires deterministic projection')
        self.query_anchors = query_anchors
        self.telemetry = {}

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        if type(query) is not str or type(top_k) is not int or top_k < 0:
            raise ValueError('query must be str and top_k a non-negative integer')
        # Re-read the append-only log so a predecessor's append/supersession
        # is visible even when this service object predates the handoff.
        store = IntentStore(self.store.path)
        current = store.current()
        graph = self.adapter.neighbourhood(self.workspace)
        known = set(graph.nodes) | {e.anchor.node_id() for e in current}
        if self.query_anchors is not None:
            anchors = list(dict.fromkeys(self.query_anchors(query)))
        else:
            tokens = {t.strip(" ,;()[]'\"`") for t in query.split()}
            anchors = sorted(known & tokens)
        remaining = self.cfg.token_budget
        results, receipts, served = [], [], set()
        visited = 0
        for anchor in anchors:
            if len(results) >= top_k or remaining <= 0:
                break
            visited += 1
            block, tel = projetar(
                graph, [e for e in current if e.id not in served], [anchor],
                replace(self.cfg, edge_types=self.adapter.edge_types), remaining,
                superadas=len(store._entries)-len(current))
            receipts.append(tel['recibo'])
            if not tel['servidas']:
                continue
            served.update(e.id for e in tel['servidas'])
            results.append(block)
            remaining -= count_tokens(block)
        self.telemetry = {
            'recibos': receipts, 'tokens_served': self.cfg.token_budget-remaining,
            'servidas': [{'id': eid, 'status': 'current'} for eid in sorted(served)],
            'alvos_nao_consultados': anchors[visited:], 'top_k': top_k,
        }
        return results
