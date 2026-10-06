"""Which wire protocol a cell speaks, and what that changes (frontier strand).

The local strand speaks one protocol: OpenAI-compatible ``/chat/completions``
(Ollama, LM Studio, llama.cpp). The frontier strand reaches subscription models
through local credential proxies (``mathai-harness``) that speak each vendor's
**native** protocol, and the pinned tau ships a native provider for each one.
Nothing here re-implements a provider or the loop (AGENTS.md rule 1): this module
only says, per protocol,

* which tau provider is built, and the base URL it is handed;
* where sampling lives in the request body, and whether the protocol has a field
  for it at all (a protocol with no ``seed`` field cannot carry the cell's seed:
  the seed is then a label of the cell, not a property of the call);
* which sampling knobs exist, so that ``provider-default`` can be *checked* on the
  wire (nothing overrode the provider's own sampling), not assumed;
* whether tau reads ``usage`` from the stream. tau 0.4.7's Google parser drops
  ``usageMetadata``; the runner then reads it off the wire (``UsageFromWire``),
  so the figure is still the provider's own, never an estimate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

OPENAI_COMPLETIONS = "openai-completions"
ANTHROPIC_MESSAGES = "anthropic-messages"
OPENAI_CODEX = "openai-codex-responses"
GOOGLE = "google-generative-ai"
PROVIDER_APIS = (OPENAI_COMPLETIONS, ANTHROPIC_MESSAGES, OPENAI_CODEX, GOOGLE)

#: ``stamped``: the cell's temperature and seed are written into every body, in the
#: fields the protocol has (the local strand's rule, AGENTS.md rule 8).
#: ``provider-default``: no sampling field leaves the process, and the wire log proves
#: it. For models that reject sampling parameters (reasoning models, Claude Opus 5.5)
#: this is the only policy that does not end every request in a 400.
SAMPLING_STAMPED = "stamped"
SAMPLING_PROVIDER_DEFAULT = "provider-default"
SAMPLING_POLICIES = (SAMPLING_STAMPED, SAMPLING_PROVIDER_DEFAULT)

#: Where each protocol keeps the fields ``stamped`` writes (dotted paths into the body).
SAMPLING_FIELDS: dict[str, dict[str, str]] = {
    OPENAI_COMPLETIONS: {"temperature": "temperature", "seed": "seed"},
    ANTHROPIC_MESSAGES: {"temperature": "temperature"},
    OPENAI_CODEX: {"temperature": "temperature"},
    GOOGLE: {"temperature": "generationConfig.temperature", "seed": "generationConfig.seed"},
}

#: Every sampling knob of each protocol: under ``provider-default`` none may be present.
SAMPLING_KNOBS: dict[str, tuple[str, ...]] = {
    OPENAI_COMPLETIONS: ("temperature", "seed", "top_p"),
    ANTHROPIC_MESSAGES: ("temperature", "top_p", "top_k"),
    OPENAI_CODEX: ("temperature", "top_p"),
    GOOGLE: ("generationConfig.temperature", "generationConfig.seed",
             "generationConfig.topP", "generationConfig.topK"),
}

#: First system block a Claude subscription (OAuth) token requires; tau's own OAuth
#: path sends the same text (``tau_coding.provider_runtime``). It is sent as a separate
#: block before the agent's prompt, identical in every arm, and stamped in the manifest.
ANTHROPIC_OAUTH_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
#: The beta an OAuth bearer needs on the Messages API (the proxy adds it too).
ANTHROPIC_OAUTH_BETA = "oauth-2025-04-20"

_MISSING = object()


def check_api(api: str) -> str:
    if api not in PROVIDER_APIS:
        raise ValueError(f"provider api must be one of {PROVIDER_APIS} (got {api!r})")
    return api


def check_sampling(sampling: str) -> str:
    if sampling not in SAMPLING_POLICIES:
        raise ValueError(f"sampling must be one of {SAMPLING_POLICIES} (got {sampling!r})")
    return sampling


def get_path(obj: Any, dotted: str, default: Any = _MISSING) -> Any:
    node = obj
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def has_path(obj: Any, dotted: str) -> bool:
    return get_path(obj, dotted) is not _MISSING


def set_path(obj: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = obj
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def stamp_for(api: str, sampling: str, *, temperature: float, seed: int) -> dict[str, Any]:
    """Dotted path -> value written into every request body of the cell."""
    check_api(api)
    if check_sampling(sampling) == SAMPLING_PROVIDER_DEFAULT:
        return {}
    values = {"temperature": temperature, "seed": seed}
    return {path: values[name] for name, path in SAMPLING_FIELDS[api].items()}


def seed_on_wire(api: str, sampling: str) -> bool:
    """Does the cell's seed reach the model, or is it only a label of the cell?"""
    return sampling == SAMPLING_STAMPED and "seed" in SAMPLING_FIELDS[check_api(api)]


