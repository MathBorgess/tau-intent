"""Workspace-rooted executors for the read/write/edit/bash catalogue.

``tools.py`` carries the schemas (an experimental fixture copied from
huggingface/tau, MIT, ORIGIN_SHA there). The catalogue used to ship stub
executors only, which is enough for a fake harness and useless for a real tau
loop: nothing touched the disk. These are the real ones, written against the
same argument names (``path``, ``edits[].oldText/newText``, ``command``) and the
same behavioural contract as tau's coding tools (MIT): exact, unique,
non-overlapping replacements; parent directories created on write; tail
truncation of command output; process-group kill on timeout.

Hard limits, declared rather than hidden:

* ``read``/``write``/``edit`` refuse paths that resolve outside the workspace.
* ``bash`` runs with the workspace as cwd and a reduced environment, but it is
  **not a sandbox** (Bench V0 §6): a command can still touch anything the
  participant's account can. Container isolation is an open owner decision.
* ``PYTHONDONTWRITEBYTECODE`` is set so that running the tests does not litter
  the workspace with bytecode the code observer would have to explain.

No import of ``tau_coding``: only the portable ``tau_agent`` types.
"""

from __future__ import annotations

import asyncio
import os
import signal as _signal
import sys
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable, Mapping

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024
DEFAULT_BASH_TIMEOUT_S = 120.0
MAX_BASH_TIMEOUT_S = 600.0

#: Environment variables a command may inherit. Everything else (tokens, cloud
#: credentials, ...) is dropped: the agent runs on someone else's laptop.
_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER",
              "LOGNAME", "SHELL", "VIRTUAL_ENV", "SYSTEMROOT", "COMSPEC")


class ToolInputError(ValueError):
    """The call is malformed or refused. Reported to the model as a tool error."""


Executor = Callable[..., Awaitable[Any]]


def _result(text: str, details: dict[str, Any] | None = None) -> Any:
    from tau_agent.messages import TextContent
    from tau_agent.tools import AgentToolResult

    return AgentToolResult(content=[TextContent(text=text)], details=details or {})


def _str_arg(arguments: Mapping[str, Any], name: str) -> str:
    value = arguments.get(name)
    if "_raw_arguments" in arguments:
        raise ToolInputError("tool arguments were not valid JSON; resend the call")
    if not isinstance(value, str):
        raise ToolInputError(f"{name} is required and must be a string")
    return value


