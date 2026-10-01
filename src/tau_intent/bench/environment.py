"""Facts about this machine, this model and this build, as the join message needs them.

Everything here is best effort and *declared*: a value that cannot be read is
``None`` (digest) or an explicit fallback the caller can override on the command
line. Nothing is guessed to look complete.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tau_intent
from tau_intent import pin

RUNNER_KINDS = ("ollama", "lmstudio", "llamacpp", "other")
ACCELS = ("cuda", "metal", "cpu", "other")
_PORTS = {11434: "ollama", 1234: "lmstudio", 8080: "llamacpp"}

#: A local endpoint is never reached through an environment proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def runner_version() -> str:
    return f"bench-v0/{tau_intent.__version__}"


def guess_runner_kind(provider_url: str) -> str:
    port = urlparse(provider_url).port
    return _PORTS.get(port or 0, "other")


def tau_intent_sha() -> str:
    """sha256 over every file of the installed ``tau_intent`` package, sorted by path.

    A content hash rather than a git SHA: it is always available (installed wheel,
    editable checkout, zipped copy) and two machines agree iff they run the same
    bytes of the mechanism, the YAML and the prompts.
    """
    root = Path(tau_intent.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def tau_ai_version() -> str | None:
    try:
        from importlib.metadata import version
        return version(pin.PINNED_DIST)
    except Exception:  # noqa: BLE001 - not installed is data, not an error here
        return None


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hardware(*, chip: str | None = None, ram_gb: float | None = None, accel: str | None = None) -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine()
    detected_chip = ""
    detected_ram: float | None = None
    if system == "Darwin":
        detected_chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        mem = _run(["sysctl", "-n", "hw.memsize"])
        detected_ram = int(mem) / 2**30 if mem.isdigit() else None
    elif system == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith(("model name", "hardware")):
                    detected_chip = line.split(":", 1)[1].strip()
                    break
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    detected_ram = int(line.split()[1]) / 2**20
                    break
        except (OSError, ValueError, IndexError):
            pass
    detected_chip = detected_chip or platform.processor() or machine or "unknown"
    if accel is None:
        if shutil.which("nvidia-smi"):
            accel = "cuda"
        elif system == "Darwin" and machine == "arm64":
            accel = "metal"
        else:
            accel = "cpu"
    if accel not in ACCELS:
        raise ValueError(f"accel must be one of {ACCELS}")
    ram = ram_gb if ram_gb is not None else detected_ram
    return {
        "os": f"{system} {platform.release()}".strip(),
        "chip": chip or detected_chip,
        "ram_gb": round(ram, 1) if ram is not None else 0,
        "accel": accel,
    }


def origin_of(provider_url: str) -> str:
    parsed = urlparse(provider_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def model_digest(provider_url: str, model: str, runner_kind: str, timeout_s: float = 5.0) -> str | None:
    """Ollama attests the model it serves (``/api/tags``). Other runners: ``None``."""
    if runner_kind != "ollama":
        return None
    try:
        with _OPENER.open(origin_of(provider_url) + "/api/tags", timeout=timeout_s) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    wanted = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in data.get("models", []) if isinstance(data, dict) else []:
        if entry.get("name") in wanted or entry.get("model") in wanted:
            digest = str(entry.get("digest") or "")
            if digest:
                return digest if digest.startswith("sha256:") else f"sha256:{digest}"
    return None


def preflight_endpoint(provider_url: str, model: str, seed: int, *, timeout_s: float = 120.0,
                       api_key: str = "local") -> dict[str, Any]:
    """One tiny streamed request before any counted execution (design §4.5).

    It checks, on the same path tau will use, that the endpoint answers at all,
    accepts ``temperature``/``seed``, and returns ``usage`` in the streamed
    response. A missing ``usage`` is *reported*, not fixed: tokens stay missing.
    """
    body = {"model": model, "stream": True, "stream_options": {"include_usage": True},
            "temperature": 0, "seed": seed, "max_tokens": 4,
            "messages": [{"role": "user", "content": "Reply with the word ok."}]}
    request = urllib.request.Request(
        provider_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    out: dict[str, Any] = {"reachable": False, "usage_in_stream": False, "error": None}
    try:
        with _OPENER.open(request, timeout=timeout_s) as response:
            out["reachable"] = True
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                try:
                    chunk = json.loads(line[5:])
                except ValueError:
                    continue
                usage = chunk.get("usage") if isinstance(chunk, dict) else None
                if isinstance(usage, dict) and (usage.get("prompt_tokens") or usage.get("completion_tokens")):
                    out["usage_in_stream"] = True
    except urllib.error.HTTPError as exc:
        out["error"] = f"HTTP {exc.code}"
        out["reachable"] = True if exc.code < 500 else False
    except (urllib.error.URLError, OSError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def check_pin() -> tuple[bool, str]:
    """The pinned tau must be the installed one, byte for byte (RECORD)."""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = pin.main(["--check", "--require-installed"])
    return code == 0, buffer.getvalue().strip()
