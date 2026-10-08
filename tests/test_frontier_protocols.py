"""Frontier strand: the bench over native protocols, offline, against local stubs.

The stubs play the subscription proxies of ``mathai-harness`` (one protocol each):
no live model, no credential, no external network. What is checked is what goes
over the wire and what the records say, for each protocol:

* the request path, and the sampling policy as the body carries it (``stamped`` puts
  temperature/seed where the protocol has fields; ``provider-default`` sends none);
* the Anthropic subscription identity block and OAuth beta;
* outcome tokens from the provider's own usage (Gemini's read off the wire);
* arm C's rescue answered by the cell's own model over the same protocol;
* a unit lost to infrastructure discarded and run again from the state before it;
* the host regression layer of a task set that declares one.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
    import tau_agent  # noqa: F401
    READY = True
except ImportError:  # pragma: no cover - depends on the environment
    READY = False

from tau_intent import provider_api as api_mod
from tau_intent.bench.cli import main as bench_main
from tau_intent.bench.record import validate_record
from tau_intent.cli import flags_from_args
from tests.bench_support import CORE_NEW, CORE_OLD, DEMO, OPS, clone_bundle, read_records
from tests.stub_native import ANTHROPIC, CODEX, GOOGLE, NativeStub
from tests.stub_openai import call, text, tools

MODELS = {ANTHROPIC: "claude-opus-5-5", CODEX: "gpt-6.1-sol", GOOGLE: "gemini-3.8-flash"}
SEED = 7


# ----------------------------------------------------------------- reading bodies
def tool_names(api: str, body: dict) -> list[str]:
    if api == ANTHROPIC or api == CODEX:
        return [t["name"] for t in body.get("tools", [])]
    return [d["name"] for t in body.get("tools", []) for d in t.get("functionDeclarations", [])]


def user_texts(api: str, body: dict) -> list[str]:
    out = []
    if api == ANTHROPIC:
        for m in body.get("messages", []):
            if m["role"] == "user":
                content = m["content"]
                if isinstance(content, str):
                    out.append(content)
                else:
                    out += [b.get("text", "") for b in content if b.get("type") == "text"]
    elif api == CODEX:
        for item in body.get("input", []):
            if item.get("role") == "user":
                out += [c.get("text", "") for c in item.get("content", []) if c.get("type") == "input_text"]
    else:
        for c in body.get("contents", []):
            if c.get("role") == "user":
                out += [p["text"] for p in c.get("parts", []) if "text" in p]
    return out


def steps(api: str, body: dict) -> int:
    if api == ANTHROPIC:
        return sum(1 for m in body.get("messages", []) if m["role"] == "assistant")
    if api == CODEX:
        return sum(1 for item in body.get("input", []) if item.get("type") == "function_call_output")
    return sum(1 for c in body.get("contents", []) if c.get("role") == "model")


class NativeDemoModel:
    """The demo task set's solver (as ``bench_support.DemoModel``), for any native protocol."""

    def __init__(self, api: str) -> None:
        self.api = api

    def __call__(self, index: int, body: dict):
        texts = user_texts(self.api, body)
        first = texts[0] if texts else ""
        names = tool_names(self.api, body)
        if not names and "<registro>" in first:
            return text(first.rsplit("<registro>", 1)[-1].split("</registro>", 1)[0].strip())
        if not names:
            return text("ok")  # preflight
        intent = "record_intent" in names
        if steps(self.api, body) >= 1:
            return text("done")
        if "`mul(a, b)`" in first:
            calls = [call("write", {"path": "calc/ops.py", "content": OPS})]
            if intent:
                calls.append(call("record_intent", {
                    "file": "calc/ops.py", "symbol": "mul", "domain": "calc",
                    "why": "a multiplicação mora em um módulo próprio para não inchar o núcleo",
                    "property": "mul devolve o produto dos dois argumentos"}))
            return tools(*calls)
        if "`sub(a, b)`" in first:
            calls = [call("edit", {"path": "calc/core.py", "edits": [{"oldText": CORE_OLD, "newText": CORE_NEW}]})]
            if intent:
                calls.append(call("record_intent", {
                    "file": "calc/core.py", "symbol": "sub", "domain": "calc",
                    "why": "a subtração entra no núcleo junto da soma porque as duas são inversas",
                    "property": "sub devolve a diferença e add continua intacta"}))
            return tools(*calls)
        return text("nothing to do")


