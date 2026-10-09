import asyncio,tempfile,unittest
from pathlib import Path
from tau_intent.fake_provider import FakeHarness,FakeTurnEnd
from tau_intent.supervisor import run_task,Flags
from tau_intent.gate import Veredito

class ProductiveBoundary(unittest.TestCase):
    def test_cap_stops_without_running_gate_on_productive_event(self):
        calls=[]
        script=[[FakeTurnEnd(tool_results=['fixture']) for _ in range(3)]+[FakeTurnEnd()]]
        with tempfile.TemporaryDirectory() as tmp:
            r=asyncio.run(run_task(Path(tmp),Flags(True,True,False,False),
                harness=FakeHarness(script),diff=[],max_productive_turns=1,
                gate_fn=lambda *args:(calls.append(args) or Veredito.passa())))
        self.assertEqual(r.productive_turns,1)
        self.assertEqual(r.verdict,'TETO')
        # Q2 (2026-10-09): never on a productive event; once, on the final
        # state, to publish the regions that pass. The loop never evaluated it.
        self.assertEqual(len(calls),1)
        self.assertTrue(r.manifest['execucao']['esbarrou_teto'])
        self.assertFalse(r.manifest['execucao']['gate_avaliado'])

    def test_without_end_publication_the_cap_never_runs_the_gate(self):
        from dataclasses import replace
        from tau_intent.config import load_supervisor_config
        calls=[]
        script=[[FakeTurnEnd(tool_results=['fixture']) for _ in range(3)]+[FakeTurnEnd()]]
        with tempfile.TemporaryDirectory() as tmp:
            r=asyncio.run(run_task(Path(tmp),Flags(True,True,False,False),
                harness=FakeHarness(script),diff=[],max_productive_turns=1,
                supervisor_cfg=replace(load_supervisor_config(),publicacao_no_encerramento='nenhuma'),
                gate_fn=lambda *args:(calls.append(args) or Veredito.passa())))
        self.assertEqual((r.verdict,calls),('TETO',[]))
