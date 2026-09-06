import unittest
from tau_intent.graph import Graph
from tau_intent.project import projetar, ProjectConfig
from tau_intent.telemetry import count_tokens

class NeighbourhoodReceipt(unittest.TestCase):
    def test_empty_graph_is_not_complete_neighbourhood(self):
        block,tel=projetar(Graph(),[],['a.go'],ProjectConfig())
        self.assertIn('vizinhança indisponível',block)
        self.assertFalse(tel['recibo']['grafo_disponivel'])
        self.assertLessEqual(count_tokens(block),1500)

    def test_degraded_receipt_obeys_small_budget(self):
        block,tel=projetar(Graph(),[],['a.go'],ProjectConfig(token_budget=1))
        self.assertEqual(block,'')
        self.assertTrue(tel['bloco_suprimido_por_orcamento'])
        self.assertFalse(tel['recibo']['grafo_disponivel'])