def run_cell(out: Path, stub: NativeStub, *extra: str, arms: str = "A,B,C", taskset: Path = DEMO):
    argv = ["--offline", "--arms", arms, "--seed", str(SEED), "--taskset", str(taskset), "--out", str(out),
            "--provider-api", stub.api, "--provider-url", stub.url, "--model", MODELS[stub.api],
            "--skip-pin-check", "--strand", "frontier", "--sampling", "provider-default", *extra]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = bench_main(argv)
    return code, buffer.getvalue()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


# ======================================================================= units
class TestSamplingPolicy(unittest.TestCase):
    def test_stamped_writes_the_fields_each_protocol_has(self):
        self.assertEqual(api_mod.stamp_for(api_mod.OPENAI_COMPLETIONS, "stamped", temperature=0, seed=7),
                         {"temperature": 0, "seed": 7})
        self.assertEqual(api_mod.stamp_for(GOOGLE, "stamped", temperature=0, seed=7),
                         {"generationConfig.temperature": 0, "generationConfig.seed": 7})
        self.assertEqual(api_mod.stamp_for(ANTHROPIC, "stamped", temperature=0, seed=7), {"temperature": 0})
        self.assertFalse(api_mod.seed_on_wire(ANTHROPIC, "stamped"))
        self.assertTrue(api_mod.seed_on_wire(GOOGLE, "stamped"))

    def test_provider_default_stamps_nothing_and_the_wire_log_checks_it(self):
        from tau_intent.harness_factory import WireLog

        for api in (ANTHROPIC, CODEX, GOOGLE):
            self.assertEqual(api_mod.stamp_for(api, "provider-default", temperature=0, seed=7), {})
            clean = WireLog(stamp={}, api=api, sampling="provider-default", bodies=[{"model": "m"}])
            self.assertTrue(clean.report()["conferida_no_fio"])
            knob = api_mod.SAMPLING_KNOBS[api][0]
            dirty = {}
            api_mod.set_path(dirty, knob, 0)
            leaked = WireLog(stamp={}, api=api, sampling="provider-default", bodies=[{"model": "m"}, dirty])
            self.assertFalse(leaked.report()["conferida_no_fio"], api)
            self.assertFalse(WireLog(stamp={}, api=api, sampling="provider-default").report()["conferida_no_fio"])

    def test_google_usage_counts_thoughts_as_output_and_cache_inside_input(self):
        usage = api_mod.google_usage({"usageMetadata": {"promptTokenCount": 300, "cachedContentTokenCount": 40,
                                                        "candidatesTokenCount": 11, "thoughtsTokenCount": 6}})
        self.assertEqual(usage, {"input": 260, "cache_read": 40, "output": 17, "reasoning": 6})
        self.assertIsNone(api_mod.google_usage({"usageMetadata": {}}))


