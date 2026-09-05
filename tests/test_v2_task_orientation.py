import asyncio,tempfile,unittest
from pathlib import Path
from tests.test_integration_bench import _semear
from tau_intent.supervisor import run_task,Flags
from tau_intent.fake_provider import FakeHarness,FakeTurnEnd

class TaskOrientation(unittest.TestCase):
    def test_new_task_can_retrieve_before_its_first_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=_semear(Path(tmp))
            r=asyncio.run(run_task(root,Flags(True,True,True,True),diff=[],
                prompt='Continue src/mod.py::f',harness=FakeHarness([[FakeTurnEnd()]])))
        self.assertIn('src/mod.py::f',r.bloco)
        self.assertEqual(r.telemetry['ancoras'],['src/mod.py::f'])
