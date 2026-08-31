import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tau_intent.supervisor import Flags, run_supervisor


class TurnEndEvent:
    def __init__(self, tool_results):
        self.tool_results = tool_results


class FakeSession:
    def __init__(self, turns):
        self._turns = list(turns)
        self.follow_ups = []

    def run_turn(self):
        if not self._turns:
            return []
        return self._turns.pop(0)

    def follow_up(self, message):
        self.follow_ups.append(message)


class FakeProvider:
    def __init__(self, turns):
        self.turns = turns
        self.received_max_turns = "unset"
        self.session = None

    def create_session(self, *, max_turns, serve, project):
        self.received_max_turns = max_turns
        self.session = FakeSession(self.turns)
        return self.session


def _init_synthetic_repo(tmpdir: str) -> str:
    repo = Path(tmpdir) / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init"], cwd=repo)
    subprocess.check_call(["git", "config", "user.email", "ci@example.com"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "CI"], cwd=repo)
    f = repo / "file.txt"
    f.write_text("one\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "file.txt"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "init"], cwd=repo)
    f.write_text("one\ntwo\n", encoding="utf-8")
    return str(repo)


class TestPr4Integration(unittest.TestCase):
    def test_arm_a_never_writes_intents(self):
        with tempfile.TemporaryDirectory() as td:
            repo_path = _init_synthetic_repo(td)
            intents = str(Path(td) / "intents.jsonl")

            provider = FakeProvider([[TurnEndEvent([{"tool": "x"}]), TurnEndEvent([])]])
            gate_calls = []

            def gate(intent):
                gate_calls.append(intent)
                return {"code": "PERMITE", "failures": []}

            result = run_supervisor(
                provider=provider,
                flags=Flags(capture=False, gate=False, project=False, serve=False),
                repo_path=repo_path,
                intents_path=intents,
                max_productive_turns=1,
                gate_eval=gate,
            )

            self.assertEqual(provider.received_max_turns, None)
            self.assertEqual(gate_calls, [])
            self.assertFalse(Path(intents).exists())
            self.assertEqual(result["productive_turns"], 1)

    def test_b_and_c_append_intent_and_gate_only_last_turn_end(self):
        with tempfile.TemporaryDirectory() as td:
            repo_path = _init_synthetic_repo(td)

            for flags in (
                Flags(capture=True, gate=True, project=False, serve=True),
                Flags(capture=True, gate=True, project=True, serve=True),
            ):
                intents = str(Path(td) / f"intents-{int(flags.project)}.jsonl")
                provider = FakeProvider([[TurnEndEvent([{"tool": "x"}]), TurnEndEvent([])]])
                gate_calls = []

                def gate(intent):
                    gate_calls.append(intent)
                    return {"code": "PERMITE", "failures": []}

                result = run_supervisor(
                    provider=provider,
                    flags=flags,
                    repo_path=repo_path,
                    intents_path=intents,
                    max_productive_turns=1,
                    gate_eval=gate,
                )

                self.assertEqual(len(gate_calls), 1)
                self.assertEqual(provider.received_max_turns, None)
                payload = [json.loads(line) for line in Path(intents).read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(payload), 1)
                self.assertIn("file.txt", payload[0]["anchors"])
                self.assertEqual(result["productive_turns"], 1)

    def test_gate_block_uses_follow_up_and_separate_budget(self):
        with tempfile.TemporaryDirectory() as td:
            repo_path = _init_synthetic_repo(td)
            intents = str(Path(td) / "intents.jsonl")

            provider = FakeProvider(
                [
                    [TurnEndEvent([])],
                    [TurnEndEvent([])],
                ]
            )
            gate_answers = iter(
                [
                    {"code": "BLOQUEIA", "failures": [{"code": "AUSENTE", "message": "missing why"}]},
                    {"code": "PERMITE", "failures": []},
                ]
            )

            result = run_supervisor(
                provider=provider,
                flags=Flags(capture=True, gate=True, project=False, serve=True),
                repo_path=repo_path,
                intents_path=intents,
                max_productive_turns=1,
                gate_eval=lambda _intent: next(gate_answers),
                max_gate_block_turns=2,
            )

            self.assertEqual(result["productive_turns"], 1)
            self.assertEqual(result["gate_block_turns"], 1)
            self.assertEqual(len(provider.session.follow_ups), 1)
            self.assertIn("BLOQUEIA", provider.session.follow_ups[0])
            self.assertEqual(result["telemetry"]["tokenizer"], "whitespace-v1")
            self.assertAlmostEqual(result["telemetry"]["cobertura_efetiva"], 0.5)
