"""Facts about this machine, this model and this build, as the join message needs them.

Everything here is best effort and *declared*: a value that cannot be read is
``None`` (digest) or an explicit fallback the caller can override on the command
line. Nothing is guessed to look complete.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import shutil
import socket
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


HARDWARE_SOURCES = ("local", "declared")


def runner_version() -> str:
    return f"bench-v0.2/{tau_intent.__version__}"


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
        "source": "local",
        "os": f"{system} {platform.release()}".strip(),
        "chip": chip or detected_chip,
        "ram_gb": round(ram, 1) if ram is not None else 0,
        "accel": accel,
    }


def hardware_declared(*, chip: str | None = None, ram_gb: float | None = None,
                      accel: str | None = None) -> dict[str, Any]:
    """Hardware as the participant *declared* it (V0.2): this machine is never read.

    The arena's ``bench_join`` schema (and the record's) types ``chip`` as a string,
    ``ram_gb`` as a non-negative number and ``accel`` as an enum: none of them takes
    ``null``. So the four wire fields carry an explicit placeholder where nothing was
    declared (``"unknown"``, ``0``, ``"other"``) and ``declared`` carries the real
    values, ``null`` included. Read ``declared``, not the placeholder.
    """
    if accel is not None and accel not in ACCELS:
        raise ValueError(f"accel must be one of {ACCELS}")
    if ram_gb is not None and ram_gb < 0:
        raise ValueError("ram_gb must be >= 0")
    ram = None if ram_gb is None else round(float(ram_gb), 1)
    return {
        "source": "declared",
        "os": "unknown",
        "chip": chip or "unknown",
        "ram_gb": ram if ram is not None else 0,
        "accel": accel or "other",
        "declared": {"chip": chip or None, "ram_gb": ram, "accel": accel},
    }


def origin_of(provider_url: str) -> str:
    parsed = urlparse(provider_url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ------------------------------------------------------------------ the backend
def host_of(provider_url: str) -> str:
    return (urlparse(provider_url).hostname or "").lower()


def is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def transport_of(provider_url: str) -> str:
    """``"local"`` when the model is on this machine (loopback), ``"lan"`` otherwise."""
    return "local" if is_loopback(host_of(provider_url)) else "lan"


def host_sha256(provider_url: str) -> str:
    """sha256 of the lower-cased host (no scheme, no port): all that leaves the arena."""
    return hashlib.sha256(host_of(provider_url).encode("utf-8")).hexdigest()


def redact_host(text: str, provider_url: str) -> str:
    """Replace the raw host of a non-loopback backend by a stable token.

    A participant's LAN address must not reach a record, a manifest, a transcript or
    the bundle. A loopback host reveals nothing and may legitimately appear in the
    agent's own work, so it is left alone.
    """
    host = host_of(provider_url)
    if not host or is_loopback(host) or not isinstance(text, str):
        return text
    token = f"backend-{host_sha256(provider_url)[:12]}"
    out = text
    for variant in (f"[{host}]", host, host.upper()):
        out = out.replace(variant, token)
    return out


def backend_block(provider_url: str, backend_id: str | None, ollama_version: str | None) -> dict[str, Any]:
    return {"backend_id": backend_id, "transport": transport_of(provider_url),
            "provider_host_sha256": host_sha256(provider_url), "ollama_version": ollama_version}


def _get_json(url: str, *, timeout_s: float, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=timeout_s) as response:
        return json.loads(response.read())


def ollama_metadata(provider_url: str, model: str, timeout_s: float = 3.0) -> dict[str, Any]:
    """``/api/version``, ``POST /api/show`` and ``/api/tags`` of the provider's origin.

    Short timeouts, no proxy, each call independent: a missing piece is ``None``,
    never a guess, and ``errors`` names the endpoint and the error class only (the
    message of a connection error carries the host).
    """
    origin = origin_of(provider_url)
    out: dict[str, Any] = {"ollama_version": None, "details": None, "digest": None, "errors": []}

    def attempt(label: str, call: Any) -> Any:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - metadata is best effort and reported
            out["errors"].append(f"{label}: {type(exc).__name__}")
            return None

    version = attempt("/api/version", lambda: _get_json(origin + "/api/version", timeout_s=timeout_s))
    if isinstance(version, dict) and version.get("version"):
        out["ollama_version"] = str(version["version"])
    show = attempt("/api/show", lambda: _get_json(origin + "/api/show", timeout_s=timeout_s,
                                                  body={"model": model}))
    details = show.get("details") if isinstance(show, dict) else None
    if isinstance(details, dict):
        out["details"] = {key: details.get(key) for key in ("family", "parameter_size", "quantization_level")}
    tags = attempt("/api/tags", lambda: _get_json(origin + "/api/tags", timeout_s=timeout_s))
    out["digest"] = _digest_in_tags(tags, model)
    return out


def _digest_in_tags(data: Any, model: str) -> str | None:
    wanted = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in data.get("models", []) if isinstance(data, dict) else []:
        if isinstance(entry, dict) and (entry.get("name") in wanted or entry.get("model") in wanted):
            digest = str(entry.get("digest") or "")
            if digest:
                return digest if digest.startswith("sha256:") else f"sha256:{digest}"
    return None


def backend_reachable(provider_url: str, timeout_s: float = 5.0) -> bool:
    """A TCP connect to the provider, nothing more: is there anything to talk to?"""
    parsed = urlparse(provider_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname or "", port), timeout=timeout_s):
            return True
    except OSError:
        return False


def model_digest(provider_url: str, model: str, runner_kind: str, timeout_s: float = 5.0) -> str | None:
    """Ollama attests the model it serves (``/api/tags``). Other runners: ``None``."""
    if runner_kind != "ollama":
        return None
    try:
        with _OPENER.open(origin_of(provider_url) + "/api/tags", timeout=timeout_s) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return _digest_in_tags(data, model)


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


def preflight_native(spec: Any, *, timeout_s: float = 120.0) -> dict[str, Any]:
    """The frontier strand's preflight: one tiny request through tau's own provider for
    the cell's protocol, on the same stamping transport the agent will use.

    Same report as ``preflight_endpoint`` plus what a native protocol adds: the HTTP
    status (a 400 here usually means the model refuses a sampling field, which is a
    sampling-policy decision, not something to patch around), whether the sampling
    the cell declared really left as declared, and the model the provider said answered.
    """
    import asyncio
    from dataclasses import replace

    from tau_intent.harness_factory import build_provider, stamped_client

    probe = replace(spec, timeout_s=timeout_s)
    out: dict[str, Any] = {"reachable": False, "usage_in_stream": False, "error": None, "status": None,
                           "api": spec.api, "sampling_ok": None, "answered_by": None}

    async def once() -> None:
        from tau_agent.messages import TextContent, UserMessage
        from tau_ai.events import AssistantDoneEvent, AssistantErrorEvent

        client, wire = stamped_client(probe)
        try:
            provider = build_provider(probe, client, wire, max_retries=0, max_output_tokens=1024)
            final = None
            async for event in provider.stream_response(
                    model=spec.model, system="", tools=[],
                    messages=[UserMessage(content=[TextContent(text="Reply with the word ok.")])]):
                if isinstance(event, AssistantDoneEvent):
                    final = event.message
                elif isinstance(event, AssistantErrorEvent):
                    out["error"] = str(event.error.error_message or event.reason)[:300]
            out["status"] = wire.statuses[-1] if wire.statuses else None
            out["reachable"] = bool(wire.statuses) and not wire.network_errors
            out["sampling_ok"] = wire.report()["conferida_no_fio"]
            if wire.network_errors:
                last = wire.network_errors[-1]
                out["error"] = f"{last['type']}: {last['detail']}"[:300]
            if final is not None:
                u = final.usage
                out["usage_in_stream"] = bool(u.input or u.output or u.cache_read or u.cache_write)
                out["answered_by"] = final.response_model or final.model
        finally:
            await client.aclose()

    try:
        asyncio.run(once())
    except Exception as exc:  # noqa: BLE001 - reported, the cell decides
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


def check_pin() -> tuple[bool, str]:
    """The pinned tau must be the installed one, byte for byte (RECORD)."""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = pin.main(["--check", "--require-installed"])
    return code == 0, buffer.getvalue().strip()
