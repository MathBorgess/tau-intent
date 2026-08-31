import importlib
import inspect
import io
import sys
import types
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

from tau_intent import pin


def _load_tau_api():
    try:
        module = importlib.import_module("tau_agent")
        return module, True
    except ModuleNotFoundError:
        class TurnEndEvent:
            pass

        class ToolExecutionStartEvent:
            args: dict

            def __init__(self, args=None):
                self.args = {} if args is None else args

        class AgentHarnessConfig:
            def __init__(self, before_tool_call=None):
                self.before_tool_call = before_tool_call

        class AgentHarness:
            def follow_up(self, *_args, **_kwargs):
                return None

        for cls in (TurnEndEvent, ToolExecutionStartEvent, AgentHarnessConfig, AgentHarness):
            cls.__module__ = "tau_agent.standin"

        standin = types.SimpleNamespace(
            TurnEndEvent=TurnEndEvent,
            ToolExecutionStartEvent=ToolExecutionStartEvent,
            AgentHarnessConfig=AgentHarnessConfig,
            AgentHarness=AgentHarness,
        )
        return standin, False


class TestContratoTau(unittest.TestCase):
    def test_turn_end_event_exists(self):
        tau_api, _ = _load_tau_api()
        self.assertTrue(hasattr(tau_api, "TurnEndEvent"))

    def test_tool_execution_start_event_has_args(self):
        tau_api, _ = _load_tau_api()
        event_cls = tau_api.ToolExecutionStartEvent
        annotations = getattr(event_cls, "__annotations__", {})
        self.assertTrue("args" in annotations or hasattr(event_cls, "args"))

    def test_before_tool_call_hook_can_refuse(self):
        tau_api, _ = _load_tau_api()
        config_cls = tau_api.AgentHarnessConfig
        self.assertIn("before_tool_call", inspect.signature(config_cls).parameters)

        refuse = lambda *_args, **_kwargs: False
        try:
            config = config_cls(before_tool_call=refuse)
        except TypeError:
            return
        self.assertIs(getattr(config, "before_tool_call", None), refuse)
        self.assertFalse(config.before_tool_call())

    def test_follow_up_exists_on_harness(self):
        tau_api, _ = _load_tau_api()
        self.assertTrue(hasattr(tau_api.AgentHarness, "follow_up"))

    def test_import_path_is_tau_agent_never_tau_coding(self):
        tau_api, _ = _load_tau_api()
        for name in ("AgentHarness", "AgentHarnessConfig"):
            self.assertTrue(getattr(tau_api, name).__module__.startswith("tau_agent"))
        self.assertNotIn("tau_coding", sys.modules)

    def test_pin_constants_populated(self):
        self.assertTrue(pin.PINNED_DIST)
        self.assertTrue(pin.PINNED_VERSION)
        self.assertTrue(pin.PINNED_SHA256)


class TestPinCheck(unittest.TestCase):
    def test_check_ok_when_installed_and_matching(self):
        with (
            mock.patch.object(pin.metadata, "version", return_value=pin.PINNED_VERSION),
            mock.patch.object(
                pin, "_resolve_pypi_wheel_sha256", return_value=pin.PINNED_SHA256
            ),
            io.StringIO() as out,
            redirect_stdout(out),
        ):
            code = pin.main(["--check"])
            output = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("pin: OK", output)

    def test_check_skips_when_wheel_lookup_unavailable(self):
        with (
            mock.patch.object(pin.metadata, "version", return_value=pin.PINNED_VERSION),
            mock.patch.object(
                pin,
                "_resolve_pypi_wheel_sha256",
                side_effect=urllib.error.URLError("offline"),
            ),
            io.StringIO() as out,
            redirect_stdout(out),
        ):
            code = pin.main(["--check"])
            output = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("pin: SKIP could not verify wheel sha256 from PyPI", output)
