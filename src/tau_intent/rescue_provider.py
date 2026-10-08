"""Arm C's real provider: the cell's own local model answers the rescue.

Kept apart from ``rescue.py`` on purpose: that module is the declared, hashed
policy and has a test that it contains no network code. This one is the
transport. The local strand's path is standard library only (no runtime
dependency); a frontier cell's rescue goes through tau's own provider for the
cell's native protocol (``provedor_nativo``), on the same stamping wire log.
"""

from __future__ import annotations

from typing import Any, Callable

from tau_intent.rescue import RescueConfig, Sumarizador, load_rescue_config


def provedor_openai_compat(
    base_url: str,
    model: str,
    seed: int,
    *,
    timeout_s: float,
    api_key: str = "local",
    wire: Any = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The rescue's real provider: the *same* local endpoint and model as the cell.

    Takes the request body ``montar_corpo_da_requisicao`` built (model,
    temperature, max_tokens, messages), stamps the cell's model and ``seed`` into
    it and POSTs it to ``/chat/completions`` without streaming. The body that
    left is appended to ``wire.bodies`` so sampling is checked on the wire here
    too (E-1). Standard library only (no runtime dependency), no environment
    proxy: the endpoint is on the participant's own machine.
    """
    import json
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = base_url.rstrip("/") + "/chat/completions"

    def chamar(body: dict[str, Any]) -> dict[str, Any]:
        sent = {**body, "model": model, "seed": seed, "stream": False}
        if wire is not None:
            wire.bodies.append(sent)
        request = urllib.request.Request(
            url, data=json.dumps(sent, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        try:
            with opener.open(request, timeout=timeout_s) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"rescue provider HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"rescue provider unreachable: {exc}") from exc
        try:
            texto = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            texto = ""
        return {"text": texto, "usage": data.get("usage")}

    return chamar


def provedor_nativo(spec: Any, *, timeout_s: float, wire: Any = None) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The rescue's provider for a frontier cell: the cell's own model, its own protocol.

    The body ``montar_corpo_da_requisicao`` built is OpenAI-shaped; only its parts
    that mean something on every protocol cross over: the user message and
    ``max_tokens``. Sampling is the cell's policy, applied by the same stamping
    transport as the agent's calls (so ``provider-default`` sends none, and the
    wire log proves it). The answer comes back in the shape ``uso_de_resposta``
    reads: ``{"text", "usage": {"prompt_tokens", "completion_tokens"}}``.

    ``projetar`` calls the summariser synchronously from inside the agent's event
    loop, so each call runs tau's async provider on a short-lived loop in a worker
    thread.
    """
    import asyncio
    import concurrent.futures
    from dataclasses import replace

    rescue_spec = replace(spec, timeout_s=timeout_s)

    async def once(body: dict[str, Any]) -> dict[str, Any]:
        from tau_agent.messages import TextContent, UserMessage
        from tau_ai.events import AssistantDoneEvent, AssistantErrorEvent

        from tau_intent.harness_factory import build_provider, stamped_client

        client, log = stamped_client(rescue_spec, wire)
        try:
            provider = build_provider(rescue_spec, client, log, max_retries=0,
                                      max_output_tokens=body.get("max_tokens"))
            content = "\n\n".join(str(m.get("content") or "") for m in body.get("messages", [])
                                   if isinstance(m, dict) and m.get("role") == "user")
            final = None
            async for event in provider.stream_response(
                    model=spec.model, system="", tools=[],
                    messages=[UserMessage(content=[TextContent(text=content)])]):
                if isinstance(event, AssistantDoneEvent):
                    final = event.message
                elif isinstance(event, AssistantErrorEvent):
                    raise RuntimeError(f"rescue provider: {event.error.error_message or event.reason}"[:300])
        finally:
            await client.aclose()
        if final is None:
            raise RuntimeError("rescue provider: the stream ended without a final message")
        texto = "".join(block.text for block in final.content if isinstance(block, TextContent))
        u = final.usage
        uso = {"prompt_tokens": int(u.input) + int(u.cache_read) + int(u.cache_write),
               "completion_tokens": int(u.output)}
        return {"text": texto, "usage": uso}

    def chamar(body: dict[str, Any]) -> dict[str, Any]:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: asyncio.run(once(body)))
        try:
            return future.result(timeout=timeout_s + 5)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(f"rescue provider timed out after {timeout_s}s") from exc
        finally:
            pool.shutdown(wait=False)  # a hung call is abandoned, never waited on

    return chamar


def sumarizador_nativo(spec: Any, *, cfg: RescueConfig | None = None, timeout_s: float | None = None,
                       wire: Any = None) -> Sumarizador:
    """Arm C's summariser for a frontier cell (same rule as ``sumarizador_local``: D-2)."""
    from dataclasses import replace

    base = cfg or load_rescue_config()
    cfg = replace(base, modelo_id=spec.model, habilitado=True)
    return Sumarizador(cfg, provedor_nativo(spec, timeout_s=timeout_s or cfg.timeout_s, wire=wire))


def sumarizador_local(
    base_url: str,
    model: str,
    seed: int,
    *,
    cfg: RescueConfig | None = None,
    timeout_s: float | None = None,
    api_key: str = "local",
    wire: Any = None,
) -> Sumarizador:
    """Arm C's summariser: the cell's own model answers the rescue (owner decision D-2).

    ``rescue.yaml`` stays frozen (``modelo_id`` is empty there, ``gatilho:
    sempre``); the model id is the cell's, set here and stamped in the manifest.
    The request timeout is the YAML's ``timeout_s`` unless the caller overrides it.
    """
    from dataclasses import replace

    base = cfg or load_rescue_config()
    cfg = replace(base, modelo_id=model, habilitado=True)
    provider = provedor_openai_compat(
        base_url, model, seed, timeout_s=timeout_s or cfg.timeout_s, api_key=api_key, wire=wire)
    return Sumarizador(cfg, provider)


