import asyncio,importlib.util,json,tempfile,unittest
from pathlib import Path
from tau_intent.fake_provider import FakeHarness,FakeToolStart,FakeTurnEnd
from tau_intent.supervisor import run_task,Flags
from tau_intent.store import IntentStore

class StateFixture(unittest.TestCase):
    def test_adapter_available(self):
        self.assertIsNotNone(importlib.util.find_spec('tau_intent.adapters.state'))

    def test_delta_capture_supersession_projection_and_oracle(self):
        from tau_intent.adapters.state import TypedStore,StateAdapter
        from tau_intent.checkpoint import Checkpoint,ValidationEvidence
        from tau_intent.project import projetar,ProjectConfig
        db=TypedStore({'booking':{'status':str,'paid':bool}}, {'booking':{'status':'pending','paid':False}})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for value in ('confirmed','cancelled'):
                adapter=StateAdapter(db)
                class Writer(FakeHarness):
                    async def prompt(self,prompt):
                        db.set('booking','status',value)
                        yield FakeToolStart(tool_name='record_intent',args={'file':'state://booking','symbol':'status','why':value,'domain':'travel'})
                        yield FakeTurnEnd()
                result=asyncio.run(run_task(root,Flags(True,True,True,True),adapter=adapter,harness=Writer(),ancoras=['state://booking::status'],checkpoint_source=lambda rs:Checkpoint.observe(rs,validation=ValidationEvidence('booking-status','checked'),continuation_state='already solved, preserve')))
                self.assertEqual(result.verdict,'PASSA')
                self.assertEqual(result.telemetry['cobertura_efetiva'],1)
                self.assertTrue(adapter.oracle(lambda state:state['booking']['status']==value))
            store=IntentStore(root)
            self.assertEqual(len(store._entries),2)
            self.assertEqual(len(store.current()),1)
            self.assertEqual(store.current()[0].supersedes,(store._entries[0].id,))
            self.assertNotEqual(store._entries[0].anchor.value_hash,store.current()[0].anchor.value_hash)
            block,tel=projetar(adapter.neighbourhood(root),store.current(),['state://booking::status'],ProjectConfig(),superadas=1)
            self.assertIn('cancelled',block)
            self.assertNotIn('Por que: confirmed',block)
            self.assertEqual(tel['recibo']['superadas_omitidas'],1)
            self.assertTrue(adapter.anchor_resolves(store.current()[0].anchor))
            self.assertFalse(adapter.anchor_resolves(store._entries[0].anchor))

    def test_schema_closed_and_missing_is_not_null(self):
        from tau_intent.adapters.state import TypedStore,StateAdapter
        db=TypedStore({'ns':{'k':type(None),'count':int}}, {'ns':{'k':None}})
        adapter=StateAdapter(db)
        with self.assertRaises(KeyError):db.set('ns','invented',1)
        with self.assertRaises(TypeError):db.set('ns','count',True)
        db.delete('ns','k')
        effect=adapter.effects(None)[0]
        self.assertNotEqual(effect.before_hash,effect.value_hash)
        self.assertEqual(effect.size,1)

    def test_state_path_does_not_load_code_resolver(self):
        import subprocess,sys
        script="""
import sys
from tau_intent.adapters.state import TypedStore,StateAdapter
from tau_intent.project import projetar,ProjectConfig
from tau_intent.supervisor import run_task
adapter=StateAdapter(TypedStore({'ns':{'k':str}}, {'ns':{'k':'before'}}))
adapter.store.set('ns','k','after')
assert adapter.effects(None)
projetar(adapter.neighbourhood(None),[],['state://ns::k'],ProjectConfig())
assert 'tau_intent.adapters.code' not in sys.modules
assert 'tau_intent.adapters.code_graph' not in sys.modules
"""
        p=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_unknown_substrate_declares_degradation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=asyncio.run(run_task(Path(tmp),Flags(True,True,True,True),adapter='conversation',harness=FakeHarness([[FakeTurnEnd()]])))
            self.assertFalse((Path(tmp)/'intents.jsonl').exists())
        self.assertEqual(result.verdict,'NAO_AVALIAVEL')
        self.assertEqual(result.telemetry['modo'],'degradado-sem-testemunha')
        self.assertTrue(result.telemetry['codigos_nao_avaliaveis'])

    def test_unannotated_sibling_key_is_missing_not_an_overlap(self):
        from tau_intent.adapters.state import TypedStore,StateAdapter
        from tau_intent.config import load_gate_config
        from tau_intent.gate import portao
        db=TypedStore({'ns':{'a':str,'b':str}})
        adapter=StateAdapter(db)
        db.set('ns','a','one');db.set('ns','b','two')
        effects=adapter.effects(None)
        pending=adapter.collect([{'tool_name':'record_intent','args':{'file':'state://ns','symbol':'a','why':'w','domain':'d'}}],effects,None)
        v=portao(effects,pending,adapter.identities(effects,None),load_gate_config(),0)
        self.assertEqual([f.code for f in v.falhas],['AUSENTE'])

    def test_nested_values_must_be_unambiguous_json(self):
        from tau_intent.adapters.state import TypedStore, StateAdapter
        db = TypedStore({'ns': {'payload': dict}}, {'ns': {'payload': {'items': [1, None]}}})
        adapter = StateAdapter(db)
        for value in ({1: 'value'}, {'items': [{1: 'value'}]}, {'items': (1, 2)}):
            with self.subTest(value=value), self.assertRaises(TypeError):
                db.set('ns', 'payload', value)
            self.assertEqual(adapter.effects(None), [])
        db.set('ns', 'payload', {'items': [2, None]})
        self.assertEqual(len(adapter.effects(None)), 1)