# ===================================================================== harness
@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestNativeHarness(unittest.TestCase):
    WRITE = call("write", {"path": "src/mod.py", "content": "def f():\n    return 1\n"})

    def repo(self, root: Path) -> Path:
        (root / "src").mkdir(parents=True)
        (root / "src" / "mod.py").write_text("def f():\n    return 0\n", encoding="utf-8")
        return root

    def run_arm(self, api: str, sampling: str, **spec_kwargs):
        from tau_intent.harness_factory import ProviderSpec, build_harness
        from tau_intent.supervisor import run_task

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = self.repo(Path(tmp))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"],
                       cwd=root, check=True)
        flags = flags_from_args(["--arm", "A"])
        with NativeStub(api, [tools(self.WRITE), text("done")], model_version="gemini-3.8-flash-001") as stub:
            spec = ProviderSpec(stub.url, MODELS[api], SEED, timeout_s=5, api=api, sampling=sampling,
                                **spec_kwargs)

            async def main():
                harness = build_harness(root, flags, spec, max_retries=0)
                try:
                    result = await run_task(root, flags, harness=harness, prompt="make f return 1")
                finally:
                    await harness.aclose()
                return harness, result

            harness, result = asyncio.run(main())
        self.assertEqual((root / "src" / "mod.py").read_text(), "def f():\n    return 1\n")
        return stub, harness, result

    def test_anthropic_identity_block_only_when_declared(self):
        stub, harness, result = self.run_arm(ANTHROPIC, "provider-default", anthropic_oauth_identity=True)
        for body in stub.requests:
            self.assertEqual([b["text"] for b in body["system"]], [api_mod.ANTHROPIC_OAUTH_IDENTITY, system_prompt()])
        self.assertEqual(result.manifest["amostragem_conferida_no_fio"], True)

    def test_anthropic_beta_effort_caps_and_no_sampling_field(self):
        stub, harness, result = self.run_arm(ANTHROPIC, "provider-default", reasoning_effort="high",
                                             max_output_tokens=32000)
        self.assertEqual(stub.model_paths(), ["/v1/messages"] * 2)
        for body, headers in zip(stub.requests, stub.headers):
            self.assertEqual(body["model"], "claude-opus-5-5")
            self.assertNotIn("temperature", body)
            self.assertEqual(body["thinking"]["type"], "adaptive")
            self.assertEqual(body["output_config"], {"effort": "high"})
            self.assertEqual(body["max_tokens"], 32000)
            self.assertNotIn("tool_choice", body)  # forced tool use 400s on Opus 5.5
            self.assertEqual(headers.get("anthropic-beta"), api_mod.ANTHROPIC_OAUTH_BETA)  # no harness beta
            self.assertTrue(headers["authorization"].startswith("Bearer "))
        report = harness.wire.report()
        self.assertTrue(report["conferida_no_fio"])
        self.assertIsNone(report["temperature"])
        self.assertTrue(result.manifest["amostragem_conferida_no_fio"])
        self.assertIsNone(result.manifest["temperatura_configurada"])
        tokens = result.telemetry["tokens"]
        self.assertEqual(tokens["source"], "provider_usage")
        self.assertEqual(tokens["in"], (100 + 20 + 5) + (101 + 20 + 5))

    def test_codex_path_effort_and_usage(self):
        stub, harness, result = self.run_arm(CODEX, "provider-default", reasoning_effort="high")
        self.assertEqual(stub.model_paths(), ["/codex/responses"] * 2)
        for body in stub.requests:
            self.assertNotIn("temperature", body)
            self.assertEqual(body["reasoning"]["effort"], "high")
            self.assertIs(body["store"], False)
        self.assertTrue(harness.wire.report()["conferida_no_fio"])
        self.assertEqual(result.telemetry["tokens"]["source"], "provider_usage")
        self.assertEqual(result.telemetry["tokens"]["out"], 18)

    def test_google_stamped_sampling_lives_in_generation_config_and_usage_comes_off_the_wire(self):
        stub, harness, result = self.run_arm(GOOGLE, "stamped")
        self.assertEqual(stub.model_paths(),
                         ["/v1beta/models/gemini-3.8-flash:streamGenerateContent"] * 2)
        for body in stub.requests:
            self.assertEqual(body["generationConfig"]["temperature"], 0)
            self.assertEqual(body["generationConfig"]["seed"], SEED)
        self.assertTrue(harness.wire.report()["conferida_no_fio"])
        tokens = result.telemetry["tokens"]
        self.assertEqual(tokens["source"], "provider_usage")  # tau's parser drops it; the wire does not
        self.assertEqual(harness.wire.responses[-1].model, "gemini-3.8-flash-001")
        self.assertEqual(tokens["in"], 300 + 301)
        self.assertEqual(tokens["out"], 17 * 2)

    def test_google_provider_default_sends_no_generation_sampling(self):
        stub, harness, _ = self.run_arm(GOOGLE, "provider-default")
        for body in stub.requests:
            self.assertNotIn("temperature", body.get("generationConfig", {}))
            self.assertNotIn("seed", body.get("generationConfig", {}))
        self.assertTrue(harness.wire.report()["conferida_no_fio"])


#: ``tau_ai.openai_codex._build_codex_payload``: ``"instructions": system or "You are a helpful assistant."``.
TAU_CODEX_EMPTY_SYSTEM = "You are a helpful assistant."


