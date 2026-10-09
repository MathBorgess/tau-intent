"""S4: outcome tokens come from provider usage per call; the block budget keeps
its own declared unit. Nothing is estimated."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tau_intent.telemetry import (
    BUDGET_TOKEN_UNIT,
    OUTCOME_TOKEN_UNIT,
    count_tokens,
    linha_de_turno,
    resumir_tokens,
    uso_do_provedor,
)
from tests.stub_openai import StubServer, call, text, tools
from tests.test_real_harness import HAVE_TAU, RECORD, WRITE, repo, run_arm


class Msg:
    def __init__(self, **usage):
        from tau_agent.messages import Usage
        self.usage = Usage(**usage)


class TestUsageFunctions(unittest.TestCase):
    @unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
    def test_prompt_is_fresh_plus_cache_with_no_discount(self):
        # tau splits OpenAI prompt_tokens into fresh input + cache read + cache write
        self.assertEqual(uso_do_provedor(Msg(input=10, cache_read=5, cache_write=2, output=3)),
                         {"tokens_in": 17, "tokens_out": 3})

    @unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
    def test_tau_zeroed_usage_is_missing_not_free(self):
        self.assertIsNone(uso_do_provedor(Msg()))

    def test_no_usage_object_is_missing_not_free(self):
        self.assertIsNone(uso_do_provedor(None))
        self.assertIsNone(uso_do_provedor(object()))

    def test_sum_is_none_when_any_call_lacks_usage_never_a_partial_total(self):
        rows = [linha_de_turno(1, "productive", {"tokens_in": 10, "tokens_out": 2}, 1),
                linha_de_turno(2, "productive", None, 0)]
        out = resumir_tokens(rows)
        self.assertEqual((out["in"], out["out"], out["source"]), (None, None, "missing"))
        self.assertEqual(out["cost_usd"], 0)

    def test_rescue_side_is_summed_apart_and_discarded_attempts_count(self):
        rows = [linha_de_turno(2, "productive", {"tokens_in": 10, "tokens_out": 2}, 0)]
        rescue = [{"tokens_in": 100, "tokens_out": 30}, {"tokens_in": 100, "tokens_out": 31}]
        out = resumir_tokens(rows, rescue)
        self.assertEqual((out["in"], out["out"], out["rescue_in"], out["rescue_out"]), (10, 2, 200, 61))
        self.assertEqual(out["source"], "provider_usage")

    def test_no_rescue_calls_is_a_true_zero_not_a_missing(self):
        out = resumir_tokens([linha_de_turno(1, "productive", {"tokens_in": 1, "tokens_out": 1}, 0)])
        self.assertEqual((out["rescue_in"], out["rescue_out"]), (0, 0))

    def test_units_are_declared_separately(self):
        out = resumir_tokens([])
        self.assertEqual((out["unit"], out["budget_unit"]), (OUTCOME_TOKEN_UNIT, BUDGET_TOKEN_UNIT))
        self.assertEqual(BUDGET_TOKEN_UNIT, "whitespace-v1")
        self.assertEqual(count_tokens("a b  c"), 3)  # the budget unit is unchanged


@unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
class TestUsageThroughTheRealLoop(unittest.TestCase):
    def run_it(self, arm, script, **stub_kwargs):
        with tempfile.TemporaryDirectory() as tmp, StubServer(script, **stub_kwargs) as stub:
            harness, result = run_arm(repo(Path(tmp)), arm, stub)
        return stub, result

    def test_usage_per_turn_is_summed_into_outcome_tokens(self):
        script = [
            tools(WRITE, usage={"prompt_tokens": 100, "completion_tokens": 20,
                                "prompt_tokens_details": {"cached_tokens": 40}}),
            text("done", usage={"prompt_tokens": 150, "completion_tokens": 30}),
        ]
        stub, result = self.run_it("A", script)
        tokens = result.telemetry["tokens"]
        self.assertEqual((tokens["in"], tokens["out"], tokens["source"]), (250, 50, "provider_usage"))
        self.assertEqual((tokens["rescue_in"], tokens["rescue_out"]), (0, 0))
        rows = result.telemetry["turnos"]
        # V0.2: throughput telemetry rides on each row (descriptive); the V1 fields are unchanged
        self.assertEqual([{k: v for k, v in row.items() if k not in ("latency_ms", "ttft_ms")} for row in rows], [
            {"turn_index": 1, "kind": "productive", "tokens_in": 100, "tokens_out": 20, "tool_calls": 1},
            {"turn_index": 2, "kind": "productive", "tokens_in": 150, "tokens_out": 30, "tool_calls": 0},
        ])
        for row in rows:  # measured by tau on the provider stream
            self.assertIsInstance(row["latency_ms"], int)
            self.assertIsInstance(row["ttft_ms"], int)
            self.assertLessEqual(row["ttft_ms"], row["latency_ms"])
        self.assertEqual(result.manifest["execucao"]["tokens"], tokens)
        self.assertIs(stub.requests[0]["stream_options"]["include_usage"], True)

    def test_endpoint_without_usage_is_missing_and_tokens_are_never_estimated(self):
        stub, result = self.run_it("A", [tools(WRITE), text("done " * 50)], usage=False)
        tokens = result.telemetry["tokens"]
        self.assertEqual((tokens["in"], tokens["out"], tokens["source"]), (None, None, "missing"))
        self.assertTrue(all(row["tokens_in"] is None for row in result.telemetry["turnos"]))
        self.assertTrue(result.telemetry["amostragem"]["stream_usage_pedido"])  # we asked; it did not answer

    def test_one_silent_turn_makes_the_whole_side_missing(self):
        script = [tools(WRITE, usage={"prompt_tokens": 100, "completion_tokens": 20}),
                  text("done", usage=None)]
        stub, result = self.run_it("A", script)
        self.assertEqual(result.telemetry["tokens"]["source"], "missing")
        self.assertIsNone(result.telemetry["tokens"]["in"])
        self.assertEqual(result.telemetry["turnos"][0]["tokens_in"], 100)  # the row keeps what is known

    def test_block_turns_are_the_ones_after_a_gate_rejection(self):
        script = [tools(WRITE), text("done"), tools(call("record_intent", RECORD)), text("done again")]
        stub, result = self.run_it("B", script)
        self.assertEqual([r["kind"] for r in result.telemetry["turnos"]],
                         ["productive", "productive", "block", "block"])
        self.assertEqual(result.block_turns, 2)  # P2 counts turns (review T6b)
        self.assertEqual(result.bloqueios, 1)

    def test_a_call_cut_by_the_deadline_marks_the_sums_as_a_lower_bound(self):
        from tau_intent.harness_factory import ProviderSpec  # noqa: F401
        script = [tools(WRITE), text("late", delay=5)]
        with tempfile.TemporaryDirectory() as tmp, StubServer(script) as stub:
            harness, result = run_arm(repo(Path(tmp)), "A", stub, deadline_s=1.0)
        tokens = result.telemetry["tokens"]
        self.assertTrue(tokens["incomplete_call"])
        self.assertEqual(tokens["in"], 11)  # the one answered call
        self.assertEqual(len(result.telemetry["turnos"]), 1)

    def test_failed_provider_call_is_not_a_billed_turn(self):
        stub, result = self.run_it("A", [text("x")], status=lambda i: 500)
        self.assertEqual(result.telemetry["turnos"], [])
        self.assertEqual(result.telemetry["encerramento"], "error")

    def test_block_budget_unit_is_unchanged_and_independent_of_usage(self):
        stub, result = self.run_it("A", [text("done", usage={"prompt_tokens": 9999, "completion_tokens": 1})])
        self.assertEqual(result.telemetry["tokenizer"], "whitespace-v1")
        self.assertEqual(result.telemetry["tokens"]["budget_unit"], "whitespace-v1")


if __name__ == "__main__":
    unittest.main()
