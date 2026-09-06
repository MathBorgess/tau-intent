import asyncio,json,tempfile,unittest
from pathlib import Path
from tau_intent.collect import Region
from tau_intent.fake_provider import FakeHarness,FakeToolStart,FakeTurnEnd
from tau_intent.supervisor import run_task,Flags
from tau_intent.manifest import manifest_da_execucao
from tau_intent.config import config_hashes

class ManifestEvidence(unittest.TestCase):
    def run_go(self,root,**kwargs):
        rs=[Region('a.go',i*30+1,i*30+20,edited_lines=20) for i in range(6)]
        script=[[FakeToolStart(tool_name='record_intent',args={'file':'a.go','why':'w','domain':'d'}),FakeTurnEnd()]]
        return asyncio.run(run_task(root,Flags(True,True,True,True),diff=rs,harness=FakeHarness(script),**kwargs))

    def test_go_declares_exclusion_and_null_effective_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.go').write_text('package main\n')
            result=self.run_go(root)
        self.assertEqual(result.verdict,'PASSA')
        self.assertIsNone(result.telemetry['cobertura_efetiva'])
        m=manifest_da_execucao(result.flags,result.telemetry)['execucao']
        self.assertEqual(m['alvos_excluidos'],['a.go'])
        self.assertTrue(m['codigos_nao_avaliaveis'])
        self.assertIsNone(m['cobertura_por_linguagem']['go']['estrita'])

    def test_undeclared_exclusion_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(AssertionError,'resolver'):
                self.run_go(Path(tmp),alvos_excluidos=[])

    def test_refactor_cannot_change_config_hashes(self):
        expected=json.loads((Path(__file__).parent/'fixtures/v1_1_code.json').read_text())
        self.assertEqual(config_hashes(),expected['config_sha256'])
