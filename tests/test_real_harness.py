"""S2: the real tau 0.4.7 harness, driven against a local OpenAI-compatible stub.

No live model and no external network: the stub plays the part of Ollama /
LM Studio / llama.cpp on 127.0.0.1. These tests are what the supervisor's event
mapping (``TurnEndEvent``, ``tool_results``) never had before: real tau events.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

try:
    import tau_agent  # noqa: F401
    HAVE_TAU = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_TAU = False

from tau_intent.cli import flags_from_args
from tests.stub_openai import StubServer, call, text, tools

SEED = 7
RECORD = {
    "file": "src/mod.py", "symbol": "f",
    "why": "f vira o incremento único desta tarefa e passa a devolver um inteiro",
    "property": "f retorna int", "domain": "demo",
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin",
                               "HOME": str(root)}).stdout


def repo(root: Path) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    return root


def run_arm(root: Path, arm: str, stub: StubServer, **kwargs):
    from tau_intent.harness_factory import ProviderSpec, build_harness
    from tau_intent.supervisor import run_task

    flags = flags_from_args(["--arm", arm])
    summarizer = kwargs.pop("summarizer_fn", None)
    kwargs.setdefault("prompt", "make f return 1")
    retries = kwargs.pop("max_retries", 0)

    async def main():
        harness = build_harness(root, flags, ProviderSpec(stub.url, "stub-model", SEED, timeout_s=5),
                                max_retries=retries)
        try:
            result = await run_task(root, flags, harness=harness,
                                    summarizer_fn=summarizer, **kwargs)
        finally:
            await harness.aclose()
        return harness, result

    return asyncio.run(main())


WRITE = call("write", {"path": "src/mod.py", "content": "def f():\n    return 1\n"})


@unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
class TestRealHarness(unittest.TestCase):
    def test_sampling_is_in_the_http_body_and_the_wire_log_proves_it(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer([tools(WRITE), text("done")]) as stub:
            harness, result = run_arm(repo(Path(tmp)), "A", stub)
        self.assertEqual(len(stub.requests), 2)
        for body in stub.requests:
            self.assertEqual(body["temperature"], 0)
            self.assertEqual(body["seed"], SEED)
            self.assertIs(body["stream"], True)
            self.assertEqual(body["stream_options"], {"include_usage": True})
            self.assertEqual(body["model"], "stub-model")
        self.assertEqual(stub.paths, ["/v1/chat/completions"] * 2)
        report = harness.wire.report()
        self.assertTrue(report["conferida_no_fio"])
        self.assertEqual(report["requests"], 2)
        self.assertTrue(result.manifest["amostragem_conferida_no_fio"])
        self.assertEqual(result.manifest["temperatura_configurada"], 0)
        self.assertEqual(result.telemetry["amostragem"]["seed"], SEED)

    def test_a_config_object_alone_is_not_trusted(self):
        from tau_intent.harness_factory import WireLog

        self.assertFalse(WireLog(stamp={"temperature": 0, "seed": 7}).report()["conferida_no_fio"])
        wrong = WireLog(stamp={"temperature": 0, "seed": 7}, bodies=[{"temperature": 0.7, "seed": 7}])
        self.assertFalse(wrong.report()["conferida_no_fio"])

    def test_catalogue_is_the_mechanisms_and_a_has_no_record_intent(self):
        names = {}
        for arm in ("A", "B", "C"):
            with tempfile.TemporaryDirectory() as tmp, StubServer([text("done")]) as stub:
                summarizer = None
                if arm == "C":
                    from tau_intent.rescue import sumarizador_falso
                    summarizer = sumarizador_falso()
                run_arm(repo(Path(tmp)), arm, stub, summarizer_fn=summarizer)
            names[arm] = [t["function"]["name"] for t in stub.requests[0]["tools"]]
        self.assertEqual(names["A"], ["read", "write", "edit", "bash"])
        self.assertEqual(names["B"], ["read", "write", "edit", "bash", "record_intent"])
        self.assertEqual(names["B"], names["C"])

    def test_local_model_named_like_a_responses_only_model_still_uses_chat_completions(self):
        from tau_intent.harness_factory import ProviderSpec, build_harness
        from tau_intent.supervisor import run_task

        with tempfile.TemporaryDirectory() as tmp, StubServer([text("done")]) as stub:
            root = repo(Path(tmp))
            flags = flags_from_args(["--arm", "A"])

            async def main():
                h = build_harness(root, flags, ProviderSpec(stub.url, "gpt-5.4-local-codex", SEED, timeout_s=5),
                                  max_retries=0)
                try:
                    await run_task(root, flags, prompt="x", harness=h)
                finally:
                    await h.aclose()

            asyncio.run(main())
        self.assertEqual(stub.paths, ["/v1/chat/completions"])

    def test_real_events_arm_a_writes_the_file_and_the_loop_ends_on_the_empty_turn(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer([tools(WRITE), text("done")]) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "A", stub)
            self.assertEqual((root / "src" / "mod.py").read_text(), "def f():\n    return 1\n")
        self.assertEqual(result.verdict, "PASSA")
        self.assertEqual(result.productive_turns, 1)
        self.assertEqual(result.telemetry["encerramento"], "completed")
        self.assertEqual(result.manifest["flags"], {"capture": False, "gate": False,
                                                    "project": False, "serve": False})
        self.assertEqual(result.manifest["modelo_consumidor"], "stub-model")

    def test_real_events_arm_b_capture_survives_tau_end_and_update_events(self):
        """tau also emits tool_execution_end/update events; they must not read as
        malformed capture calls (NAO_PARSEAVEL) nor change what the gate sees."""
        script = [tools(WRITE, call("record_intent", RECORD)), text("done")]
        with tempfile.TemporaryDirectory() as tmp, StubServer(script) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "B", stub)
            lines = [json.loads(line) for line in (root / "intents.jsonl").read_text().splitlines()]
        self.assertEqual(result.verdict, "PASSA")
        self.assertEqual(result.telemetry["erros_de_captura"], [])
        self.assertTrue(result.telemetry["gate_avaliado"])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["anchor"]["file"], "src/mod.py")
        self.assertEqual(lines[0]["anchor"]["symbol"], "f")
        # the record_intent result came back to the model as a tool result
        second = stub.requests[1]["messages"]
        self.assertEqual([m["role"] for m in second][-3:], ["assistant", "tool", "tool"])

    def test_arm_b_without_intent_is_blocked_and_the_follow_up_reaches_the_model(self):
        script = [tools(WRITE), text("done"), tools(call("record_intent", RECORD)), text("done again")]
        with tempfile.TemporaryDirectory() as tmp, StubServer(script) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "B", stub)
        self.assertEqual(result.bloqueios, 1)  # one gate verdict
        self.assertEqual(result.block_turns, 2)  # P2: the record_intent turn and the closing turn
        self.assertEqual(result.verdict, "PASSA")
        self.assertIn("AUSENTE", result.follow_ups[0])
        last_user = [m for m in stub.requests[2]["messages"] if m["role"] == "user"][-1]
        self.assertIn("AUSENTE", last_user["content"])

    def test_arguments_split_across_sse_deltas_are_reassembled(self):
        with tempfile.TemporaryDirectory() as tmp, \
                StubServer([tools(WRITE), text("done")], split_args=True) as stub:
            root = repo(Path(tmp))
            run_arm(root, "A", stub)
            self.assertEqual((root / "src" / "mod.py").read_text(), "def f():\n    return 1\n")

    def test_malformed_tool_arguments_are_a_tool_error_and_a_capture_diagnostic(self):
        script = [tools(call("write", "{not json"), call("record_intent", RECORD)), text("done")]
        with tempfile.TemporaryDirectory() as tmp, StubServer(script) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "B", stub)
        tool_msgs = [m for m in stub.requests[1]["messages"] if m["role"] == "tool"]
        self.assertIn("not valid JSON", tool_msgs[0]["content"])
        self.assertEqual([e["tool"] for e in result.telemetry["erros_de_captura"]], ["write"])

    def test_provider_failure_is_an_error_not_a_finished_task(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer([text("x")], status=lambda i: 500) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "B", stub)
        self.assertEqual(result.verdict, "ERRO")
        self.assertEqual(result.telemetry["encerramento"], "error")
        self.assertIn("500", result.telemetry["erro_de_provedor"])
        self.assertFalse(result.telemetry["gate_avaliado"])
        self.assertFalse(result.telemetry["captura_publicada"])

    def test_deadline_bounds_a_hung_model(self):
        with tempfile.TemporaryDirectory() as tmp, StubServer([text("late", delay=5)]) as stub:
            root = repo(Path(tmp))
            started = time.monotonic()
            harness, result = run_arm(root, "A", stub, deadline_s=0.6)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3.5)
        self.assertEqual(result.verdict, "DEADLINE")
        self.assertEqual(result.telemetry["encerramento"], "deadline")

    def test_productive_cap_stops_the_real_loop(self):
        script = [tools(call("read", {"path": "src/mod.py"})) for _ in range(5)]
        with tempfile.TemporaryDirectory() as tmp, StubServer(script) as stub:
            root = repo(Path(tmp))
            harness, result = run_arm(root, "A", stub, max_productive_turns=2)
        self.assertEqual(result.verdict, "TETO")
        self.assertEqual(result.telemetry["encerramento"], "teto_turnos")
        self.assertEqual(len(stub.requests), 2)

    def test_hidden_proxy_environment_does_not_capture_a_local_endpoint(self):
        import os
        os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:9"
        try:
            with tempfile.TemporaryDirectory() as tmp, StubServer([text("done")]) as stub:
                harness, result = run_arm(repo(Path(tmp)), "A", stub)
            self.assertEqual(result.telemetry["encerramento"], "completed")
        finally:
            del os.environ["HTTP_PROXY"], os.environ["http_proxy"]


@unittest.skipUnless(HAVE_TAU, "needs the pinned tau-ai (pip install .[tau])")
class TestWorkspaceTools(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "ws"
        self.root.mkdir()
        from tau_intent.workspace_tools import make_executors
        self.ex = make_executors(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return asyncio.run(self.ex[name]("id", args, None, None))

    def test_write_read_edit_round_trip(self):
        self.run_tool("write", path="pkg/a.py", content="x = 1\ny = 2\n")
        self.assertIn("y = 2", self.run_tool("read", path="pkg/a.py").text)
        self.run_tool("edit", path="pkg/a.py", edits=[{"oldText": "x = 1", "newText": "x = 10"}])
        self.assertEqual((self.root / "pkg" / "a.py").read_text(), "x = 10\ny = 2\n")

    def test_edit_refuses_ambiguous_missing_or_overlapping_text(self):
        (self.root / "a.py").write_text("a\na\nb\n")
        for edits, message in (
            ([{"oldText": "a", "newText": "c"}], "matches 2 places"),
            ([{"oldText": "zzz", "newText": "c"}], "not found"),
            ([{"oldText": "a\na", "newText": "c"}, {"oldText": "a\nb", "newText": "d"}], "not overlap"),
        ):
            with self.assertRaises(Exception) as ctx:
                self.run_tool("edit", path="a.py", edits=edits)
            self.assertIn(message, str(ctx.exception))
        self.assertEqual((self.root / "a.py").read_text(), "a\na\nb\n")

    def test_paths_outside_the_workspace_are_refused(self):
        for path in ("../escape.txt", "/etc/passwd", "sub/../../x"):
            with self.assertRaises(Exception) as ctx:
                self.run_tool("write", path=path, content="x")
            self.assertIn("outside the workspace", str(ctx.exception))
        (self.root.parent / "outside").mkdir()
        (self.root / "link").symlink_to(self.root.parent / "outside")
        with self.assertRaises(Exception):
            self.run_tool("write", path="link/x.txt", content="x")

    def test_bash_runs_in_the_workspace_with_a_scrubbed_environment(self):
        import os
        os.environ["TAU_INTENT_TEST_SECRET"] = "s3cret"
        try:
            out = self.run_tool("bash", command="pwd; env | grep -c TAU_INTENT_TEST_SECRET; echo $PYTHONDONTWRITEBYTECODE",
                                description="checking")
        finally:
            del os.environ["TAU_INTENT_TEST_SECRET"]
        lines = out.text.split()
        self.assertEqual(Path(lines[0]).resolve(), self.root.resolve())
        self.assertEqual(lines[1], "0")
        self.assertEqual(lines[2], "1")

    def test_bash_timeout_kills_the_process_group(self):
        started = time.monotonic()
        out = self.run_tool("bash", command="sleep 30 & sleep 30", description="hang", timeout=0.5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("timed out", out.text)

    def test_bash_reports_exit_code_and_truncates_long_output(self):
        out = self.run_tool("bash", command="seq 1 5000; exit 3", description="noise")
        self.assertIn("exited with code 3", out.text)
        self.assertIn("Output truncated", out.text)
        self.assertNotIn("\n1\n", out.text)


if __name__ == "__main__":
    unittest.main()
