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
* **The protocol is the cell's** (frontier strand, ``provider_api.py``). The
  default is the local strand's OpenAI-compatible ``/chat/completions``; a frontier
  cell speaks its vendor's native protocol to a local credential proxy, through
  tau's own provider for that protocol. The stamp moves with the protocol (or is
  empty under ``provider-default``), and the wire log checks it either way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tau_intent import provider_api as api_mod
from tau_intent.config import CONFIG_DIR, sha256_of
from tau_intent.provider_api import ResponseUsage, UsageFromWire, get_path, has_path, set_path
from tau_intent.supervisor import Flags
from tau_intent.tools import catalog

SYSTEM_PROMPT_PATH = CONFIG_DIR / "prompts" / "agent-system-v1.txt"


def system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def system_prompt_sha256() -> str:
    return sha256_of(SYSTEM_PROMPT_PATH)


@dataclass(frozen=True)
class ProviderSpec:
    """One cell's model endpoint. The same spec serves the agent and the rescue.

    ``api``, ``sampling``, ``reasoning_effort`` and ``max_output_tokens`` are the
    frontier strand's knobs; their defaults are the local strand, unchanged.
    """

    base_url: str
    model: str
    seed: int
    temperature: float = 0.0
    timeout_s: float = 600.0
    api_key: str = "local"
    api: str = api_mod.OPENAI_COMPLETIONS
    sampling: str = api_mod.SAMPLING_STAMPED
    #: Provider-native depth knob (Anthropic ``output_config.effort``, Codex
    #: ``reasoning.effort``, Gemini ``thinkingConfig``); ``None`` = the provider's default.
    reasoning_effort: str | None = None
    #: ``None`` = tau's default for the protocol (4096 on Anthropic).
    max_output_tokens: int | None = None
    #: Anthropic over a subscription token: prepend the Claude Code identity block some
    #: subscriptions require. Off by default: the call is the agent's prompt and nothing
    #: else; ``frontier probe`` measures whether a subscription refuses it without.
    anthropic_oauth_identity: bool = False

    def stamp(self) -> dict[str, Any]:
        return api_mod.stamp_for(self.api, self.sampling, temperature=self.temperature, seed=self.seed)

    def wire_log(self) -> "WireLog":
        return WireLog(stamp=self.stamp(), api=self.api, sampling=self.sampling)

    def system_prefix(self) -> str | None:
        """Text the protocol puts before the agent's own system prompt, if any."""
        if self.api == api_mod.ANTHROPIC_MESSAGES and self.anthropic_oauth_identity:
            return api_mod.ANTHROPIC_OAUTH_IDENTITY
        return None

    def describe(self) -> dict[str, Any]:
        """What the manifest says about the protocol side of the cell."""
        return {"provider_api": self.api, "sampling": self.sampling,
                "seed_on_wire": api_mod.seed_on_wire(self.api, self.sampling),
                "reasoning_effort": self.reasoning_effort, "max_output_tokens": self.max_output_tokens,
                "system_prefix": self.system_prefix()}


@dataclass
class WireLog:
    """Request bodies as they left the process, plus what they were meant to carry."""

    stamp: dict[str, Any]
    bodies: list[dict[str, Any]] = field(default_factory=list)
    #: Transport failures seen on the agent's calls (refused, reset, timeout, closed
    #: mid-stream): ``{"type": <httpx class>, "detail": <message>}``. They are how the
    #: cell tells "the backend is gone" (infrastructure) from any other provider error.
    network_errors: list[dict[str, str]] = field(default_factory=list)
    api: str = api_mod.OPENAI_COMPLETIONS
    sampling: str = api_mod.SAMPLING_STAMPED
    #: One entry per response whose bytes the transport read for ``usage`` (Google only:
    #: tau's parser for that protocol does not keep it). See ``UsageFromWire``.
    responses: list[ResponseUsage] = field(default_factory=list)
    #: HTTP status of every response, in order: how the cell tells a spent quota or a
    #: refused credential (infrastructure) from a model that answered.
    statuses: list[int] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        n = len(self.bodies)
        if self.sampling == api_mod.SAMPLING_PROVIDER_DEFAULT:
            knobs = api_mod.SAMPLING_KNOBS[self.api]
            ok = n > 0 and not any(has_path(body, knob) for body in self.bodies for knob in knobs)
        else:
            ok = n > 0 and all(
                all(get_path(body, key, None) == value for key, value in self.stamp.items())
                for body in self.bodies
            )
        fields = api_mod.SAMPLING_FIELDS[self.api]
        report = {
            "temperature": self.stamp.get(fields.get("temperature", "")),
            "seed": self.stamp.get(fields.get("seed", "")),
            "requests": n,
            "conferida_no_fio": ok,
            "stream_usage_pedido": n > 0 and all(
                (body.get("stream_options") or {}).get("include_usage") is True
                for body in self.bodies
            ),
        }
        if self.api != api_mod.OPENAI_COMPLETIONS:
            # Native protocols always report usage in the stream: nothing to ask for.
            report.update({"stream_usage_pedido": None, "api": self.api, "politica": self.sampling})
        return report


#: A backend that does not accept a connection is known quickly; a model that is
#: slow to answer is not an unreachable one, so only the connect phase is short.
CONNECT_TIMEOUT_S = 10.0


