import unittest
from tau_intent.collect import Region
from tau_intent.telemetry import cobertura_de_captura, aproveitamento_do_bloco


class CoverageDenominators(unittest.TestCase):
    def test_mixed_granularity_is_not_pooled(self):
        a=Region('a.py',1,2,symbol='f')
        b=Region('a.py',3,4,symbol='g')
        c=Region('a.go',1,2);c.resolver=None
        result=cobertura_de_captura([a,b,c],[a,c])
        self.assertIsInstance(result,dict)
        self.assertEqual(result['estrita'],.5)
        self.assertEqual(result['por_arquivo'],1)
        self.assertEqual(result['denominadores']['estrita'],2)
        self.assertEqual(result['fracao_resolvida'],2/3)

    def test_absent_witness_and_empty_population(self):
        r=Region('a.go',1,2);r.resolver=None
        for rs in ([],[r]):
            result=cobertura_de_captura(rs,[r])
            self.assertIsInstance(result,dict)
            self.assertIsNone(result['estrita'])
            self.assertEqual(result['denominadores']['estrita'],0)
        self.assertIsNone(aproveitamento_do_bloco([])['razao'])
