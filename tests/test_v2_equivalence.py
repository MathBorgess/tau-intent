import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from tests.test_integration_bench import _semear,_rodar
from tau_intent.collect import Region,Pending
from tau_intent.config import load_gate_config,config_hashes
from tau_intent.gate import portao

class CodeEquivalence(unittest.TestCase):
    def test_code_adapter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('tau_intent.adapters'))

    def test_v1_1_golden_normal_case(self):
        expected=json.loads((Path(__file__).parent/'fixtures/v1_1_code.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=_semear(Path(tmp)); result=_rodar(root,'B')
            rows=[json.loads(x) for x in (root/'intents.jsonl').read_text().splitlines()]
        for row in rows: row.pop('id'); row.pop('ts')
        self.assertEqual(result.bloco,expected['bloco'])
        self.assertEqual(rows,expected['entries'])
        r=Region('src/mod.py',1,2,symbol='f',edited_lines=2)
        v=portao([r],{r.key():Pending(r,why='w',domain='d',symbol='f')},{'src/mod.py::f'},load_gate_config(),0)
        self.assertEqual({'tipo':v.tipo,'falhas':list(v.falhas)},expected['veredito'])
        self.assertFalse(v.nao_avaliaveis)
        self.assertEqual(config_hashes(),expected['config_sha256'])

    def test_moved_routines_are_byte_identical_to_wave_one(self):
        import inspect,hashlib
        from tau_intent.adapters import code
        from tau_intent import neighbourhood
        expected=json.loads((Path(__file__).parent/'fixtures/moved_source_hashes.json').read_text())
        for name,digest in expected.items():
            module=neighbourhood if name in ('Graph','marcar_onipresentes') else code
            self.assertEqual(hashlib.sha256(inspect.getsource(getattr(module,name)).encode()).hexdigest(),digest,name)