def system_prompt() -> str:
    from tau_intent.harness_factory import system_prompt as prompt

    return prompt()


def system_text(api: str, body: dict) -> str:
    """Every system-level text of a request body, joined (empty when there is none)."""
    if api == ANTHROPIC:
        system = body.get("system") or ""
        return system if isinstance(system, str) else "\n".join(b.get("text", "") for b in system)
    if api == CODEX:
        texts = [body.get("instructions") or ""]
        texts += [c.get("text", "") for item in body.get("input", []) if item.get("role") in ("system", "developer")
                  for c in item.get("content", []) if isinstance(c, dict)]
        return "\n".join(t for t in texts if t)
    return "\n".join(p.get("text", "") for p in (body.get("systemInstruction") or {}).get("parts", []))


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestNoHarnessOnTheWire(unittest.TestCase):
    """A cell's request carries the agent's prompt, the mechanism's tools and the task —
    nothing of Claude Code, Codex or Antigravity. Checked on every request of a whole cell
    (agent turns, arm C's rescue, the preflight), for each protocol."""

    TOOLS = {"read", "write", "edit", "bash", "record_intent"}

    def test_every_request_of_a_cell_is_the_mechanism_and_nothing_else(self):
        prompt = system_prompt()
        for api in (ANTHROPIC, CODEX, GOOGLE):
            with self.subTest(api=api), tempfile.TemporaryDirectory() as tmp, \
                    NativeStub(api, NativeDemoModel(api)) as stub:
                code, stdout = run_cell(Path(tmp), stub, arms="A,B,C")
                self.assertEqual(code, 0, stdout)
            agent = [b for b in stub.requests if tool_names(api, b)]
            bare = [b for b in stub.requests if not tool_names(api, b)]  # preflight and rescue
            self.assertTrue(agent and len(bare) >= 2, (len(agent), len(bare)))
            for body in agent:
                self.assertEqual(system_text(api, body), prompt)
                self.assertLessEqual(set(tool_names(api, body)), self.TOOLS)
            for body in bare:
                # tau's Codex provider (not the proxy, not Codex) fills an empty system prompt
                # with this sentence; it is the only text a bare call carries.
                self.assertEqual(system_text(api, body), TAU_CODEX_EMPTY_SYSTEM if api == CODEX else "")
            dump = json.dumps(stub.requests)
            for marker in ("Claude Code", "Codex CLI", "Antigravity", "requestType"):
                self.assertNotIn(marker, dump, (api, marker))
            for headers in stub.headers:
                self.assertNotIn("claude-code", headers.get("anthropic-beta", ""))


@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestNativeRescueAndPreflight(unittest.TestCase):
    def test_the_rescue_is_the_cells_model_over_the_cells_protocol(self):
        from tau_intent.harness_factory import ProviderSpec
        from tau_intent.rescue_provider import provedor_nativo

        for api in (ANTHROPIC, CODEX, GOOGLE):
            with self.subTest(api=api), NativeStub(api, NativeDemoModel(api)) as stub:
                spec = ProviderSpec(stub.url, MODELS[api], SEED, api=api, sampling="provider-default")
                wire = spec.wire_log()
                chamar = provedor_nativo(spec, timeout_s=5, wire=wire)
                answer = chamar({"model": MODELS[api], "temperature": 0, "max_tokens": 800,
                                 "messages": [{"role": "user", "content": "resuma\n<registro>\nX\n</registro>"}]})
                self.assertEqual(answer["text"], "X")
                self.assertGreater(answer["usage"]["prompt_tokens"], 0)
                self.assertGreater(answer["usage"]["completion_tokens"], 0)
                self.assertEqual(len(wire.bodies), 1)
                self.assertTrue(wire.report()["conferida_no_fio"])

    def test_preflight_reports_status_usage_and_who_answered(self):
        from tau_intent.bench import environment
        from tau_intent.harness_factory import ProviderSpec

        with NativeStub(GOOGLE, [text("ok")], model_version="gemini-3.8-flash-001") as stub:
            report = environment.preflight_native(
                ProviderSpec(stub.url, MODELS[GOOGLE], SEED, api=GOOGLE, sampling="provider-default"), timeout_s=5)
        self.assertTrue(report["reachable"])
        self.assertEqual(report["status"], 200)
        self.assertTrue(report["usage_in_stream"])
        self.assertTrue(report["sampling_ok"])
        with NativeStub(ANTHROPIC, [text("ok")], status=lambda i: 400) as stub:
            refused = environment.preflight_native(
                ProviderSpec(stub.url, MODELS[ANTHROPIC], SEED, api=ANTHROPIC, sampling="stamped"), timeout_s=5)
        self.assertEqual(refused["status"], 400)
        down = environment.preflight_native(
            ProviderSpec("http://127.0.0.1:9", MODELS[CODEX], SEED, api=CODEX), timeout_s=2)
        self.assertFalse(down["reachable"])


