import importlib.util,tempfile,unittest
from pathlib import Path

class Retrieval(unittest.TestCase):
    def test_surface_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('tau_intent.serve'))

    def test_read_only_top_k_budget_and_current_entries(self):
        from tau_intent.serve import IntentRetrieval
        from tau_intent.adapters.state import TypedStore,StateAdapter,StateAnchor
        from tau_intent.model import IntentEntry
        from tau_intent.store import IntentStore
        from tau_intent.project import ProjectConfig
        from tau_intent.telemetry import count_tokens
        db=TypedStore({'ns':{'a':str,'b':str}}, {'ns':{'a':'x','b':'y'}})
        with tempfile.TemporaryDirectory() as tmp:
            store=IntentStore(Path(tmp))
            for key in ('a','b'):
                store.append(IntentEntry(key,'ts','t',StateAnchor('ns',key,'hash'),key,'p','d'))
            before=store.path.read_bytes()
            service=IntentRetrieval(store,StateAdapter(db),Path(tmp),ProjectConfig(up_depth=0,down_depth=0,token_budget=200))
            query='state://ns::a state://ns::b'
            for k in (0,1,2,5):
                result=service.retrieve_learnings(query,k)
                self.assertIs(type(result),list)
                self.assertEqual(len(result),min(k,2))
                self.assertTrue(all(type(s) is str and '<intencao_registrada>' in s for s in result))
                self.assertLessEqual(sum(map(count_tokens,result)),200)
            self.assertEqual(store.path.read_bytes(),before)
            self.assertEqual(service.retrieve_learnings('unknown'),[])
            with self.assertRaises(ValueError):service.retrieve_learnings(query,-1)
