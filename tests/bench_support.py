"""Shared pieces of the bench tests: the demo task set and a scripted local model."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from tests.stub_openai import call, text, tools

DEMO = Path(__file__).parent / "fixtures" / "demo_taskset"
MODEL = "stub-model"

CORE_OLD = "def add(a, b):\n    return a + b\n"
CORE_NEW = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
OPS = "def mul(a, b):\n    return a * b\n"


def rescue_text(body: dict) -> str:
    content = body["messages"][0]["content"]
    return content.rsplit("<registro>", 1)[-1].split("</registro>", 1)[0].strip()


class DemoModel:
    """A local model that solves the demo tasks, whatever arm or order calls it.

    It reads the conversation (never the arm): the task from the statement, the step
    from the number of assistant messages so far, and it calls ``record_intent`` only
    when the catalogue it was handed has that tool, as a compliant model would.
    ``sessions`` records what each agent session looked like from the wire.
    """

    def __init__(self, *, q_first_attempt_wrong: bool = False, slow_plain_arm: float = 0.0) -> None:
        self.q_first_attempt_wrong = q_first_attempt_wrong
        self.slow_plain_arm = slow_plain_arm
        self.q_attempts = 0
        self.agent_sessions: list[dict] = []

    def __call__(self, index: int, body: dict):
        if not body.get("stream"):
            return text(rescue_text(body))  # the rescue call: echo the record back
        messages = body["messages"]
        first_user = next(m["content"] for m in messages if m["role"] == "user")
        step = sum(1 for m in messages if m["role"] == "assistant")
        names = [t["function"]["name"] for t in body.get("tools", [])]
        intent = "record_intent" in names
        if step == 0 and names:  # the endpoint preflight carries no tools: not an agent session
            self.agent_sessions.append({"intent_tool": intent, "prompt": first_user})
        delay = {} if intent or not self.slow_plain_arm else {"delay": self.slow_plain_arm}
        if step >= 1:
            return text("done")
        if "`mul(a, b)`" in first_user:
            calls = [call("write", {"path": "calc/ops.py", "content": OPS})]
            if intent:
                calls.append(call("record_intent", {
                    "file": "calc/ops.py", "symbol": "mul", "domain": "calc",
                    "why": "a multiplicação mora em um módulo próprio para não inchar o núcleo",
                    "property": "mul devolve o produto dos dois argumentos"}))
            return tools(*calls, **delay)
        if "`sub(a, b)`" in first_user:
            calls = [call("edit", {"path": "calc/core.py",
                                   "edits": [{"oldText": CORE_OLD, "newText": CORE_NEW}]})]
            if intent:
                calls.append(call("record_intent", {
                    "file": "calc/core.py", "symbol": "sub", "domain": "calc",
                    "why": "a subtração entra no núcleo junto da soma porque as duas são inversas",
                    "property": "sub devolve a diferença e add continua intacta"}))
            return tools(*calls, **delay)
        if "answer.py" in first_user:
            self.q_attempts += 1
            wrong = self.q_first_attempt_wrong and self.q_attempts == 1
            return tools(call("write", {"path": "answer.py",
                                        "content": f"def value():\n    return {41 if wrong else 42}\n"}), **delay)
        return text("nothing to do")


def clone_bundle(bundle: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="bundle-clone-"))
    subprocess.run(["git", "clone", "-q", str(bundle), str(dest / "repo")], check=True, capture_output=True)
    return dest / "repo"


def git_log(repo: Path) -> list[str]:
    out = subprocess.run(["git", "log", "--reverse", "--format=%s", "origin/main"], cwd=repo,
                         check=True, capture_output=True, text=True).stdout
    return out.splitlines()


def read_records(cell_dir: Path) -> list[dict]:
    path = cell_dir / "records.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
