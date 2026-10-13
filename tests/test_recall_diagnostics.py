"""Real store reloading and cold lookup; no model calls or hidden test banks."""
import ast
import shutil
import tempfile
import unittest
from pathlib import Path
from tau_intent.adapters import get_adapter
from tau_intent.model import Anchor, IntentEntry
from tau_intent.recall import RecallService, SEM_HISTORICO
from tau_intent.store import IntentStore

class RecallDiagnosticTests(unittest.TestCase):
    def test_cold_service_reloads_five_published_entries_in_sklearn_workspace(self):
        source=Path('/home/ubuntu/tg/swem-sklearn/linux-arm-pilot-k2-20261013-v2/seed/sklearn/utils/_array_api.py')
        if not source.is_file():
            self.skipTest('local frozen sklearn implementation source unavailable')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);relative='sklearn/utils/_array_api.py';target=root/relative
            target.parent.mkdir(parents=True);shutil.copyfile(source,target)
            functions=[n for n in ast.parse(target.read_text()).body if isinstance(n,ast.FunctionDef)][:5]
            self.assertEqual(len(functions),5)
            path=root/'history/intents.jsonl'
            cold=RecallService(path,get_adapter('code'),root)
            self.assertEqual(cold(paths=[relative])['intent'],SEM_HISTORICO)
            self.assertEqual(cold.chamadas[-1]['diagnostic']['empty_reason'],'no_published_history')
            writer=IntentStore(path)
            for i,node in enumerate(functions):
                writer.append(IntentEntry(id=f'intent-{i}',ts=f'2026-10-13T00:00:0{i}Z',task_id='task-01',
                    anchor=Anchor(file=relative,symbol=node.name,line_start=node.lineno,line_end=node.end_lineno,blob_sha='fixture'),
                    why=f'Preserve array semantics for function {node.name}.',property=f'Function {node.name} keeps its documented result.',domain='code'))
            del writer,cold
            # Fresh service and store: no conversation or publication object survives.
            fresh=RecallService(IntentStore(path),get_adapter('code'),root)
            result=fresh(paths=[relative]);diagnostic=fresh.chamadas[-1]['diagnostic']
            self.assertEqual(set(result),{'ok','intent'})
            self.assertEqual(diagnostic['store_entries_current'],5)
            self.assertEqual(set(diagnostic['served_entry_ids']),{f'intent-{i}'for i in range(5)})
            self.assertIsNone(diagnostic['empty_reason'])
            for node in functions:self.assertIn(f'Preserve array semantics for function {node.name}.',result['intent'])
            self.assertEqual(fresh(paths=['sklearn/tree/_classes.py'])['intent'],SEM_HISTORICO)
            self.assertEqual(fresh.chamadas[-1]['diagnostic']['empty_reason'],'no_direct_or_reachable_history')
            self.assertEqual(fresh.chamadas[-1]['diagnostic']['direct_matching_entry_ids'],[])
    def test_portable_store_snapshot_and_current_stage_are_visible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);file=root/'sklearn/utils/module.py';file.parent.mkdir(parents=True)
            file.write_text('def helper():\n return 1\n')
            store=IntentStore(root/'history/intents.jsonl')
            store.append(IntentEntry(id='current',ts='2026-10-13T00:00:00Z',task_id='task-02',
                anchor=Anchor('sklearn/utils/module.py','helper',1,2,'fixture'),why='Keep one.',property='Returns one.',domain='code'))
            recall=RecallService(store,get_adapter('code'),root)
            result=recall(paths=['./sklearn/utils/module.py']);diagnostic=recall.chamadas[-1]['diagnostic']
            self.assertIn('Keep one.',result['intent']);self.assertEqual(diagnostic['current_task_ids'],['task-02'])
            self.assertEqual(diagnostic['normalized_paths'],['sklearn/utils/module.py'])
