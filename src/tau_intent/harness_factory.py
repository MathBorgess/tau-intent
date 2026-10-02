"""Real tau harness: ``AgentHarness`` + tau's OpenAI-compatible provider.

Nothing here re-implements the loop (AGENTS.md rule 1): the loop, the event
types and the provider are tau's, imported from the pinned wheel. What this
module adds is the part the experiment owns:

* **The sampling is on the wire.** tau's provider has no ``temperature`` or
  ``seed`` knob, and AGENTS.md rule 8 forbids trusting a config object. A
  transport wrapper stamps ``temperature`` and ``seed`` into the JSON body of
  every ``/chat/completions`` request and logs the body that actually left
  (``WireLog``). The manifest says "verified on the wire" only if that log
  proves it.
* **The catalogue is the mechanism's.** ``record_intent`` for B/C, the plain
  four tools for A (``capture`` is the only thing read), with real executors
  rooted at the arm's workspace.
* **A local endpoint is never proxied.** Ollama, LM Studio and llama.cpp run on
  the participant's own machine; environment proxies must not get in between.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tau_intent.config import CONFIG_DIR, sha256_of
from tau_intent.supervisor import Flags
from tau_intent.tools import catalog

SYSTEM_PROMPT_PATH = CONFIG_DIR / "prompts" / "agent-system-v1.txt"


def system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def system_prompt_sha256() -> str:
    return sha256_of(SYSTEM_PROMPT_PATH)


@dataclass(frozen=True)
class ProviderSpec:
    """One cell's model endpoint. The same spec serves the agent and the rescue."""

    base_url: str
    model: str
    seed: int
    temperature: float = 0.0
    timeout_s: float = 600.0
    api_key: str = "local"

    def stamp(self) -> dict[str, Any]:
        return {"temperature": self.temperature, "seed": self.seed}


@dataclass
class WireLog:
    """Request bodies as they left the process, plus what they were meant to carry."""

    stamp: dict[str, Any]
    bodies: list[dict[str, Any]] = field(default_factory=list)
    #: Transport failures seen on the agent's calls (refused, reset, timeout, closed
    #: mid-stream): ``{"type": <httpx class>, "detail": <message>}``. They are how the
    #: cell tells "the backend is gone" (infrastructure) from any other provider error.
    network_errors: list[dict[str, str]] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        n = len(self.bodies)
        ok = n > 0 and all(
            all(body.get(key) == value for key, value in self.stamp.items())
            for body in self.bodies
        )
        return {
            "temperature": self.stamp.get("temperature"),
            "seed": self.stamp.get("seed"),
            "requests": n,
            "conferida_no_fio": ok,
            "stream_usage_pedido": n > 0 and all(
                (body.get("stream_options") or {}).get("include_usage") is True
                for body in self.bodies
            ),
        }


#: A backend that does not accept a connection is known quickly; a model that is
#: slow to answer is not an unreachable one, so only the connect phase is short.
CONNECT_TIMEOUT_S = 10.0


def stamping_transport(inner: Any, stamp: dict[str, Any], wire: WireLog) -> Any:
    import httpx

    def note(exc: Exception) -> None:
        wire.network_errors.append({"type": type(exc).__name__, "detail": str(exc)[:200]})

    class GuardedStream(httpx.AsyncByteStream):
        """The body of the response: a failure while it streams is seen here."""

        def __init__(self, stream: Any) -> None:
            self._stream = stream

        async def __aiter__(self) -> Any:
            try:
                async for chunk in self._stream:
                    yield chunk
            except httpx.TransportError as exc:
                note(exc)
                raise

        async def aclose(self) -> None:
            await self._stream.aclose()

    class StampingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            body = await request.aread()
            if request.method == "POST" and body:
                try:
                    payload = json.loads(body)
                except ValueError:
                    payload = None
                if isinstance(payload, dict):
                    payload.update(stamp)
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    headers = httpx.Headers(request.headers)
                    headers["content-length"] = str(len(body))
                    request = httpx.Request(
                        request.method, request.url, headers=headers, content=body,
                        extensions=request.extensions,
                    )
                    wire.bodies.append(payload)
            try:
                response = await inner.handle_async_request(request)
            except httpx.TransportError as exc:
                note(exc)
                raise
            return httpx.Response(
                response.status_code, headers=response.headers, stream=GuardedStream(response.stream),
                extensions=response.extensions)

        async def aclose(self) -> None:
            await inner.aclose()

    return StampingTransport()


def build_harness(
    workspace: Path,
    flags: Flags,
    spec: ProviderSpec,
    *,
    system: str | None = None,
    max_retries: int = 2,
    home: Path | None = None,
) -> Any:
    """A real ``tau_agent.AgentHarness`` for one session (one task, no compaction).

    ``max_turns`` is None on purpose: the productive-turn cap is the supervisor's
    (AGENTS.md rule 5). The returned object carries ``model_id``, ``wire`` (the
    request-body log) and ``aclose()`` for the HTTP client it owns.
    """
    import httpx
    from tau_agent.harness import AgentHarness, AgentHarnessConfig
    from tau_ai.env import OpenAICompatibleConfig
    from tau_ai.openai_compatible import OpenAICompatibleProvider

    wire = WireLog(stamp=spec.stamp())
    client = httpx.AsyncClient(
        transport=stamping_transport(httpx.AsyncHTTPTransport(), spec.stamp(), wire),
        timeout=httpx.Timeout(spec.timeout_s, connect=min(spec.timeout_s, CONNECT_TIMEOUT_S)),
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            api_key=spec.api_key,
            base_url=spec.base_url.rstrip("/"),
            timeout_seconds=spec.timeout_s,
            max_retries=max_retries,
            api="openai-completions",
            infer_api_from_model=False,  # a local model named gpt-5.4-* is still chat/completions
            compat={"supportsStore": False},
            provider_name="local-openai-compatible",
        ),
        client=client,
    )
    harness = AgentHarness(
        AgentHarnessConfig(
            provider=provider,
            model=spec.model,
            system=system if system is not None else system_prompt(),
            tools=catalog(capture=flags.capture, workspace=Path(workspace), home=home),
            max_turns=None,
        )
    )
    harness.model_id = spec.model
    harness.wire = wire

    async def aclose() -> None:
        await client.aclose()

    harness.aclose = aclose
    return harness
