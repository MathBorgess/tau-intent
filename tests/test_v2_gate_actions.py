import tempfile,unittest
from pathlib import Path
from tau_intent.collect import Region,Pending,collect_events,resolver_simbolos
from tau_intent.gate import portao
from tau_intent.config import load_gate_config

class SatisfiableGate(unittest.TestCase):
    def verdict(self,rs,events):
        return portao(rs,collect_events(events,rs),set(),load_gate_config(),0)

    def test_valid_command_without_redirect_is_not_malformed(self):
        r=Region('a.py',1,2)
        events=[{'tool_name':'bash','args':{'command':'unit-check'}},
                {'tool_name':'record_intent','args':{'file':'a.py','why':'w','domain':'d'}}]
        self.assertEqual(self.verdict([r],events).tipo,'PASSA')

    def test_agent_can_correct_a_rejected_call(self):
        r=Region('a.py',1,2)
        bad={'tool_name':'record_intent','args':{'file':'a.py'},'_raw_arguments':'broken'}
        good={'tool_name':'record_intent','args':{'file':'a.py','why':'w','domain':'d'}}
        self.assertEqual(self.verdict([r],[bad]).falhas[0].code,'NAO_PARSEAVEL')
        self.assertEqual(self.verdict([r],[bad,good]).tipo,'PASSA')

    def test_non_object_arguments_are_reported_not_crashed(self):
        r=Region('a.py',1,2)
        v=self.verdict([r],[{'tool_name':'record_intent','args':'bad'}])
        self.assertEqual(v.falhas[0].code,'NAO_PARSEAVEL')

    def test_declaration_cannot_manufacture_an_effect(self):
        self.assertEqual(collect_events([{'tool_name':'record_intent','args':{'file':'invented','why':'w','domain':'d'}}],[]),{})

    def test_available_witness_without_fine_identity_is_not_agent_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'a.py').write_text('value = 1\n'*60)
            rs=resolver_simbolos([Region('a.py',1,60,edited_lines=60)],tmp)
        v=self.verdict(rs,[{'tool_name':'record_intent','args':{'file':'a.py','why':'w','domain':'d'}}])
        self.assertEqual(v.tipo,'PASSA')
        self.assertEqual([f.code for f in v.nao_avaliaveis],['EDICAO_GRANDE_SEM_SIMBOLO'])

    def test_unrelated_true_name_cannot_certify_this_effect(self):
        r=Region('a.py',1,60,edited_lines=60,symbol='real')
        p=Pending(r,why='w',domain='d',symbol='unrelated')
        v=portao([r],{r.key():p},{'a.py::real','a.py::unrelated'},load_gate_config(),0)
        self.assertEqual(v.tipo,'BLOQUEIA')
        self.assertEqual(len(v.falhas),2)

    def test_corrected_call_preserves_error_history_in_manifest(self):
        import asyncio
        from tau_intent.fake_provider import FakeHarness,FakeToolStart,FakeTurnEnd
        from tau_intent.supervisor import run_task,Flags
        script=[[FakeToolStart(tool_name='record_intent',args={'file':'a.py'}),FakeTurnEnd()],
                [FakeToolStart(tool_name='record_intent',args={'file':'a.py','why':'w','domain':'d'}),FakeTurnEnd()]]
        with tempfile.TemporaryDirectory() as tmp:
            r=asyncio.run(run_task(Path(tmp),Flags(True,True,False,False),harness=FakeHarness(script),diff=[Region('a.py',1,2)]))
        self.assertEqual(r.verdict,'PASSA')
        self.assertEqual(r.block_turns,1)
        self.assertEqual(len(r.manifest['execucao']['erros_de_captura']),1)

    def test_failed_gate_does_not_publish_ungated_intent(self):
        import asyncio
        from dataclasses import replace
        from tau_intent.fake_provider import FakeHarness,FakeToolStart,FakeTurnEnd
        from tau_intent.supervisor import run_task,Flags
        script=[[FakeToolStart(tool_name='record_intent',args={'file':'a.py','why':'w'}),FakeTurnEnd()]]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            r=asyncio.run(run_task(root,Flags(True,True,False,False),harness=FakeHarness(script),diff=[Region('a.py',1,2)],gate_cfg=replace(load_gate_config(),n_max=0)))
            self.assertEqual(r.verdict,'ESCALAR')
            self.assertFalse((root/'intents.jsonl').exists())
