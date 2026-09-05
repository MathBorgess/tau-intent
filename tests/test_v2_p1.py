import tempfile
import unittest
from pathlib import Path
from tau_intent.collect import Region, Pending, resolver_simbolos
from tau_intent.config import load_gate_config
from tau_intent.gate import portao


class ResolverPremises(unittest.TestCase):
    def test_no_resolver_never_blocks_fine_checks_even_at_block_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'a.go').write_text('package main\n')
            rs=resolver_simbolos([Region('a.go',i*30+1,i*30+20,edited_lines=20) for i in range(6)],tmp)
        ps={r.key():Pending(r,why='w',domain='d',symbol='invented') for r in rs}
        v=portao(rs,ps,set(),load_gate_config(),3)
        self.assertEqual(v.tipo,'PASSA')
        self.assertEqual(len(v.nao_avaliaveis),12)
        self.assertFalse(v.falhas)
        self.assertTrue(all(r.resolver is None for r in rs))

    def test_missing_intent_still_blocks_without_resolver(self):
        r=Region('a.go',1,60,edited_lines=60)
        r.resolver=None
        v=portao([r],{},set(),load_gate_config(),0)
        self.assertEqual([f.code for f in v.falhas],['AUSENTE'])
        self.assertEqual(len(v.nao_avaliaveis),2)

    def test_available_but_incomplete_table_still_blocks(self):
        r=Region('a.py',1,60,edited_lines=60,symbol='real')
        p=Pending(r,why='w',domain='d',symbol='real')
        v=portao([r],{r.key():p},set(),load_gate_config(),0)
        self.assertEqual(len(v.falhas),2)
        self.assertFalse(v.nao_avaliaveis)