def runner_kind_for(api: str) -> str:
    """A native-protocol cell is never a local runner the arena knows."""
    return "other" if check_api(api) != OPENAI_COMPLETIONS else ""


# ------------------------------------------------------------------ usage off the wire
@dataclass
class ResponseUsage:
    """What one response carried about its own cost, read from its bytes."""

    usage: dict[str, int] | None = None
    #: The model the provider said answered (Gemini ``modelVersion``), when it said.
    model: str | None = None
    _pending: str = field(default="", repr=False)

    def feed(self, chunk: bytes) -> None:
        self._pending += chunk.decode("utf-8", "replace")
        lines = self._pending.split("\n")
        self._pending = lines.pop()
        for line in lines:
            self._line(line)

    def close(self) -> None:
        if self._pending:
            self._line(self._pending)
            self._pending = ""

    def _line(self, line: str) -> None:
        line = line.strip()
        if not line.startswith("data:") or "usageMetadata" not in line:
            return
        try:
            chunk = json.loads(line[5:])
        except ValueError:
            return
        found = google_usage(chunk)
        if found is not None:
            self.usage = found  # cumulative: the last report wins
        if isinstance(chunk, dict) and isinstance(chunk.get("modelVersion"), str):
            self.model = chunk["modelVersion"]


def google_usage(chunk: Any) -> dict[str, int] | None:
    """Gemini ``usageMetadata`` in tau's vocabulary.

    ``promptTokenCount`` is the whole prompt, cached part included;
    ``candidatesTokenCount`` excludes the thinking, which is billed as output
    (``thoughtsTokenCount``). Output here is candidates + thoughts, as for every
    other protocol (``uso_do_provedor``: completion, reasoning included).
    """
    meta = chunk.get("usageMetadata") if isinstance(chunk, dict) else None
    if not isinstance(meta, dict):
        return None

    def num(key: str) -> int:
        value = meta.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    prompt, cached = num("promptTokenCount"), num("cachedContentTokenCount")
    thoughts = num("thoughtsTokenCount")
    output = num("candidatesTokenCount") + thoughts
    if prompt == 0 and output == 0:
        return None
    return {"input": max(prompt - cached, 0), "cache_read": min(cached, prompt), "output": output,
            "reasoning": thoughts}


class UsageFromWire:
    """Wraps a tau provider: fills an empty ``usage`` from the response the wire saw,
    and ``response_model`` from the model the provider said answered (``modelVersion``).

    Only ever *fills* a usage the provider left at zero, and only from the bytes of
    the response that produced the message; a provider that parsed its own usage is
    left untouched. The loop, the events and the provider are tau's.
    """

    def __init__(self, inner: Any, wire: Any) -> None:
        self._inner = inner
        self._wire = wire

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def stream_response(self, **kwargs: Any) -> Any:
        from tau_agent.messages import Usage
        from tau_ai.events import AssistantDoneEvent, AssistantErrorEvent

        wire = self._wire
        start = len(wire.responses)
        source = self._inner.stream_response(**kwargs)

        async def events() -> Any:
            async for event in source:
                message = None
                if isinstance(event, AssistantDoneEvent):
                    message = event.message
                elif isinstance(event, AssistantErrorEvent):
                    message = event.error
                if message is not None:
                    _fill(message, wire.responses[start:], Usage)
                yield event

        return events()


def _fill(message: Any, responses: list[ResponseUsage], usage_cls: Any) -> None:
    served = [r.model for r in responses if r.model]
    if served and getattr(message, "response_model", None) is None:
        message.response_model = served[-1]  # the model the provider says answered
    current = getattr(message, "usage", None)
    if current is not None and (current.input or current.output or current.cache_read or current.cache_write):
        return
    seen = [r.usage for r in responses if r.usage is not None]
    if not seen:
        return
    last = seen[-1]
    message.usage = usage_cls(input=last["input"], output=last["output"], cache_read=last["cache_read"],
                              reasoning=last["reasoning"],
                              total_tokens=last["input"] + last["cache_read"] + last["output"])
