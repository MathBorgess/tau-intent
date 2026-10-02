"""``gambiarra-coleta-2`` records (contract §4, V0 draft): build and validate.

One record per (cell, arm, task). Qualification attempts use ``arm_id: "Q"``,
``harness_id: "tau"``, ``task_index: 0`` and are never mixed with arm A.

The validator mirrors the constraints the arena applies on receipt and the vault
check applies later, and the runner runs it **before sending**: a record that
contradicts itself is kept locally (``records.invalid.jsonl``) and never reaches
the dataset.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from tau_intent.bench import SCHEMA_VERSION

#: arm_id <-> harness_id bijection (a table to read, not a branch).
HARNESS_BY_ARM = {"A": "tau", "B": "tau_intent", "C": "tau_intent_llm_rescue", "Q": "tau"}
#: Which mechanism flags an arm id stands for. Q is the qualification round in
#: the plain-tau configuration.
FLAG_ARM_BY_ARM_ID = {"A": "A", "B": "B", "C": "C", "Q": "A"}
TERMINATIONS = ("completed", "teto_turnos", "deadline", "stopped", "error")
RUNNER_KINDS = ("ollama", "lmstudio", "llamacpp", "other")
ACCELS = ("cuda", "metal", "cpu", "other")
FLAG_KEYS = ("capture", "gate", "project", "serve", "llm_rescue")
HARDWARE_SOURCES = ("local", "declared")
TRANSPORTS = ("lan", "local")
#: ``error.kind`` of a unit that ended in ``error`` (V0.2). ``backend_unreachable`` is
#: infrastructure: the analysis drops those units, it never counts them as failures.
ERROR_KINDS = ("backend_unreachable", "provider_error", "instrument_error", "not_run")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def config_sha256(hashes: dict[str, str]) -> str:
    """One digest over the five frozen config files (the dict stays in the manifest)."""
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def flags_dict(flags: Any) -> dict[str, bool]:
    return {key: bool(getattr(flags, key, False)) for key in FLAG_KEYS}


def zero_oracle() -> dict[str, Any]:
    """Shape of an oracle that never ran (a unit the runner was told to skip)."""
    return {"pass": False, "passed": 0, "failed": 0, "errors": 0, "duration_s": 0, "per_test": []}


def oracle_block(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in ("pass", "passed", "failed", "errors", "duration_s", "per_test",
                                          "exit_code", "timed_out") if key in result}


def mechanism_telemetry(telemetry: dict[str, Any], verdict: str, productive: int, blocks: int) -> dict[str, Any]:
    """The descriptive telemetry of the contract, plus the fields the analysis will want.

    Ratios are copied as the supervisor computed them: ``None`` on an empty
    denominator (I-2), never rewritten to 0 or 1 here.
    """
    servidas = [s.get("id") if isinstance(s, dict) else s for s in telemetry.get("servidas", [])]
    out: dict[str, Any] = {
        "verdict": verdict,
        "productive_turns": productive,
        "block_turns": blocks,
        "bloco_vazio": bool(telemetry.get("bloco_vazio", False)),
        "tokens_served": int(telemetry.get("tokens_served") or 0),
        "nao_avaliaveis": telemetry.get("codigos_nao_avaliaveis", []),
        "servidas": servidas,
        "tokenizer": telemetry.get("tokenizer"),
    }
    for key in ("gate_avaliado", "captura_publicada", "pendencias_nao_publicadas", "esbarrou_teto",
                "ancoras", "ancoras_vazias", "recibo", "cobertura_de_captura", "cobertura_efetiva",
                "fracao_resolvida", "denominadores", "aproveitamento_do_bloco", "latencia_de_captura",
                "erros_de_captura", "efeitos_nao_rastreados", "efeitos_opacos", "erro_de_provedor",
                "chamada_interrompida", "alvos_excluidos", "grafo_heterogeneo", "edge_types_efetivos"):
        if key in telemetry:
            out[key] = telemetry[key]
    for key, value in telemetry.items():
        if key.startswith("llm_rescue") and key != "llm_rescue_bloco_servido":
            out[key] = value
    return out


def validate_record(record: dict[str, Any]) -> list[str]:
    """Constraints of contract §4. Returns the problems; an empty list means valid."""
    problems: list[str] = []

    def need(cond: bool, message: str) -> None:
        if not cond:
            problems.append(message)

    need(record.get("schema_version") == SCHEMA_VERSION, "schema_version")
    need(record.get("draft") is True, "draft must be true in V0")
    for key in ("cell_id", "participant_id", "task_set_sha", "task_id", "task_hash",
                "started_at", "ended_at"):
        need(isinstance(record.get(key), str) and record[key] != "", f"{key} must be a non-empty string")
    arm, harness = record.get("arm_id"), record.get("harness_id")
    need(arm in HARNESS_BY_ARM, f"arm_id {arm!r}")
    need(HARNESS_BY_ARM.get(arm) == harness, f"arm_id {arm} requires harness_id {HARNESS_BY_ARM.get(arm)} (got {harness})")
    index = record.get("task_index")
    need(isinstance(index, int) and not isinstance(index, bool), "task_index must be an int")
    if arm == "Q":
        need(index == 0, "arm Q requires task_index 0")
    else:
        need(isinstance(index, int) and index >= 1, "arms A/B/C require task_index >= 1")
    model = record.get("model") or {}
    need(isinstance(model.get("id"), str) and model["id"] != "", "model.id")
    need(model.get("runner_kind") in RUNNER_KINDS, "model.runner_kind")
    hw = record.get("hardware") or {}
    need(hw.get("accel") in ACCELS, "hardware.accel")
    need(isinstance(hw.get("ram_gb"), (int, float)) and hw["ram_gb"] >= 0, "hardware.ram_gb")
    need("source" not in hw or hw["source"] in HARDWARE_SOURCES, "hardware.source")
    if hw.get("source") == "declared":
        declared = hw.get("declared")
        need(isinstance(declared, dict) and set(declared) == {"chip", "ram_gb", "accel"}, "hardware.declared")
    backend = record.get("backend")
    if backend is not None:
        need(isinstance(backend, dict) and backend.get("transport") in TRANSPORTS, "backend.transport")
        sha = (backend or {}).get("provider_host_sha256") if isinstance(backend, dict) else None
        need(isinstance(sha, str) and len(sha) == 64, "backend.provider_host_sha256")
    need(isinstance(record.get("seed"), int) and not isinstance(record.get("seed"), bool), "seed must be an int")
    order = record.get("arm_order")
    need(isinstance(order, list) and all(a in ("A", "B", "C") for a in order), "arm_order")
    need(record.get("terminated_by") in TERMINATIONS, "terminated_by")
    error = record.get("error")
    if record.get("terminated_by") == "error":
        need(isinstance(error, dict) and error.get("kind") in ERROR_KINDS
             and isinstance(error.get("detail"), str), "terminated_by error requires error {kind, detail}")
    else:
        need(error is None, "error must be null unless terminated_by is error")

    mech = record.get("mechanism") or {}
    flags = mech.get("flags")
    need(isinstance(flags, dict) and all(isinstance(v, bool) for v in flags.values()), "mechanism.flags")
    tel = record.get("mechanism_telemetry") or {}
    turns = record.get("turns")
    need(isinstance(turns, list), "turns")
    for row in turns if isinstance(turns, list) else []:
        for key in ("latency_ms", "ttft_ms"):
            need(row.get(key) is None or (isinstance(row[key], int) and not isinstance(row[key], bool)
                                          and row[key] >= 0), f"turns[].{key} must be a non-negative int or null")
    if harness == "tau" and isinstance(flags, dict):
        need(not any(flags.values()), "arm A/Q: flags must all be false")
        need(tel.get("block_turns", 0) == 0, "arm A/Q: block_turns must be 0")
        need(not any(t.get("kind") == "block" for t in turns or []), "arm A/Q: no block turns")
        need(not any(t.get("kind") == "rescue" for t in turns or []), "arm A/Q: no rescue turns")
    if harness in ("tau_intent", "tau_intent_llm_rescue") and isinstance(flags, dict):
        need(bool(flags.get("capture")) and bool(flags.get("project")), "arms B/C run capture and project")
    if isinstance(flags, dict):
        need(bool(flags.get("llm_rescue")) == (harness == "tau_intent_llm_rescue"), "llm_rescue flag vs harness_id")

    tokens = record.get("tokens") or {}
    need(tokens.get("source") in ("provider_usage", "missing"), "tokens.source")
    need(tokens.get("cost_usd") == 0, "cost_usd must be 0")
    for key in ("in", "out", "rescue_in", "rescue_out"):
        value = tokens.get(key)
        need(value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0),
             f"tokens.{key} must be a non-negative int or null (never estimated)")
    values = [tokens.get(k) for k in ("in", "out", "rescue_in", "rescue_out")]
    if tokens.get("source") == "provider_usage":
        need(None not in values, "tokens.source provider_usage requires every figure")
    if tokens.get("source") == "missing":
        need(None in values, "tokens.source missing requires a null figure (never a guessed zero)")

    oracle = record.get("oracle") or {}
    need(isinstance(oracle.get("pass"), bool), "oracle.pass")
    need(isinstance(oracle.get("per_test", []), list), "oracle.per_test")
    evolution = record.get("evolution")
    need(isinstance(evolution, dict), "evolution")
    problems.extend(_ratio_problems(tel))
    return problems


def _ratio_problems(tel: dict[str, Any]) -> Iterable[str]:
    """I-2: a ratio over an empty denominator is ``null``, never 0 or 1."""
    out: list[str] = []
    block = tel.get("aproveitamento_do_bloco")
    if isinstance(block, dict) and block.get("servidas") == 0 and block.get("razao") is not None:
        out.append("I-2: aproveitamento_do_bloco.razao over zero served entries must be null")
    coverage = tel.get("cobertura_de_captura")
    if isinstance(coverage, dict):
        den = coverage.get("denominadores") or {}
        for key in ("estrita", "por_arquivo", "fracao_resolvida"):
            if den.get(key) == 0 and coverage.get(key) is not None:
                out.append(f"I-2: cobertura_de_captura.{key} over an empty denominator must be null")
    latency = tel.get("latencia_de_captura")
    if isinstance(latency, dict) and latency.get("denominador") == 0:
        for key in ("media", "maxima"):
            if latency.get(key) is not None:
                out.append(f"I-2: latencia_de_captura.{key} over an empty denominator must be null")
    recibo = tel.get("llm_rescue_recall_de_simbolo")
    if isinstance(recibo, dict) and recibo.get("antes") == 0 and recibo.get("razao") is not None:
        out.append("I-2: llm_rescue_recall_de_simbolo.razao over zero anchors must be null")
    return out
