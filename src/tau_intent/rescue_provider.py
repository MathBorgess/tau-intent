"""Arm C's real provider: the cell's own local model answers the rescue.

Kept apart from ``rescue.py`` on purpose: that module is the declared, hashed
policy and has a test that it contains no network code. This one is the
transport. Standard library only (no runtime dependency).
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


