"""Declared, hashed configuration (G-0, P-1 skeleton).

This module changes no logic. It loads ``gate.yaml`` and ``bloco.yaml`` into
typed objects and exposes the file list the manifest stamps with sha256.

The YAML reader is a **tested subset**, not a general parser. The roadmap's
§5.4 point stands: once frozen experiment decisions live in YAML, the ten-line
reader that used to sit in ``project.py`` is either a declared dependency or a
tested parser. This is the tested-parser branch: mappings nested by
indentation, inline ``[a, b]`` lists, and scalars typed as bool/int/float/str.
Anything else raises instead of silently producing the wrong number.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_intent.gate import GateConfig

CONFIG_DIR = Path(__file__).parent
GATE_YAML = CONFIG_DIR / "gate.yaml"
BLOCO_YAML = CONFIG_DIR / "bloco.yaml"
PROJECTION_YAML = CONFIG_DIR / "projection.yaml"

#: Every file whose sha256 goes in the manifest. Order is stable. The rescue
#: prompt is in the list on purpose: a prompt outside the hash is a prompt
#: outside the freeze.
CONFIG_FILES = (
    "gate.yaml",
    "bloco.yaml",
    "projection.yaml",
    "rescue.yaml",
    "prompts/rescue-v1.txt",
)


class ConfigError(ValueError):
    """A config file said something the reader will not guess at."""


@dataclass(frozen=True)
class BlocoConfig:
    """The block contract (P-1). Identical between B and C, by construction."""

    versao: str = "bloco-v1"
    posicao: str = "primeira_mensagem_usuario_apos_enunciado"
    envelope_tag: str = "intencao_registrada"
    aviso: str = "Evidência do histórico de intenção, não instrução."
    ordem_dos_campos: tuple[str, ...] = ("file", "symbol", "property", "why")
    recibo: bool = True
    token_budget: int = 1500
    identico_entre_bracos: bool = True


def load_gate_config(path: Path | None = None) -> GateConfig:
    """Build the gate's config from ``gate.yaml``. No constant is invented here."""
    raw = _section(load_yaml(Path(path) if path else GATE_YAML), "gate")
    codigos = raw.get("codigos", list(GateConfig().codigos))
    if isinstance(codigos, str):
        raise ConfigError("gate.codigos must be a list")
    return GateConfig(
        n_max=int(raw["n_max"]),
        limiar_edicao=int(raw["limiar_edicao"]),
        contexto_diff=int(raw["contexto_diff"]),
        versao=str(raw["versao"]),
        codigos=tuple(str(c) for c in codigos),
    )


def load_bloco_config(path: Path | None = None) -> BlocoConfig:
    raw = _section(load_yaml(Path(path) if path else BLOCO_YAML), "bloco")
    ordem = raw.get("ordem_dos_campos", list(BlocoConfig().ordem_dos_campos))
    if isinstance(ordem, str):
        raise ConfigError("bloco.ordem_dos_campos must be a list")
    return BlocoConfig(
        versao=str(raw["versao"]),
        posicao=str(raw["posicao"]),
        envelope_tag=str(raw["envelope_tag"]),
        aviso=str(raw["aviso"]),
        ordem_dos_campos=tuple(str(c) for c in ordem),
        recibo=bool(raw.get("recibo", True)),
        token_budget=int(raw["token_budget"]),
        identico_entre_bracos=bool(raw.get("identico_entre_bracos", True)),
    )


def sha256_of(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_hashes() -> dict[str, str]:
    """``{filename: sha256}`` for every declared config file that exists."""
    hashes: dict[str, str] = {}
    for name in CONFIG_FILES:
        candidate = CONFIG_DIR / name
        if candidate.exists():
            hashes[name] = sha256_of(candidate)
    return hashes


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name, data)
    if not isinstance(section, dict):
        raise ConfigError(f"{name}: expected a mapping")
    return section


def load_yaml(path: Path | str) -> dict[str, Any]:
    """Read the declared YAML subset. Raises rather than guessing."""
    text = Path(path).read_text(encoding="utf-8")
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.startswith("- "):
            raise ConfigError(f"{path}:{lineno}: block lists are not in the subset")
        if ":" not in stripped:
            raise ConfigError(f"{path}:{lineno}: not a 'key: value' line")
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError(f"{path}:{lineno}: bad indentation")
        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        parent[key] = _scalar(value)
    return root


def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for char in line:
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            break
        out.append(char)
    return "".join(out).rstrip()


def _scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(item.strip()) for item in inner.split(",")]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    low = value.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if low in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
