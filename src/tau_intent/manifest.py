"""Run manifest. A field that describes intent instead of what went out on the
wire is worse than an absent field — so everything here is read from the
artefact it describes, never asserted.
"""

from __future__ import annotations

from typing import Any

from tau_intent import pin
from tau_intent.config import config_hashes, load_bloco_config, load_gate_config
from tau_intent.rescue import load_rescue_config


def _rescue_entry() -> dict[str, Any]:
    """The frozen description of the summariser (H16/H17).

    Two hashes, not one: the YAML and the prompt file. A prompt outside the
    hash is a prompt outside the freeze.
    """
    try:
        cfg = load_rescue_config()
    except Exception as exc:  # noqa: BLE001 - a broken config is data here
        return {"erro": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "versao": cfg.versao,
        "habilitado": cfg.habilitado,
        "gatilho": cfg.gatilho,
        "unidade": cfg.unidade,
        "modelo_id": cfg.modelo_id,
        "temperatura": cfg.temperatura,
        "max_tokens_saida": cfg.max_tokens_saida,
        "prompt_caminho": cfg.prompt_caminho,
        "prompt_sha256": cfg.prompt_sha256(),
        "preservar_obrigatorio": list(cfg.preservar_obrigatorio),
        "falha_politica": cfg.falha_politica,
        "timeout_s": cfg.timeout_s,
    }


def manifest_da_execucao(flags: Any, telemetry: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Manifest of one run: the frozen config plus what actually went out.

    Arm C is not reproducible from the YAML and the store alone — a model wrote
    part of what was served. So the block that was actually served is recorded,
    not only the hash of the prompt that asked for it (study note §3.7).
    """
    entry = manifest(flags=flags, **kwargs)
    execucao = {
        "tokens_served": telemetry.get("tokens_served"),
        "recibo": telemetry.get("recibo"),
        "bloco_posicao": telemetry.get("bloco_posicao"),
        "cobertura_de_captura": telemetry.get("cobertura_de_captura"),
        "latencia_de_captura": telemetry.get("latencia_de_captura"),
        "aproveitamento_do_bloco": telemetry.get("aproveitamento_do_bloco"),
        "productive_turns": telemetry.get("productive_turns"),
        "block_turns": telemetry.get("block_turns"),
    }
    for campo, valor in telemetry.items():
        if campo.startswith("llm_rescue"):
            execucao[campo] = valor
    entry["execucao"] = execucao
    return entry


def manifest(
    *,
    flags: Any = None,
    tokenizer: str = "whitespace-v1",
    temperatura_configurada: float | None = None,
    amostragem_conferida_no_fio: bool = False,
) -> dict[str, Any]:
    """The frozen description of one run's configuration."""
    gate_cfg = load_gate_config()
    bloco_cfg = load_bloco_config()
    entry: dict[str, Any] = {
        "config_sha256": config_hashes(),
        "gate": {
            "versao": gate_cfg.versao,
            "n_max": gate_cfg.n_max,
            "limiar_edicao": gate_cfg.limiar_edicao,
            "contexto_diff": gate_cfg.contexto_diff,
            "codigos": list(gate_cfg.codigos),
        },
        "bloco": {
            "versao": bloco_cfg.versao,
            "posicao": bloco_cfg.posicao,
            "envelope_tag": bloco_cfg.envelope_tag,
            "identico_entre_bracos": bloco_cfg.identico_entre_bracos,
        },
        "tau": {
            "dist": pin.PINNED_DIST,
            "version": pin.PINNED_VERSION,
            "sha256": pin.PINNED_SHA256,
            "git": pin.PINNED_GIT,
        },
        "rescue": _rescue_entry(),
        "tokenizer": tokenizer,
        "temperatura_configurada": temperatura_configurada,
        "amostragem_conferida_no_fio": amostragem_conferida_no_fio,
    }
    if flags is not None:
        entry["rescue"]["habilitado_na_execucao"] = bool(getattr(flags, "llm_rescue", False))
        entry["flags"] = {
            "capture": bool(getattr(flags, "capture", False)),
            "gate": bool(getattr(flags, "gate", False)),
            "project": bool(getattr(flags, "project", False)),
            "serve": bool(getattr(flags, "serve", False)),
        }
        entry["catalogo_tem_record_intent"] = bool(getattr(flags, "capture", False))
    return entry


class RelatoIncoerente(ValueError):
    """V4 and V5 reported over configs that are not the same config."""


def conferir_v4_v5(v4: dict[str, Any], v5: dict[str, Any] | None) -> None:
    """P-4: V4 is the objective, V5 is the constraint, and they travel together.

    Closing V4 by cutting everything is trivially possible, and it is exactly
    what reporting V4 alone would hide. A report is refused when V5 is missing,
    or when the two were produced over different config hashes.
    """
    if v5 is None:
        raise RelatoIncoerente("V4 sem V5 do mesmo sha256: V4 é o objetivo, V5 é a restrição")
    a = v4.get("config_sha256") or {}
    b = v5.get("config_sha256") or {}
    if not a or not b:
        raise RelatoIncoerente("relato sem config_sha256 não é auditável")
    if a != b:
        diferentes = sorted(
            nome for nome in set(a) | set(b) if a.get(nome) != b.get(nome)
        )
        raise RelatoIncoerente(f"V4 e V5 sobre YAML diferentes: {diferentes}")
