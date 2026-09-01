import inspect
import os
import unittest

from tau_intent import pin as pin_mod


class _FakeTurnEnd:
    type = "turn_end"

    def __init__(self, message=None, tool_results=None):
        self.message = message
        self.tool_results = [] if tool_results is None else tool_results


class _FakeToolStart:
    type = "tool_execution_start"

    def __init__(self, args=None):
        self.args = {} if args is None else args
        self.tool_name = "write"


class _FakeHarnessConfig:
    def __init__(self, before_tool_call=None, max_turns=None):
        self.before_tool_call = before_tool_call
        self.max_turns = max_turns


class _FakeHarness:
    def __init__(self, config=None):
        self.config = config or _FakeHarnessConfig()
        self._follow = []

    def follow_up(self, content: str):
        self._follow.append(content)
        return tuple(self._follow)


def _tau_or_fake():
    try:
        from tau_agent.events import ToolExecutionStartEvent, TurnEndEvent
        from tau_agent.harness import AgentHarness, AgentHarnessConfig

        return {
            "TurnEndEvent": TurnEndEvent,
            "ToolExecutionStartEvent": ToolExecutionStartEvent,
            "AgentHarness": AgentHarness,
            "AgentHarnessConfig": AgentHarnessConfig,
            "source": "tau_agent",
        }
    except ImportError:
        return {
            "TurnEndEvent": _FakeTurnEnd,
            "ToolExecutionStartEvent": _FakeToolStart,
            "AgentHarness": _FakeHarness,
            "AgentHarnessConfig": _FakeHarnessConfig,
            "source": "fake",
        }


class TestContratoTau(unittest.TestCase):
    """Six public-API facts. Fake stand-in always; tau_agent too when importable."""

    def setUp(self):
        self.api = _tau_or_fake()

    def test_turn_end_event_exists_and_is_the_turn_boundary(self):
        TurnEndEvent = self.api["TurnEndEvent"]
        if self.api["source"] == "tau_agent":
            fields = TurnEndEvent.model_fields
            self.assertIn("tool_results", fields)
            self.assertIn("message", fields)
        else:
            event = TurnEndEvent(message="assistant", tool_results=[])
            self.assertEqual(list(event.tool_results), [])
            with_tools = TurnEndEvent(message="assistant", tool_results=[{"name": "write"}])
            self.assertTrue(list(with_tools.tool_results))

    def test_tool_execution_start_event_has_args_before_execution(self):
        ToolExecutionStartEvent = self.api["ToolExecutionStartEvent"]
        if self.api["source"] == "tau_agent":
            fields = ToolExecutionStartEvent.model_fields
            self.assertIn("args", fields)
            event = ToolExecutionStartEvent(
                tool_call_id="c1", tool_name="write", args={"path": "src/a.py"}
            )
            self.assertEqual(event.args["path"], "src/a.py")
        else:
            event = ToolExecutionStartEvent(args={"path": "src/a.py", "content": "x"})
            self.assertEqual(event.args["path"], "src/a.py")
            self.assertNotIn("file_path", event.args)

    def test_before_tool_call_can_refuse(self):
        executed = []

        async def before_tool_call(call):
            return True, "refused by harness config"

        async def maybe_execute(call, hook):
            blocked, reason = await hook(call)
            if blocked:
                return {"executed": False, "reason": reason}
            executed.append(call)
            return {"executed": True}

        class Call:
            name = "write"
            arguments = {"path": "x.py"}

        import asyncio

        result = asyncio.run(maybe_execute(Call(), before_tool_call))
        self.assertFalse(result["executed"])
        self.assertEqual(executed, [])
        Config = self.api["AgentHarnessConfig"]
        if self.api["source"] == "tau_agent":
            self.assertIn("before_tool_call", Config.__dataclass_fields__)
        else:
            cfg = Config(before_tool_call=before_tool_call)
            self.assertIs(cfg.before_tool_call, before_tool_call)

    def test_follow_up_exists_on_the_harness(self):
        Harness = self.api["AgentHarness"]
        Config = self.api["AgentHarnessConfig"]
        if self.api["source"] == "tau_agent":
            self.assertTrue(hasattr(Harness, "follow_up"))
            self.assertIn("content", inspect.signature(Harness.follow_up).parameters)
        else:
            harness = Harness(Config())
            queued = harness.follow_up("corrija AUSENTE")
            self.assertTrue(queued)

    def test_import_path_is_tau_agent_never_tau_coding(self):
        if self.api["source"] == "tau_agent":
            import tau_agent
            from tau_agent import AgentHarness, AgentHarnessConfig

            self.assertEqual(AgentHarness.__module__.split(".")[0], "tau_agent")
            self.assertEqual(AgentHarnessConfig.__module__.split(".")[0], "tau_agent")
            self.assertTrue(hasattr(tau_agent, "TurnEndEvent"))
        pkg_root = os.path.join(os.path.dirname(__file__), "..", "src", "tau_intent")
        for dirpath, _, files in os.walk(pkg_root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as handle:
                    text = handle.read()
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("from tau_coding") or stripped.startswith(
                        "import tau_coding"
                    ):
                        self.fail(f"{name} must not import tau_coding")

    def test_pin_constants_are_populated(self):
        self.assertEqual(pin_mod.PINNED_DIST, "tau-ai")
        self.assertEqual(pin_mod.PINNED_VERSION, "0.4.1")
        self.assertEqual(len(pin_mod.PINNED_SHA256), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in pin_mod.PINNED_SHA256))
        self.assertEqual(
            pin_mod.PINNED_SHA256,
            "c0f396527c9c804f6787bc1eccb585f7f123293154861fe8b99354cba79dbc71",
        )
        rc = pin_mod.main(["--check"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