def _int_arg(arguments: Mapping[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ToolInputError(f"{name} must be an integer")
    return int(value)


def resolve_inside(workspace: Path, raw: str) -> Path:
    """Resolve ``raw`` against the workspace; refuse anything that leaves it."""
    root = Path(os.path.realpath(workspace))
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = Path(os.path.realpath(candidate))
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ToolInputError(f"path is outside the workspace: {raw}") from None
    return resolved


def truncate_tail(text: str, max_lines: int = DEFAULT_MAX_LINES,
                  max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, bool]:
    lines = text.splitlines()
    cut = False
    if len(lines) > max_lines:
        lines, cut = lines[-max_lines:], True
    out = "\n".join(lines)
    data = out.encode("utf-8")
    if len(data) > max_bytes:
        out, cut = data[-max_bytes:].decode("utf-8", errors="ignore"), True
    return out, cut


def truncate_head(text: str, max_lines: int = DEFAULT_MAX_LINES,
                  max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, bool]:
    lines = text.splitlines()
    cut = False
    if len(lines) > max_lines:
        lines, cut = lines[:max_lines], True
    out = "\n".join(lines)
    data = out.encode("utf-8")
    if len(data) > max_bytes:
        out, cut = data[:max_bytes].decode("utf-8", errors="ignore"), True
    return out, cut


def make_executors(workspace: Path, *, bash_timeout_s: float = DEFAULT_BASH_TIMEOUT_S,
                   home: Path | None = None, env_bin: Path | None = None) -> dict[str, Executor]:
    """The four executors, bound to ``workspace``. Keyed by tool name.

    ``env_bin``: the arm's own interpreter directory (task set ``environment``),
    first on PATH, so ``python`` in the agent's shell is the one its code builds in.
    """
    workspace = Path(workspace)
    env = _command_env(home, env_bin)

    async def read(tool_call_id, arguments, signal=None, on_update=None):
        del tool_call_id, signal, on_update
        path = resolve_inside(workspace, _str_arg(arguments, "path"))
        if not path.exists():
            raise ToolInputError(f"File not found: {arguments['path']}")
        if path.is_dir():
            raise ToolInputError(f"Path is a directory: {arguments['path']}")
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            raise ToolInputError("Binary file: cannot be read as text")
        text = data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        offset = _int_arg(arguments, "offset")
        limit = _int_arg(arguments, "limit")
        start = max((offset or 1) - 1, 0)
        if start >= len(lines) and lines != [""]:
            raise ToolInputError(f"offset {offset} is beyond the end of the file ({len(lines)} lines)")
        selected = lines[start: start + limit] if limit else lines[start:]
        body, cut = truncate_head("\n".join(selected))
        if cut:
            shown = len(body.splitlines())
            body += f"\n\n[Showing lines {start + 1}-{start + shown} of {len(lines)}. Use offset={start + shown + 1} to continue.]"
        elif limit and start + limit < len(lines):
            body += f"\n\n[{len(lines) - start - limit} more lines. Use offset={start + limit + 1} to continue.]"
        return _result(body or "(empty file)", {"path": str(path)})

    async def write(tool_call_id, arguments, signal=None, on_update=None):
        del tool_call_id, signal, on_update
        path = resolve_inside(workspace, _str_arg(arguments, "path"))
        content = _str_arg(arguments, "content")
        if path.is_dir():
            raise ToolInputError(f"Path is a directory: {arguments['path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return _result(f"Successfully wrote {len(content)} characters to {arguments['path']}.",
                       {"path": str(path), "characters": len(content)})

    async def edit(tool_call_id, arguments, signal=None, on_update=None):
        del tool_call_id, signal, on_update
        path = resolve_inside(workspace, _str_arg(arguments, "path"))
        edits = arguments.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ToolInputError("edits is required and must be a non-empty array")
        if not path.is_file():
            raise ToolInputError(f"File not found: {arguments['path']}")
        original = path.read_text(encoding="utf-8")
        spans: list[tuple[int, int, str]] = []
        for index, item in enumerate(edits, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("oldText"), str) \
                    or not isinstance(item.get("newText"), str):
                raise ToolInputError(f"edits[{index}] needs string oldText and newText")
            old, new = item["oldText"], item["newText"]
            if not old:
                raise ToolInputError(f"edits[{index}].oldText must not be empty")
            found = original.count(old)
            if found == 0:
                raise ToolInputError(
                    f"edits[{index}].oldText was not found in {arguments['path']}; it must match exactly")
            if found > 1:
                raise ToolInputError(
                    f"edits[{index}].oldText matches {found} places in {arguments['path']}; "
                    "add surrounding context so it is unique")
            at = original.index(old)
            spans.append((at, at + len(old), new))
        spans.sort()
        for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
            if start < end:
                raise ToolInputError("edits must not overlap")
        pieces, cursor = [], 0
        for start, end, new in spans:
            pieces.append(original[cursor:start])
            pieces.append(new)
            cursor = end
        pieces.append(original[cursor:])
        updated = "".join(pieces)
        if updated == original:
            raise ToolInputError("edits made no change to the file")
        path.write_text(updated, encoding="utf-8")
        return _result(f"Successfully replaced {len(spans)} block(s) in {arguments['path']}.",
                       {"path": str(path), "edits": len(spans)})

    async def bash(tool_call_id, arguments, signal=None, on_update=None):
        del tool_call_id, on_update
        command = _str_arg(arguments, "command")
        timeout = arguments.get("timeout")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                                    or timeout <= 0):
            raise ToolInputError("timeout must be a number greater than 0")
        limit = min(float(timeout) if timeout else bash_timeout_s, MAX_BASH_TIMEOUT_S)
        if signal is not None and signal.is_cancelled():
            raise ToolInputError("Command cancelled")
        started = monotonic()
        kwargs: dict[str, Any] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_shell(
            command, cwd=workspace, env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kwargs)
        timed_out = cancelled = False
        output = b""
        try:
            communicate = asyncio.ensure_future(process.communicate())
            while True:
                done, _ = await asyncio.wait({communicate}, timeout=0.25)
                if done:
                    output = communicate.result()[0] or b""
                    break
                if monotonic() - started > limit:
                    timed_out = True
                elif signal is not None and signal.is_cancelled():
                    cancelled = True
                if timed_out or cancelled:
                    _kill(process)
                    output = (await communicate)[0] or b""
                    break
        except asyncio.CancelledError:
            _kill(process)
            raise
        text, cut = truncate_tail(output.decode(errors="replace"))
        text = text or "(no output)"
        if cut:
            text += f"\n\n[Output truncated to the last {DEFAULT_MAX_LINES} lines / {DEFAULT_MAX_BYTES // 1024}KB.]"
        if timed_out:
            text += f"\n\nCommand timed out after {limit:g} seconds"
        elif cancelled:
            text += "\n\nCommand cancelled"
        elif process.returncode not in (0, None):
            text += f"\n\nCommand exited with code {process.returncode}"
        return _result(text, {"command": command, "exit_code": process.returncode,
                              "timed_out": timed_out, "cancelled": cancelled,
                              "duration_seconds": round(monotonic() - started, 3)})

    return {"read": read, "write": write, "edit": edit, "bash": bash}


def _kill(process: "asyncio.subprocess.Process") -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, _signal.SIGKILL)
        else:  # pragma: no cover - posix is the supported platform
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass


def _command_env(home: Path | None, env_bin: Path | None = None) -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOW if key in os.environ}
    path = env.get("PATH", os.defpath)
    interpreter_dir = os.path.dirname(sys.executable)
    if interpreter_dir and interpreter_dir not in path.split(os.pathsep):
        path = interpreter_dir + os.pathsep + path
    if env_bin is not None:
        path = str(env_bin) + os.pathsep + path
        env["VIRTUAL_ENV"] = str(Path(env_bin).parent)
    env["PATH"] = path
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    if home is not None:
        env["HOME"] = str(home)
        # Several runners share one machine (V0.2): a private TMPDIR keeps their agents
        # from colliding on a fixed /tmp path.
        scratch = Path(home) / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(scratch)
    return env
