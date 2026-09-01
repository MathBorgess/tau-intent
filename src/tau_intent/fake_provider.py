"""In-memory provider/harness. No API key, no network, no live model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable


@dataclass
class FakeTurnEnd:
    type: str = "turn_end"
    message: Any = None
    tool_results: list[Any] = field(default_factory=list)


@dataclass
class FakeToolStart:
    type: str = "tool_execution_start"
    tool_call_id: str = "call-1"
    tool_name: str = "write"
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeAgentEnd:
    type: str = "agent_end"
    messages: list[Any] = field(default_factory=list)


class FakeProvider:
    """Yields a canned assistant/tool script. Temperature is owner-set (0) on the real provider."""

    temperature_owner_set = 0
    amostragem_conferida_no_fio = False

    def __init__(self, script: list[list[Any]] | None = None) -> None:
        self.script = script or default_script()


class FakeHarness:
    """Duck-typed stand-in for tau_agent.AgentHarness used by tests and --fake-provider."""

    def __init__(
        self,
        script: list[list[Any]] | None = None,
        *,
        max_turns: int | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        if max_turns is not None:
            raise ValueError(
                "identical raw max_turns across arms is a bug; pass None and cap productive turns"
            )
        self.script = list(script or default_script())
        self.tools = list(tools or [])
        self.follow_ups: list[str] = []
        self._cursor = 0
        self.config = type("Cfg", (), {"max_turns": None, "tools": self.tools})()

    def follow_up(self, content: str) -> list[str]:
        self.follow_ups.append(content)
        return list(self.follow_ups)

    async def prompt(self, content: str) -> AsyncIterator[Any]:
        del content
        while True:
            if self._cursor >= len(self.script):
                yield FakeAgentEnd()
                return
            for event in self.script[self._cursor]:
                yield event
            self._cursor += 1
            if self.follow_ups:
                self.follow_ups.pop(0)
                continue
            yield FakeAgentEnd()
            return


def default_script() -> list[list[Any]]:
    """One productive write, then a last TurnEndEvent with empty tool_results."""
    return [
        [
            FakeToolStart(
                args={
                    "path": "src/mod.py",
                    "content": "def f():\n    return 1\n",
                }
            ),
            FakeTurnEnd(tool_results=[{"tool_name": "write"}]),
            FakeTurnEnd(tool_results=[]),
        ]
    ]


def passing_script() -> list[list[Any]]:
    """Write + record_intent, then last turn. Gate should PASSA when symbols match."""
    return [
        [
            FakeToolStart(
                tool_name="write",
                args={"path": "src/mod.py", "content": "def f():\n    return 1\n"},
            ),
            FakeToolStart(
                tool_call_id="call-2",
                tool_name="record_intent",
                args={
                    "file": "src/mod.py",
                    "symbol": "f",
                    "why": "expõe f como incremento único desta tarefa",
                    "property": "f retorna int",
                    "domain": "demo",
                },
            ),
            FakeTurnEnd(tool_results=[{"tool_name": "write"}, {"tool_name": "record_intent"}]),
            FakeTurnEnd(tool_results=[]),
        ]
    ]
