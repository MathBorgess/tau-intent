import tempfile
import textwrap
import unittest
from pathlib import Path

from tau_intent.graph import build_graph
from tau_intent.project import (
    load_projection_config,
    served_token_count_full,
    served_token_count_projected,
    whitespace_tokenize,
)


class TestProjectionV1(unittest.TestCase):
    def test_graph_extracts_edge_kinds_and_supports_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text(
                textwrap.dedent(
                    """
                    import os
                    from math import sqrt

                    class Base:
                        pass

                    class Child(Base):
                        def run(self):
                            return sqrt(4)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            g1 = build_graph(root, cache_key="abc123")
            g2 = build_graph(root, cache_key="abc123")

        kinds = {edge.kind for edge in g1.edges}
        self.assertTrue({"contains", "imports", "invokes", "inherits"}.issubset(kinds))
        self.assertIs(g1, g2)

    def test_v4_projection_is_smaller_than_full_store_and_budget_monotonic(self):
        config = load_projection_config()
        self.assertEqual(config.k, 1)
        self.assertTrue(config.prune_hubs)
        self.assertFalse(config.llm_rescue)
        self.assertEqual(config.gamma, 0.1)

        intents: list[dict] = []
        for i in range(1, 9):
            intents.append(
                {
                    "id": f"i{i}",
                    "anchors": [f"anchor_{i}"],
                    "text": f"intent {i} carries several words for token counting",
                }
            )
            full_tokens = served_token_count_full(intents)
            projected_tokens = served_token_count_projected(
                intents, max_nodes=config.max_nodes, seed_nodes=[f"anchor_{i}"]
            )
            if len(intents) > config.max_nodes:
                self.assertLess(projected_tokens, full_tokens)

        current_store = intents[:]
        budgets = [min(config.max_nodes, len(current_store)), 4, 3, 2, 1]
        token_counts = [
            served_token_count_projected(current_store, max_nodes=budget, seed_nodes=["anchor_8"])
            for budget in budgets
        ]
        self.assertEqual(token_counts, sorted(token_counts, reverse=True))
        self.assertEqual(whitespace_tokenize("a b   c"), ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
