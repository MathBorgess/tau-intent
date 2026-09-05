import tempfile,asyncio,unittest
from pathlib import Path
from tau_intent.manifest import manifest,manifest_da_execucao
from tau_intent.supervisor import run_task,Flags
from tau_intent.fake_provider import FakeHarness,FakeTurnEnd

class ModelPairs(unittest.TestCase):
    def test_always_stamped_even_equal(self):
        m=manifest()
        self.assertIn('modelo_produtor',m)
        self.assertIn('modelo_consumidor',m)

    def test_run_stamps_distinct_pair_and_actual_served_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=asyncio.run(run_task(Path(tmp),Flags(False,False,False,False),
                harness=FakeHarness([[FakeTurnEnd()]]),diff=[],
                modelo_produtor='M1-synthetic',modelo_consumidor='M2-synthetic'))
        self.assertEqual(r.manifest['modelo_produtor'],'M1-synthetic')
        self.assertEqual(r.manifest['modelo_consumidor'],'M2-synthetic')
        self.assertEqual(r.manifest['execucao']['servidas'],[])

    def test_pooled_report_is_rejected(self):
        from tau_intent.manifest import relatorio_por_par,conferir_relatorio,RelatoIncoerente
        rows=[manifest(modelo_produtor='M1',modelo_consumidor=m) for m in ('M1','M2')]
        report=relatorio_por_par(rows)
        self.assertEqual(len(report),2)
        report[0]['execucoes'].append(rows[1])
        with self.assertRaises(RelatoIncoerente):conferir_relatorio(report)
        with self.assertRaises(RelatoIncoerente):relatorio_por_par([manifest()])
