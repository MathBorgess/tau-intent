import importlib.util
import tempfile
import unittest
from pathlib import Path

class CheckpointCapture(unittest.TestCase):
    def test_checkpoint_api_available(self):
        self.assertIsNotNone(importlib.util.find_spec('tau_intent.checkpoint'))

    def test_deterministic_half_round_trip_and_render(self):
        from tau_intent.checkpoint import Checkpoint,ValidationEvidence
        from tau_intent.collect import Region
        from tau_intent.model import IntentEntry,Anchor
        from tau_intent.store import IntentStore
        from tau_intent.render import render_entry
        r=Region('a.py',1,2,symbol='f')
        cp=Checkpoint.observe([r],non_target_artifacts=('report.txt',),
            validation=ValidationEvidence('unit-check','exit=0'),continuation_state='already solved, preserve')
        e=IntentEntry('id','ts','task',Anchor('a.py','f',1,2,'hash'),'why','property','domain',checkpoint=cp)
        with tempfile.TemporaryDirectory() as tmp:
            store=IntentStore(Path(tmp));store.append(e)
            loaded=IntentStore(Path(tmp)).current()[0]
        self.assertEqual(loaded.checkpoint,cp)
        self.assertEqual(cp.changed_targets,('a.py::f',))
        for value in ('unit-check','exit=0','already solved, preserve','report.txt'):
            self.assertIn(value,render_entry(loaded))

    def test_no_inference_of_continuation_state(self):
        from tau_intent.checkpoint import Checkpoint
        with self.assertRaises(ValueError):
            Checkpoint.observe([],continuation_state='probably solved')

    def test_runner_uses_checkpoint_observer_not_agent_fields(self):
        import asyncio
        from tau_intent.checkpoint import Checkpoint,ValidationEvidence
        from tau_intent.fake_provider import FakeHarness,FakeToolStart,FakeTurnEnd
        from tau_intent.supervisor import run_task,Flags
        from tau_intent.store import IntentStore
        from tau_intent.collect import Region
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('def f():\n    return 1\n')
            script=[[FakeToolStart(tool_name='record_intent',args={'file':'a.py','why':'w','domain':'d','latest_validation_evidence':'forged'}),FakeTurnEnd()]]
            asyncio.run(run_task(root,Flags(True,True,False,False),harness=FakeHarness(script),diff=[Region('a.py',1,2)],checkpoint_source=lambda rs:Checkpoint.observe(rs,validation=ValidationEvidence('assertion','observed'))))
            entry=IntentStore(root).current()[0]
            self.assertEqual(entry.checkpoint.latest_validation_evidence,'observed')
            self.assertIsNone(entry.checkpoint.continuation_state)

    def test_validation_evidence_comes_from_executed_check(self):
        import sys,json
        from tau_intent.adapters.code import CodeAdapter
        from tau_intent.adapters.state import TypedStore,StateAdapter
        with tempfile.TemporaryDirectory() as tmp:
            evidence=CodeAdapter().validate([sys.executable,'-c','print("fixture")'],Path(tmp))
        self.assertEqual(json.loads(evidence.evidence)['returncode'],0)
        self.assertEqual(json.loads(evidence.evidence)['stdout'],'fixture\n')
        db=TypedStore({'ns':{'k':int}},{'ns':{'k':1}})
        adapter=StateAdapter(db,checks={'positive':lambda s:s['ns']['k']>0})
        self.assertEqual(json.loads(adapter.validate('positive').evidence),{'passed':True})
        db.set('ns','k',-1)
        self.assertEqual(json.loads(adapter.validate('positive').evidence),{'passed':False})
