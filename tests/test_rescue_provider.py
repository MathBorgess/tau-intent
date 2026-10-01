"""S5: arm C's rescue answered by the cell's own local model, token-accounted.

Owner decisions: same endpoint and model as the cell, trigger ``sempre``, and a
rejected rewrite still counts its tokens.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tau_intent.harness_factory import WireLog
from tau_intent.model import Anchor, IntentEntry
from tau_intent.rescue import load_rescue_config
from tau_intent.rescue_provider import sumarizador_local
from tau_intent.store import IntentStore
from tests.stub_openai import StubServer, text
from tests.test_real_harness import HAVE_TAU, SEED, repo, run_arm

MODEL = "stub-model"


def seeded(root: Path) -> Path:
    repo(root)
    store = IntentStore(root)
    store.append(IntentEntry(
        id="seed-1", ts="2026-10-01T00:00:00Z", task_id="task-01",
        anchor=Anchor(file="src/mod.py", symbol="f", line_start=1, line_end=2, blob_sha="0" * 40),
        why="f existe para devolver o valor base que as tarefas seguintes estendem",
        property="f retorna int e nunca levanta", domain="demo"))
    return root


def rescue_text(body: dict) -> str:
    """What a well-behaved model returns for the rescue prompt: the registro back."""
    content = body["messages"][0]["content"]
    return content.rsplit("<registro>", 1)[-1].split("</registro>", 1)[0].strip()


def agent_or_rescue(rescue_turn):
    def script(index, body):
        if body.get("stream"):
            return text("done")
        return rescue_turn(body)
    return script


@unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
class TestRescueProvider(unittest.TestCase):
    def run_c(self, rescue_turn, **stub_kwargs):
        wire = WireLog(stamp={"temperature": 0, "seed": SEED})
        with tempfile.TemporaryDirectory() as tmp, \
                StubServer(agent_or_rescue(rescue_turn), **stub_kwargs) as stub:
            summarizer = sumarizador_local(stub.url, MODEL, SEED, wire=wire,
                                           timeout_s=stub_kwargs.pop("timeout_s", None) or 5)
            harness, result = run_arm(seeded(Path(tmp)), "C", stub, summarizer_fn=summarizer,
                                      prompt="update src/mod.py so f returns 1")
        return stub, summarizer, wire, result

    def test_rescue_uses_the_cells_endpoint_and_model_and_stamps_sampling_on_the_wire(self):
        stub, summarizer, wire, result = self.run_c(lambda body: text(rescue_text(body)))
        rescue_bodies = [b for b in stub.requests if not b.get("stream")]
        self.assertEqual(len(rescue_bodies), 1)
        body = rescue_bodies[0]
        self.assertEqual((body["model"], body["temperature"], body["seed"], body["max_tokens"]),
                         (MODEL, 0, SEED, 800))
        self.assertIs(body["stream"], False)
        self.assertIn("<registro>", body["messages"][0]["content"])
        self.assertTrue(wire.report()["conferida_no_fio"])
        # the agent session ran on the same endpoint
        self.assertEqual(sum(1 for b in stub.requests if b.get("stream")), 1)
        self.assertEqual(summarizer.cfg.gatilho, "sempre")
        self.assertEqual(summarizer.cfg.modelo_id, MODEL)

    def test_applied_rescue_counts_its_provider_tokens_apart_from_the_agents(self):
        stub, summarizer, wire, result = self.run_c(lambda body: text(rescue_text(body)))
        self.assertTrue(result.telemetry["llm_rescue_aplicado"])
        tokens = result.telemetry["tokens"]
        self.assertEqual((tokens["rescue_in"], tokens["rescue_out"]), (11, 7))
        self.assertEqual((tokens["in"], tokens["out"]), (11, 7))  # the agent's own call, stub default usage
        self.assertEqual(tokens["source"], "provider_usage")
        kinds = [row["kind"] for row in result.telemetry["turnos"]]
        self.assertEqual(kinds, ["rescue", "productive"])
        self.assertEqual([row["turn_index"] for row in result.telemetry["turnos"]], [1, 2])

    def test_a_rejected_rewrite_still_counts_its_tokens(self):
        usage = {"prompt_tokens": 500, "completion_tokens": 40}
        stub, summarizer, wire, result = self.run_c(lambda body: text("lost every anchor", usage=usage))
        self.assertFalse(result.telemetry["llm_rescue_aplicado"])
        self.assertTrue(result.telemetry["llm_rescue_falhou"])
        tokens = result.telemetry["tokens"]
        self.assertEqual((tokens["rescue_in"], tokens["rescue_out"]), (500, 40))
        self.assertEqual(summarizer.chamadas_log, [{"tokens_in": 500, "tokens_out": 40}])

    def test_the_trigger_is_always_even_when_nothing_was_cut(self):
        stub, summarizer, wire, result = self.run_c(lambda body: text(rescue_text(body)))
        self.assertEqual(result.telemetry["n_cortadas"], 0)
        self.assertTrue(result.telemetry["llm_rescue_disparou"])

    def test_provider_error_is_declared_and_its_tokens_are_missing_not_zero(self):
        wire = WireLog(stamp={"temperature": 0, "seed": SEED})
        with tempfile.TemporaryDirectory() as tmp, StubServer(
                agent_or_rescue(lambda body: text("x")),
                status=lambda i: 500 if i == 0 else 200) as stub:
            # request 0 is the (non-streamed) rescue call: it is made before the agent runs
            summarizer = sumarizador_local(stub.url, MODEL, SEED, wire=wire, timeout_s=5)
            harness, result = run_arm(seeded(Path(tmp)), "C", stub, summarizer_fn=summarizer,
                                      prompt="update src/mod.py so f returns 1")
        self.assertTrue(result.telemetry["llm_rescue_falhou"])
        self.assertIn("HTTP 500", result.telemetry["llm_rescue_erro"])
        tokens = result.telemetry["tokens"]
        self.assertIsNone(tokens["rescue_in"])
        self.assertEqual(tokens["source"], "missing")
        self.assertIsNotNone(result.manifest["execucao"]["llm_rescue_erro"])

    def test_endpoint_without_usage_leaves_rescue_tokens_missing(self):
        stub, summarizer, wire, result = self.run_c(lambda body: text(rescue_text(body), usage=None))
        self.assertIsNone(result.telemetry["tokens"]["rescue_in"])
        self.assertEqual(result.telemetry["tokens"]["source"], "missing")
        self.assertTrue(result.telemetry["llm_rescue_aplicado"])  # the block still got rewritten

    def test_request_timeout_is_a_failure_of_the_call_not_a_hang(self):
        wire = WireLog(stamp={"temperature": 0, "seed": SEED})
        with tempfile.TemporaryDirectory() as tmp, StubServer(
                agent_or_rescue(lambda body: text("slow", delay=3))) as stub:
            summarizer = sumarizador_local(stub.url, MODEL, SEED, wire=wire, timeout_s=0.3)
            harness, result = run_arm(seeded(Path(tmp)), "C", stub, summarizer_fn=summarizer,
                                      prompt="update src/mod.py so f returns 1")
        self.assertTrue(result.telemetry["llm_rescue_falhou"])
        self.assertRegex(result.telemetry["llm_rescue_erro"], "unreachable|timed out")

    def test_rescue_clock_counts_against_the_attempts_deadline(self):
        """C pays for its rescue on the same clock as everything else."""
        wire = WireLog(stamp={"temperature": 0, "seed": SEED})
        with tempfile.TemporaryDirectory() as tmp, StubServer(
                agent_or_rescue(lambda body: text(rescue_text(body), delay=1.2))) as stub:
            summarizer = sumarizador_local(stub.url, MODEL, SEED, wire=wire, timeout_s=5)
            harness, result = run_arm(seeded(Path(tmp)), "C", stub, summarizer_fn=summarizer,
                                      prompt="update src/mod.py so f returns 1", deadline_s=1.0)
        self.assertEqual(result.telemetry["encerramento"], "deadline")
        self.assertEqual(sum(1 for b in stub.requests if b.get("stream")), 0)

    def test_rescue_yaml_is_still_the_frozen_one(self):
        cfg = load_rescue_config()
        self.assertEqual((cfg.gatilho, cfg.modelo_id, cfg.habilitado), ("sempre", "", False))
        from tau_intent.config import config_hashes
        import json
        golden = json.loads((Path(__file__).parent / "fixtures" / "config_sha256_v2.json").read_text())
        self.assertEqual(config_hashes()["rescue.yaml"], golden["rescue.yaml"])


if __name__ == "__main__":
    unittest.main()
