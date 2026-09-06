import unittest
from tau_intent.graph import Graph
from tau_intent.model import IntentEntry,Anchor
from tau_intent.project import projetar,ProjectConfig
from tau_intent.telemetry import count_tokens

class RescueGuards(unittest.TestCase):
    def test_rescue_cannot_lose_anchors_or_exceed_budget(self):
        e=IntentEntry('id','ts','t',Anchor('a.py','f',1,2,'hash'),'why','property','domain')
        g=Graph();g.add_node('a.py::f')
        for rewrite in ('lost everything','a.py::f\nPropriedade: property\nPor que: why\n'+'extra '*1000):
            block,tel=projetar(g,[e],['a.py::f'],ProjectConfig(llm_rescue=True,token_budget=100),summarizer_fn=lambda *args:rewrite)
            self.assertLessEqual(count_tokens(block),100)
            self.assertIn('a.py::f',block)
            self.assertTrue(tel['llm_rescue_falhou'])
            self.assertFalse(tel['llm_rescue_aplicado'])