def stamping_transport(inner: Any, stamp: dict[str, Any], wire: WireLog) -> Any:
    import httpx

    read_usage = wire.api == api_mod.GOOGLE

    def note(exc: Exception) -> None:
        wire.network_errors.append({"type": type(exc).__name__, "detail": str(exc)[:200]})

    class GuardedStream(httpx.AsyncByteStream):
        """The body of the response: a failure while it streams is seen here."""

        def __init__(self, stream: Any, usage: ResponseUsage | None = None) -> None:
            self._stream = stream
            self._usage = usage

        async def __aiter__(self) -> Any:
            try:
                async for chunk in self._stream:
                    if self._usage is not None:
                        self._usage.feed(chunk)
                    yield chunk
            except httpx.TransportError as exc:
                note(exc)
                raise
            finally:
                if self._usage is not None:
                    self._usage.close()

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
                    for path, value in stamp.items():
                        set_path(payload, path, value)
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
            wire.statuses.append(response.status_code)
            usage = None
            if read_usage and request.method == "POST":
                usage = ResponseUsage()
                wire.responses.append(usage)
            return httpx.Response(
                response.status_code, headers=response.headers, stream=GuardedStream(response.stream, usage),
                extensions=response.extensions)

        async def aclose(self) -> None:
            await inner.aclose()

    return StampingTransport()


def _versioned(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith(suffix) else base + suffix


def stamped_client(spec: ProviderSpec, wire: WireLog | None = None) -> tuple[Any, WireLog]:
    """An ``httpx.AsyncClient`` whose transport stamps and logs every body."""
    import httpx

    wire = wire if wire is not None else spec.wire_log()
    client = httpx.AsyncClient(
        transport=stamping_transport(httpx.AsyncHTTPTransport(), spec.stamp(), wire),
        timeout=httpx.Timeout(spec.timeout_s, connect=min(spec.timeout_s, CONNECT_TIMEOUT_S)),
    )
    return client, wire


def build_provider(spec: ProviderSpec, client: Any, wire: WireLog, *, max_retries: int,
                   max_output_tokens: int | None = None) -> Any:
    """tau's own provider for the cell's protocol, on the stamping client."""
    out_tokens = max_output_tokens if max_output_tokens is not None else spec.max_output_tokens
    if spec.api == api_mod.OPENAI_COMPLETIONS:
        from tau_ai.env import OpenAICompatibleConfig
        from tau_ai.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            OpenAICompatibleConfig(
                api_key=spec.api_key,
                base_url=spec.base_url.rstrip("/"),
                timeout_seconds=spec.timeout_s,
                max_retries=max_retries,
                api="openai-completions",
                infer_api_from_model=False,  # a local model named gpt-5.4-* is still chat/completions
                compat={"supportsStore": False},
                provider_name="local-openai-compatible",
                **({"max_tokens": out_tokens} if out_tokens is not None else {}),
            ),
            client=client,
        )
    if spec.api == api_mod.ANTHROPIC_MESSAGES:
        from tau_ai.anthropic import AnthropicProvider
        from tau_ai.env import AnthropicConfig

        identity = spec.system_prefix()
        return AnthropicProvider(
            AnthropicConfig(
                api_key=spec.api_key,
                bearer_auth=True,  # the proxy swaps the bearer for the subscription's
                base_url=_versioned(spec.base_url, "/v1"),
                # Only the beta an OAuth bearer needs; no Claude Code harness beta.
                headers={"anthropic-beta": api_mod.ANTHROPIC_OAUTH_BETA},
                timeout_seconds=spec.timeout_s,
                max_retries=max_retries,
                max_tokens=out_tokens,
                # No ``thinking`` field unless an effort is declared: the model's default
                # (adaptive on Opus 5.5, which rejects ``disabled``) is what runs.
                thinking_mode="adaptive" if spec.reasoning_effort else "budget",
                thinking_effort=spec.reasoning_effort,
                provider_name="anthropic-via-proxy",
                oauth_system_prompt=identity,
            ),
            client=client,
        )
    if spec.api == api_mod.OPENAI_CODEX:
        from tau_ai.openai_codex import OpenAICodexConfig, OpenAICodexCredentials, OpenAICodexProvider

        async def placeholder() -> OpenAICodexCredentials:
            # The proxy holds the subscription; what is sent here is replaced there.
            return OpenAICodexCredentials(access_token=spec.api_key, account_id="via-proxy")

        return OpenAICodexProvider(
            OpenAICodexConfig(
                credential_resolver=placeholder,
                base_url=spec.base_url.rstrip("/"),
                timeout_seconds=spec.timeout_s,
                max_retries=max_retries,
                reasoning_effort=spec.reasoning_effort,
                provider_name="openai-codex-via-proxy",
            ),
            client=client,
        )
    if spec.api == api_mod.GOOGLE:
        from tau_ai.env import OpenAICompatibleConfig
        from tau_ai.google import GoogleGenerativeAIProvider

        provider = GoogleGenerativeAIProvider(
            OpenAICompatibleConfig(
                api_key=spec.api_key,
                base_url=_versioned(spec.base_url, "/v1beta"),
                timeout_seconds=spec.timeout_s,
                max_retries=max_retries,
                reasoning_effort=spec.reasoning_effort,
                max_tokens=out_tokens,
                provider_name="google-via-proxy",
            ),
            client=client,
        )
        return UsageFromWire(provider, wire)
    raise ValueError(f"unknown provider api {spec.api!r}")


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
    from tau_agent.harness import AgentHarness, AgentHarnessConfig

    client, wire = stamped_client(spec)
    provider = build_provider(spec, client, wire, max_retries=max_retries)
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
