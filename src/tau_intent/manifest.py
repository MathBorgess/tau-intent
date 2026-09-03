"""Run manifest. A field that describes intent instead of what went out on the
wire is worse than an absent field — so everything here is read from the
artefact it describes, never asserted.
"""

from __future__ import annotations

from typing import Any

from tau_intent import pin
from tau_intent.config import config_hashes, load_bloco_config, load_gate_config


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
        "tokenizer": tokenizer,
        "temperatura_configurada": temperatura_configurada,
        "amostragem_conferida_no_fio": amostragem_conferida_no_fio,
    }
    if flags is not None:
        entry["flags"] = {
            "capture": bool(getattr(flags, "capture", False)),
            "gate": bool(getattr(flags, "gate", False)),
            "project": bool(getattr(flags, "project", False)),
            "serve": bool(getattr(flags, "serve", False)),
        }
        entry["catalogo_tem_record_intent"] = bool(getattr(flags, "capture", False))
    return entry
