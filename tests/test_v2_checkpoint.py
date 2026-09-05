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
