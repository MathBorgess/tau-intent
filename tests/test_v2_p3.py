import unittest
from tau_intent.rescue import recall_de_simbolo

class Recall(unittest.TestCase):
    def test_empty_origin_is_unknown(self):
        r=recall_de_simbolo('nothing','a.go::f')
        self.assertIsNone(r['razao'])
        self.assertEqual(r['ancoras_no_bloco'],0)
        self.assertEqual(r['antes'],0)

    def test_anchor_recognition_is_not_extension_specific(self):
        r=recall_de_simbolo('a.go::f b.rs::g','a.go::f')
        self.assertEqual(r['razao'],.5)
        self.assertEqual(r['antes'],2)