# ======================================================================== cells
@unittest.skipUnless(READY, "needs pytest and tau-ai (pip install .[bench])")
class TestFrontierCell(unittest.TestCase):
    def test_a_full_cell_per_protocol(self):
        for api in (ANTHROPIC, CODEX, GOOGLE):
            with self.subTest(api=api), tempfile.TemporaryDirectory() as tmp, \
                    NativeStub(api, NativeDemoModel(api)) as stub:
                code, stdout = run_cell(Path(tmp), stub, "--reasoning-effort", "high",
                                        "--model-family", "family-x")
                self.assertEqual(code, 0, stdout)
                (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
                records = read_records(cell_dir)
                cell = json.loads((cell_dir / "cell.json").read_text())
            self.assertEqual(len(records), 6)
            for record in records:
                self.assertEqual(validate_record(record), [], record["arm_id"])
                self.assertTrue(record["oracle"]["pass"], (api, record["arm_id"], record["task_index"]))
                self.assertEqual(record["tokens"]["source"], "provider_usage")
                self.assertEqual(record["model"]["runner_kind"], "other")
                self.assertEqual(record["model"]["provider_api"], api)
                self.assertEqual(record["model"]["sampling"], "provider-default")
                self.assertEqual(record["model"]["family"], "family-x")
                self.assertNotIn("infra_retries", record)
                self.assertNotIn("host_regression", record)
            # task 1 has no earlier intent to serve; task 2's block is rescued by the cell's model
            rescued = [r for r in records if r["arm_id"] == "C" and r["task_index"] == 2]
            self.assertTrue(rescued and rescued[0]["tokens"]["rescue_in"] > 0, api)
            self.assertTrue(all(r["tokens"]["rescue_in"] == 0 for r in records if r["arm_id"] != "C"))
            self.assertEqual(cell["strand"], "frontier")
            self.assertEqual(cell["protocol"]["provider_api"], api)
            self.assertTrue(cell["preflight"]["sampling_ok"])

    def test_a_spent_quota_is_discarded_and_the_unit_runs_again_from_the_state_before_it(self):
        api = ANTHROPIC
        model = NativeDemoModel(api)
        # request 0 is the preflight; 1 is arm A's first agent call; 2 a retry of it, refused again
        refusals = {1, 2}
        with tempfile.TemporaryDirectory() as tmp, \
                NativeStub(api, model, status=lambda i: 429 if i in refusals else 200) as stub:
            code, stdout = run_cell(Path(tmp), stub, "--infra-retries", "3", "--infra-wait-s", "0.01",
                                    arms="A,B", taskset=DEMO)
            self.assertEqual(code, 0, stdout)
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
            repo = clone_bundle(cell_dir / "arms" / "A" / "repo.bundle")
            log = git(repo, "log", "--reverse", "--format=%s", "origin/main").splitlines()
            tags = git(repo, "ls-remote", "--tags", str(cell_dir / "arms" / "A" / "repo.bundle"))
            parked = sorted(p.name for p in (cell_dir / "arms" / "A").iterdir() if p.is_dir())
        first = records[0]
        self.assertEqual((first["arm_id"], first["task_index"]), ("A", 1))
        self.assertTrue(first["oracle"]["pass"])
        self.assertEqual([r["kind"] for r in first["infra_retries"]], ["quota_exhausted"] * 2)
        self.assertEqual(validate_record(first), [])
        self.assertEqual(log, ["seed", "task-01", "task-02"])  # one commit per task on main
        self.assertIn("infra/A-task-01/attempt-1", tags)
        self.assertEqual(parked, ["task-01", "task-01.infra-1", "task-01.infra-2", "task-02"])
        self.assertTrue(all(r["oracle"]["pass"] for r in records))

    def test_without_retries_a_spent_quota_is_infrastructure_not_a_failed_task(self):
        api = CODEX
        with tempfile.TemporaryDirectory() as tmp, \
                NativeStub(api, NativeDemoModel(api), status=lambda i: 429 if i == 1 else 200) as stub:
            code, stdout = run_cell(Path(tmp), stub, arms="A", taskset=DEMO)
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
        self.assertEqual(records[0]["terminated_by"], "error")
        self.assertEqual(records[0]["error"]["kind"], "quota_exhausted")
        self.assertEqual(records[1]["terminated_by"], "completed")  # the cell went on

    def test_an_error_inside_a_200_stream_is_still_infrastructure(self):
        api = ANTHROPIC
        with tempfile.TemporaryDirectory() as tmp, \
                NativeStub(api, NativeDemoModel(api), stream_error=lambda i: i == 1) as stub:
            code, stdout = run_cell(Path(tmp), stub, "--infra-retries", "2", "--infra-wait-s", "0.01",
                                    arms="A", taskset=DEMO)
            (cell_dir,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
            records = read_records(cell_dir)
        self.assertEqual(code, 0, stdout)
        self.assertEqual([r["kind"] for r in records[0]["infra_retries"]], ["provider_unavailable"])
        self.assertIn("Overloaded", records[0]["infra_retries"][0]["detail"])
        self.assertTrue(records[0]["oracle"]["pass"])

    def test_host_regression_is_a_descriptive_layer_next_to_the_oracle(self):
        api = GOOGLE
        with tempfile.TemporaryDirectory() as tmp:
            taskset = Path(tmp) / "taskset"
            shutil.copytree(DEMO, taskset)
            shutil.copytree(DEMO / "seed" / "tests", taskset / "regression" / "tests")
            manifest = json.loads((taskset / "taskset.json").read_text())
            manifest["regression"] = {"tests": "regression/tests"}
            (taskset / "taskset.json").write_text(json.dumps(manifest, indent=2))
            with NativeStub(api, NativeDemoModel(api)) as stub:
                code, stdout = run_cell(Path(tmp) / "out", stub, arms="A", taskset=taskset)
            self.assertEqual(code, 0, stdout)
            (cell_dir,) = [p for p in (Path(tmp) / "out").iterdir() if p.is_dir()]
            records = read_records(cell_dir)
            cell = json.loads((cell_dir / "cell.json").read_text())
        for record in records:
            self.assertTrue(record["host_regression"]["pass"])
            self.assertEqual(record["host_regression"]["passed"], 1)
            self.assertEqual(record["host_regression"]["per_test"], [])  # only what did not pass
            self.assertEqual(record["host_regression"]["per_test_scope"], "not_passed")
            self.assertIn("regression", record["artifacts"]["paths"])
        self.assertTrue(cell["host_regression"])

    def test_cli_guards(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench_main(["--provider-api", ANTHROPIC, "--server", "ws://x", "--pin", "1", "--participant-id", "p",
                        "--nickname", "n", "--provider-url", "http://127.0.0.1:1", "--model", "m",
                        "--taskset", str(DEMO), "--out", "/tmp/x", "--skip-pin-check"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench_main(["--offline", "--provider-api", CODEX, "--provider-url", "http://127.0.0.1:1",
                        "--model", "m", "--taskset", str(DEMO), "--out", "/tmp/x", "--skip-pin-check"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench_main(["--offline", "--provider-api", CODEX, "--sampling", "provider-default",
                        "--anthropic-oauth-identity", "--provider-url", "http://127.0.0.1:1", "--model", "m",
                        "--taskset", str(DEMO), "--out", "/tmp/x", "--skip-pin-check"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench_main(["--offline", "--infra-retries", "2", "--provider-url", "http://127.0.0.1:1",
                        "--model", "m", "--taskset", str(DEMO), "--out", "/tmp/x", "--skip-pin-check"])


if __name__ == "__main__":
    unittest.main()
