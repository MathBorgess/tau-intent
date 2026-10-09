"""Arm B v2: the owner's decisions of the arm-B grilling (2026-10-09).

Q2/Q11  graceful stop: a budget notice two turns before the cap and at 90% of
        the deadline, the same in every arm (B and C add the registration
        sentence); TETO, ESCALAR and DEADLINE run the gate on the final state
        and publish the entries whose regions pass.
Q3/Q14  record_intent takes several intents in one call (``intents: [...]``)
        and its description asks for what the code cannot say.
Q5/Q12  the view is pulled: an instruction plus an index of the files with
        history, and a ``recall_intent`` tool. No pushed block.
Q13     arm C (llm_rescue) is not defined in consulta mode.
Q15     every model turn has a class: trabalho, registro, consulta,
        resposta_a_bloqueio, encerramento, final.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tau_intent.adapters import get_adapter
from tau_intent.collect import Region, collect_events
from tau_intent.config import BlocoConfig, load_bloco_config, load_supervisor_config

CONSULTA = load_bloco_config("bloco-consulta.yaml")
from tau_intent.fake_provider import FakeHarness, FakeToolStart, FakeTurnEnd
from tau_intent.gate import GateConfig
from tau_intent.recall import RecallService, instrucao_de_consulta
from tau_intent.store import IntentStore
from tau_intent.supervisor import Flags, run_task
from tau_intent.tools import tool_specs

DIFF2 = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
    "diff --git a/src/other.py b/src/other.py\n"
    "--- a/src/other.py\n"
    "+++ b/src/other.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def g():\n"
    "+    return 2\n"
)
A = Flags(capture=False, gate=False, project=False, serve=False)
B_SEM_VISAO = Flags(capture=True, gate=True, project=False, serve=False)
B = Flags(capture=True, gate=True, project=True, serve=True)
C = Flags(capture=True, gate=True, project=True, serve=True, llm_rescue=True)


def write(path, n=1):
    return FakeToolStart(tool_call_id=f"w{n}", tool_name="write", args={"path": path, "content": "x"})


def intent(file, symbol, why="the reason", n=1):
    return FakeToolStart(tool_call_id=f"r{n}", tool_name="record_intent", args={
        "file": file, "symbol": symbol, "why": why, "property": "p", "domain": "demo"})


def end(*names):
    return FakeTurnEnd(tool_results=[{"tool_name": n} for n in names])


class SteeringHarness(FakeHarness):
    """FakeHarness that records steering messages (tau's mid-session channel)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.steering: list[str] = []

    def steer(self, content):
        self.steering.append(content)
        return list(self.steering)


def repo(root: Path) -> Path:
    (root / "src").mkdir()
    (root / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "src" / "other.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    return root


def run(flags, script, *, harness_cls=SteeringHarness, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        root = repo(Path(tmp))
        harness = harness_cls(script, max_turns=None)
        kwargs.setdefault("diff", DIFF2)
        kwargs.setdefault("symbols", {"f", "g"})
        kwargs.setdefault("bloco_cfg", load_bloco_config())
        result = asyncio.run(run_task(root, flags, harness=harness, **kwargs))
        entries = IntentStore(root).current() if flags.capture else []
        return harness, result, entries


class TestGracefulStop(unittest.TestCase):
    def test_notice_two_turns_before_the_cap_in_arm_a_has_no_registration_sentence(self):
        script = [[write("src/mod.py", i), end("write")] for i in range(4)]
        harness, result, _ = run(A, [sum(script, [])], max_productive_turns=4)
        self.assertEqual(len(harness.steering), 1)
        self.assertIn("2 turns are left", harness.steering[0])
        self.assertNotIn("record_intent", harness.steering[0])
        self.assertEqual(result.telemetry["aviso_de_fim"]["motivo"], "teto")
        self.assertEqual(result.telemetry["aviso_de_fim"]["apos_turno"], 2)

    def test_notice_in_arm_b_asks_for_one_registration_call(self):
        script = [[write("src/mod.py", i), end("write")] for i in range(4)]
        harness, result, _ = run(B_SEM_VISAO, [sum(script, [])], max_productive_turns=4)
        self.assertIn("record_intent", harness.steering[0])

    def test_notice_at_ninety_percent_of_the_deadline(self):
        ticks = iter([0.0, 0.0, 50.0, 95.0, 95.0, 95.0, 95.0, 95.0, 95.0, 95.0])
        script = [write("src/mod.py", 1), end("write"), write("src/mod.py", 2), end("write"), end()]
        harness, result, _ = run(A, [script], max_productive_turns=30, deadline_s=100.0,
                                 relogio=lambda: next(ticks, 95.0))
        self.assertEqual(result.telemetry["aviso_de_fim"]["motivo"], "prazo")
        self.assertEqual(len(harness.steering), 1)

    def test_turns_after_the_notice_are_closing_turns(self):
        script = [[write("src/mod.py", i), end("write")] for i in range(4)]
        _, result, _ = run(A, [sum(script, [])], max_productive_turns=4)
        classes = [t["classe"] for t in result.telemetry["turnos"]]
        self.assertEqual(classes, ["trabalho", "trabalho", "encerramento", "encerramento"])


class TestPublicationAtTheEnd(unittest.TestCase):
    def test_teto_publishes_the_regions_that_pass_and_keeps_the_rest(self):
        script = [[write("src/mod.py", 1), write("src/other.py", 2), intent("src/mod.py", "f", n=3),
                   end("write", "write", "record_intent")]]
        _, result, entries = run(B_SEM_VISAO, script, max_productive_turns=1)
        tel = result.telemetry
        self.assertEqual(result.verdict, "TETO")
        self.assertEqual(tel["publicacao"], "parcial")
        self.assertEqual(tel["portao_no_encerramento"]["tipo"], "BLOQUEIA")
        self.assertEqual(tel["portao_no_encerramento"]["codigos"], {"AUSENTE": 1})
        self.assertEqual(tel["intencoes_publicadas"], 1)
        self.assertEqual(tel["intencoes_nao_publicadas"], 0)
        self.assertEqual(tel["pendencias_nao_publicadas"], 1)  # other.py, never annotated
        self.assertTrue(tel["captura_publicada"])
        self.assertEqual([e.anchor.file for e in entries], ["src/mod.py"])

    def test_teto_with_nothing_registered_publishes_nothing(self):
        script = [[write("src/mod.py", 1), end("write")]]
        _, result, entries = run(B_SEM_VISAO, script, max_productive_turns=1,
                                 diff=DIFF2.split("diff --git a/src/other.py")[0], symbols={"f"})
        self.assertEqual(result.telemetry["publicacao"], "nenhuma")
        self.assertFalse(result.telemetry["captura_publicada"])
        self.assertEqual(entries, [])

    def test_escalar_publishes_the_regions_that_pass(self):
        script = [[write("src/mod.py", 1), write("src/other.py", 2), intent("src/mod.py", "f", n=3),
                   end("write", "write", "record_intent"), end()],
                  [end()], [end()]]
        _, result, entries = run(B_SEM_VISAO, script, gate_cfg=GateConfig(n_max=2))
        self.assertEqual(result.verdict, "ESCALAR")
        self.assertEqual(result.telemetry["publicacao"], "parcial")
        self.assertEqual([e.anchor.file for e in entries], ["src/mod.py"])

    def test_passa_still_publishes_everything(self):
        script = [[write("src/mod.py", 1), intent("src/mod.py", "f", n=2), end("write", "record_intent"), end()]]
        _, result, entries = run(B_SEM_VISAO, script, diff=DIFF2.split("diff --git a/src/other.py")[0],
                                 symbols={"f"})
        self.assertEqual(result.telemetry["publicacao"], "total")
        self.assertEqual(len(entries), 1)


class TestBatchRegistration(unittest.TestCase):
    def test_one_call_registers_several_intents(self):
        regions = [Region("src/mod.py", 1, 2, symbol="f"), Region("src/other.py", 1, 2, symbol="g")]
        event = FakeToolStart(tool_name="record_intent", args={"intents": [
            {"file": "src/mod.py", "symbol": "f", "why": "w1", "domain": "d"},
            {"files": ["src/other.py"], "why": "w2", "property": "p2", "domain": "d"},
        ]})
        pend = collect_events([event], regions)
        self.assertEqual(sorted(p.why for p in pend.values()), ["w1", "w2"])
        self.assertFalse(any(p.unparseable for p in pend.values()))

    def test_a_malformed_batch_item_is_unparseable(self):
        regions = [Region("src/mod.py", 1, 2, symbol="f")]
        event = FakeToolStart(tool_name="record_intent", args={"intents": ["not an object"]})
        pend = collect_events([event], regions)
        self.assertTrue(all(p.unparseable for p in pend.values()))

    def test_batch_call_passes_the_gate_in_one_turn(self):
        batch = FakeToolStart(tool_call_id="r", tool_name="record_intent", args={"intents": [
            {"file": "src/mod.py", "symbol": "f", "why": "w1", "domain": "d"},
            {"file": "src/other.py", "symbol": "g", "why": "w2", "domain": "d"}]})
        script = [[write("src/mod.py", 1), write("src/other.py", 2), batch, end("write", "write", "record_intent"),
                   end()]]
        _, result, entries = run(B_SEM_VISAO, script)
        self.assertEqual(result.verdict, "PASSA")
        self.assertEqual(len(entries), 2)

    def test_description_asks_for_what_the_code_cannot_say(self):
        spec = next(s for s in tool_specs(capture=True) if s["name"] == "record_intent")
        self.assertIn("could not recover from the code", spec["description"])
        self.assertIn("intents", spec["parameters"]["properties"])
        self.assertEqual(spec["parameters"].get("required", []), [])


class TestPulledView(unittest.TestCase):
    def _store(self, root: Path) -> IntentStore:
        from tau_intent.model import Anchor, IntentEntry
        store = IntentStore(root / "log")
        for i, (file, symbol, why) in enumerate([("src/mod.py", "f", "f keeps ints"),
                                                 ("src/mod.py", "f", "f keeps ints"),
                                                 ("src/other.py", "g", "g is pure")]):
            store.append(IntentEntry(id=str(i), ts=f"2026-10-09T00:00:0{i}Z", task_id="t1",
                                     anchor=Anchor(file, symbol, 1, 2, ""), why=why, property="", domain="d"))
        return store

    def test_instruction_lists_files_with_history_and_no_entry_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            texto = instrucao_de_consulta(store.current(), CONSULTA)
        self.assertIn("recall_intent", texto)
        self.assertIn("src/mod.py (1)", texto)  # the identical copy is not counted
        self.assertIn("src/other.py (1)", texto)
        self.assertNotIn("f keeps ints", texto)

    def test_instruction_without_history_says_so(self):
        texto = instrucao_de_consulta([], CONSULTA)
        self.assertIn("No intent has been recorded yet.", texto)

    def test_recall_returns_the_entries_of_the_asked_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(Path(tmp))
            store = self._store(root)
            recall = RecallService(store, get_adapter("code"), root, bloco_cfg=CONSULTA)
            out = recall(paths=["src/mod.py"])
            vazio = recall(symbols=["src/nowhere.py::h"])
        self.assertEqual(out["intent"].count("f keeps ints"), 1)
        self.assertNotIn("g is pure", out["intent"])
        self.assertEqual(recall.chamadas[0]["paths"], ["src/mod.py"])
        self.assertEqual(recall.chamadas[0]["n_entradas"], 1)
        self.assertGreater(recall.chamadas[0]["tokens"], 0)
        self.assertEqual(vazio["intent"], "No recorded intent for these files or symbols.")

    def test_arm_b_in_consulta_mode_serves_the_instruction_and_offers_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(Path(tmp))
            store = self._store(root)
            recall = RecallService(store, get_adapter("code"), root)
            harness = SteeringHarness([[FakeToolStart(tool_name="recall_intent", args={"paths": ["src/mod.py"]}),
                                        end("recall_intent"), end()]], max_turns=None,
                                      tools=tool_specs(capture=True, recall=recall))
            result = asyncio.run(run_task(root, B, harness=harness, store=store, recall=recall, diff="",
                                          symbols=set(), bloco_cfg=CONSULTA))
            recall(paths=["src/mod.py"])  # the fake harness does not execute tools
        tel = result.telemetry
        self.assertEqual(tel["visao_modo"], "consulta")
        self.assertIn("recall_intent", result.bloco)
        self.assertNotIn("<intencao_registrada>", result.bloco)
        self.assertEqual([t["classe"] for t in tel["turnos"]], ["consulta", "final"])
        self.assertEqual(tel["chamadas_recall_intent"], 1)

    def test_consulta_mode_without_the_tool_in_the_harness_is_refused(self):
        with self.assertRaises(ValueError):
            run(B, [[end()]], bloco_cfg=CONSULTA)

    def test_arm_c_is_not_defined_in_consulta_mode(self):
        with self.assertRaises(ValueError):
            run(C, [[end()]], bloco_cfg=CONSULTA, summarizer_fn=lambda *a: None)

    def test_tools_by_arm(self):
        names = lambda **kw: [s["name"] for s in tool_specs(**kw)]  # noqa: E731
        self.assertNotIn("record_intent", names(capture=False))
        self.assertNotIn("recall_intent", names(capture=True))
        self.assertIn("recall_intent", names(capture=True, recall=lambda **kw: {}))


class TestTurnClasses(unittest.TestCase):
    def test_classes_and_the_mechanism_count(self):
        script = [[write("src/mod.py", 1), end("write"), end()],
                  [intent("src/mod.py", "f", n=2), end("record_intent"), end()]]
        _, result, _ = run(B_SEM_VISAO, script, diff=DIFF2.split("diff --git a/src/other.py")[0], symbols={"f"})
        tel = result.telemetry
        self.assertEqual([t["classe"] for t in tel["turnos"]],
                         ["trabalho", "final", "resposta_a_bloqueio", "resposta_a_bloqueio"])
        self.assertEqual(tel["turnos_por_classe"], {"trabalho": 1, "final": 1, "resposta_a_bloqueio": 2})
        self.assertEqual(tel["turnos_do_mecanismo"], 2)

    def test_a_turn_with_work_and_registration_is_work_marked_mixed(self):
        script = [[write("src/mod.py", 1), intent("src/mod.py", "f", n=2), end("write", "record_intent"), end()]]
        _, result, _ = run(B_SEM_VISAO, script, diff=DIFF2.split("diff --git a/src/other.py")[0], symbols={"f"})
        first = result.telemetry["turnos"][0]
        self.assertEqual((first["classe"], first["misto"]), ("trabalho", True))
        self.assertEqual(first["ferramentas"], ["record_intent", "write"])


class TestSupervisorConfig(unittest.TestCase):
    def test_declared_defaults(self):
        cfg = load_supervisor_config()
        self.assertEqual((cfg.aviso_turnos_restantes, cfg.aviso_fracao_do_prazo), (2, 0.9))
        self.assertTrue(cfg.teto_conta_resposta_a_bloqueio)
        self.assertEqual(cfg.publicacao_no_encerramento, "por_regiao")
        self.assertEqual(load_bloco_config().modo, "bloco")  # v1, byte-identical
        self.assertEqual((CONSULTA.modo, CONSULTA.versao), ("consulta", "bloco-v2-consulta"))
        self.assertEqual(BlocoConfig().modo, "bloco")


if __name__ == "__main__":
    unittest.main()


try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    BENCH_READY = True
except ImportError:  # pragma: no cover - depends on the environment
    BENCH_READY = False


@unittest.skipUnless(BENCH_READY, "needs pytest and tau-ai (pip install .[bench])")
class TestBenchWithThePulledView(unittest.TestCase):
    """``tau-intent bench --bloco-yaml bloco-consulta.yaml`` end to end, offline."""

    def run_cell(self, arms):
        import json
        from tests.bench_support import DemoModel, read_records
        from tests.stub_openai import StubServer
        from tests.test_bench_runner import run_bench
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        with StubServer(DemoModel()) as stub:
            code, stdout = run_bench(out, stub, "--bloco-yaml", "bloco-consulta.yaml",
                                     offline_args=("--arms", arms, "--seed", "7"))
            requests = stub.chat_requests()
        cells = [p for p in out.iterdir() if p.is_dir()]
        records = read_records(cells[0]) if cells else []
        manifests = [json.loads(p.read_text()) for p in sorted(out.rglob("manifest.json"))]
        return code, stdout, records, requests, manifests

    def test_arm_b_is_offered_recall_intent_and_the_record_says_consulta(self):
        code, stdout, records, requests, manifests = self.run_cell("A,B")
        self.assertEqual(code, 0, stdout)
        b = [r for r in records if r["arm_id"] == "B"]
        self.assertTrue(b)
        for record in b:
            tel = record["mechanism_telemetry"]
            self.assertEqual((tel["visao_modo"], tel["bloco_versao"]), ("consulta", "bloco-v2-consulta"))
            self.assertIn("turnos_por_classe", tel)
            self.assertIn("publicacao", tel)
        tools_by_request = [{t["function"]["name"] for t in (req.get("tools") or [])} for req in requests]
        self.assertTrue(any("recall_intent" in names for names in tools_by_request))
        self.assertTrue(all("recall_intent" not in names or "record_intent" in names for names in tools_by_request))
        self.assertTrue(all(m["bench"]["bloco_yaml"] == "bloco-consulta.yaml" for m in manifests if "bench" in m))

    def test_arm_c_is_refused_with_the_pulled_view(self):
        code, stdout, records, _, _ = self.run_cell("A,B,C")
        self.assertNotEqual(code, 0)
        self.assertIn("Q13", stdout)
        self.assertEqual(records, [])
