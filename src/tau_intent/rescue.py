"""llm_rescue — arm C's summariser (H16, H17 decided by the owner).

The one place in the mechanism where a model writes what another model reads.
It runs **after** the deterministic selection, over the block that the budget
cut already closed; it never selects, never runs inside ``portao()``, and never
touches the envelope, the position or the omission receipt.

Every degree of freedom lives in ``rescue.yaml`` — trigger policy, unit,
model id, sampling, prompt file, failure policy, telemetry switches. Nothing
here is a constant in the code, which is the discipline ``limiar_edicao = 51``
did not get.

The prompt is a file on disk, versioned and hashed. Both hashes — the YAML's
and the prompt file's — go in the manifest: a prompt outside the hash is a
prompt outside the freeze.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from tau_intent.config import CONFIG_DIR, ConfigError, load_yaml, sha256_of

RESCUE_YAML = CONFIG_DIR / "rescue.yaml"

GATILHOS = ("sempre", "ao_estourar")
UNIDADES = ("bloco", "arquivo", "entrada")
POLITICAS_DE_FALHA = ("degradar_sem_sumarizar",)

#: ``arquivo.py::simbolo`` — the anchored symbol the summary may not lose.
_ANCORA = re.compile(r"[\w./\\-]+\.py::[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class RescueConfig:
    versao: str = "rescue-v1"
    habilitado: bool = False
    gatilho: str = "sempre"
    unidade: str = "bloco"
    modelo_id: str = ""
    temperatura: float = 0.0
    max_tokens_saida: int = 800
    prompt_caminho: str = "prompts/rescue-v1.txt"
    preservar_obrigatorio: tuple[str, ...] = (
        "simbolo_ancorado",
        "distincao_property_why",
        "recibo_de_omissao",
    )
    proibir_invencao: bool = True
    falha_politica: str = "degradar_sem_sumarizar"
    timeout_s: int = 30
    telemetria_token_antes: bool = True
    telemetria_token_depois: bool = True
    telemetria_frequencia_de_disparo: bool = True
    telemetria_recall_de_simbolo: bool = True
    telemetria_bloco_servido: bool = True

    def prompt_path(self) -> Path:
        caminho = Path(self.prompt_caminho)
        return caminho if caminho.is_absolute() else CONFIG_DIR / caminho

    def prompt_text(self) -> str:
        return self.prompt_path().read_text(encoding="utf-8")

    def prompt_sha256(self) -> str:
        return sha256_of(self.prompt_path())


@dataclass
class Resumo:
    """What the summariser gave back, plus what has to be reported about it."""

    texto: str
    modelo: str = ""
    prompt_sha256: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    amostragem: dict[str, Any] = field(default_factory=dict)
    chamadas: int = 0


def load_rescue_config(path: Path | None = None) -> RescueConfig:
    raw = load_yaml(Path(path) if path else RESCUE_YAML)
    raw = raw.get("rescue", raw)
    cfg = RescueConfig(
        versao=str(raw.get("versao", "rescue-v1")),
        habilitado=bool(raw.get("habilitado", False)),
        gatilho=str(raw.get("gatilho", "sempre")),
        unidade=str(raw.get("unidade", "bloco")),
        modelo_id=str(raw.get("modelo_id", "") or ""),
        temperatura=float(raw.get("temperatura", 0)),
        max_tokens_saida=int(raw.get("max_tokens_saida", 800)),
        prompt_caminho=str(raw.get("prompt_caminho", "prompts/rescue-v1.txt")),
        preservar_obrigatorio=tuple(raw.get("preservar_obrigatorio", ()) or ()),
        proibir_invencao=bool(raw.get("proibir_invencao", True)),
        falha_politica=str(raw.get("falha_politica", "degradar_sem_sumarizar")),
        timeout_s=int(raw.get("timeout_s", 30)),
        telemetria_token_antes=bool(raw.get("telemetria_token_antes", True)),
        telemetria_token_depois=bool(raw.get("telemetria_token_depois", True)),
        telemetria_frequencia_de_disparo=bool(
            raw.get("telemetria_frequencia_de_disparo", True)
        ),
        telemetria_recall_de_simbolo=bool(raw.get("telemetria_recall_de_simbolo", True)),
        telemetria_bloco_servido=bool(raw.get("telemetria_bloco_servido", True)),
    )
    if cfg.gatilho not in GATILHOS:
        raise ConfigError(f"rescue.gatilho: {cfg.gatilho!r} não é {GATILHOS}")
    if cfg.unidade not in UNIDADES:
        raise ConfigError(f"rescue.unidade: {cfg.unidade!r} não é {UNIDADES}")
    if cfg.falha_politica not in POLITICAS_DE_FALHA:
        raise ConfigError(f"rescue.falha_politica: {cfg.falha_politica!r}")
    if not cfg.prompt_path().exists():
        raise ConfigError(f"rescue.prompt_caminho não existe: {cfg.prompt_path()}")
    if cfg.habilitado and not cfg.modelo_id:
        # Degrading silently here would turn arm C into arm B without saying so.
        raise ConfigError(
            "rescue.habilitado=true exige rescue.modelo_id — está vazio à espera "
            "da decisão de provedor (nota de estudo §3.5)"
        )
    return cfg


def simbolos_ancorados(texto: str) -> set[str]:
    """``file::symbol`` occurrences. Deterministic, zero model calls."""
    return set(_ANCORA.findall(texto or ""))


def recall_de_simbolo(antes: str, depois: str) -> dict[str, Any]:
    """Anchored symbols surviving the summary (study note §3.4).

    Descriptive of arm C only: in arm B the "after" *is* the "before", so the
    number is not comparable across arms and must never be reported as one.
    """
    origem = simbolos_ancorados(antes)
    destino = simbolos_ancorados(depois)
    perdidos = sorted(origem - destino)
    return {
        "antes": len(origem),
        "depois": len(origem & destino),
        "razao": (len(origem & destino) / len(origem)) if origem else 1.0,
        "perdidos": perdidos,
    }


def deve_disparar(cfg: RescueConfig, contexto: dict[str, Any] | None) -> bool:
    """``sempre`` × ``ao_estourar`` (study note §3.1 — open study point).

    Under ``ao_estourar`` the summariser only runs when the budget cut actually
    dropped something; in the sessions where the selected block already fits, C
    is byte-for-byte B, and the effective n of Q3 is not the reported n. Which
    is why the frequency is reported per arm instead of assumed.
    """
    if cfg.gatilho == "sempre":
        return True
    contexto = contexto or {}
    return bool(contexto.get("estourou")) or int(contexto.get("cortadas", 0)) > 0


def fatiar(corpo: str, unidade: str) -> list[str]:
    """Split the selected body into summarisation units (study note §3.2)."""
    entradas = [parte for parte in corpo.split("\n\n") if parte.strip()]
    if unidade == "bloco":
        return ["\n\n".join(entradas)] if entradas else []
    if unidade == "entrada":
        return entradas
    grupos: dict[str, list[str]] = {}
    for entrada in entradas:
        arquivo = entrada.splitlines()[0].split("::", 1)[0].strip()
        grupos.setdefault(arquivo, []).append(entrada)
    return ["\n\n".join(itens) for itens in grupos.values()]


def montar_corpo_da_requisicao(cfg: RescueConfig, registro: str) -> dict[str, Any]:
    """The request body that goes on the wire.

    E-1, extended to the *second* model call (study note §3.6): sampling is
    stamped in the body and inspected in the body — never trusted to a config
    object. ``seed`` is not written, because nothing here puts it on the wire.
    """
    prompt = cfg.prompt_text()
    conteudo = prompt.replace("{registro}", registro) if "{registro}" in prompt else (
        f"{prompt}\n\n<registro>\n{registro}\n</registro>"
    )
    return {
        "model": cfg.modelo_id,
        "temperature": cfg.temperatura,
        "max_tokens": cfg.max_tokens_saida,
        "messages": [{"role": "user", "content": conteudo}],
    }


class Sumarizador:
    """Callable handed to ``projetar`` as ``summarizer_fn``.

    ``provider_fn`` takes the request body and returns the text. The tests pass
    a fake one: no API key, no live HTTP, and the body itself is what gets
    asserted on.
    """

    def __init__(self, cfg: RescueConfig, provider_fn: Callable[[dict[str, Any]], Any]):
        self.cfg = cfg
        self.provider_fn = provider_fn
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, corpo: str, contexto: dict[str, Any] | None = None) -> Resumo | None:
        if not deve_disparar(self.cfg, contexto):
            return None
        partes = fatiar(corpo, self.cfg.unidade)
        saidas: list[str] = []
        for parte in partes:
            body = montar_corpo_da_requisicao(self.cfg, parte)
            self.corpos.append(body)
            resposta = self.provider_fn(body)
            texto = "" if resposta is None else str(
                resposta.get("text") if isinstance(resposta, dict) else resposta
            )
            if texto.strip():
                saidas.append(texto.strip())
        from tau_intent.telemetry import count_tokens

        if not saidas:
            # The provider answered nothing. That is a failure of the call, not
            # a trigger that declined — the two must not collapse into one, or
            # a broken summariser reads as a session where C legitimately
            # equals B. ``None`` is reserved for "the trigger said no".
            return Resumo(
                texto="",
                modelo=self.cfg.modelo_id,
                prompt_sha256=self.cfg.prompt_sha256(),
                chamadas=len(partes),
            )

        return Resumo(
            texto="\n\n".join(saidas),
            modelo=self.cfg.modelo_id,
            prompt_sha256=self.cfg.prompt_sha256(),
            tokens_entrada=sum(
                count_tokens(str(body["messages"][0]["content"])) for body in self.corpos
            ),
            tokens_saida=count_tokens("\n\n".join(saidas)),
            amostragem={
                "temperature": self.cfg.temperatura,
                "max_tokens": self.cfg.max_tokens_saida,
                "conferida_no_corpo": True,
            },
            chamadas=len(partes),
        )


def sumarizador_de(
    provider_fn: Callable[[dict[str, Any]], Any], cfg: RescueConfig | None = None
) -> Sumarizador:
    return Sumarizador(cfg or load_rescue_config(), provider_fn)


def preservacoes_checaveis(cfg: RescueConfig, antes: str, depois: str) -> dict[str, Any]:
    """The half of ``preservar_obrigatorio`` that is deterministic.

    ``simbolo_ancorado`` and ``distincao_property_why`` are checkable from the
    text; the rest of the prompt's obligations need graded evaluation, which is
    §3.3 of the study note and not this slice.
    """
    exigidas: Sequence[str] = cfg.preservar_obrigatorio
    resultado: dict[str, Any] = {}
    if "simbolo_ancorado" in exigidas:
        resultado["simbolo_ancorado"] = recall_de_simbolo(antes, depois)["razao"] == 1.0
    if "distincao_property_why" in exigidas:
        tinha = "Propriedade:" in antes and "Por que:" in antes
        resultado["distincao_property_why"] = (
            not tinha or ("Propriedade:" in depois and "Por que:" in depois)
        )
    return resultado


def provedor_falso(regra: Callable[[str], str] | None = None) -> Callable[[dict[str, Any]], str]:
    """Deterministic stand-in for a provider. No API key, no HTTP.

    Reads the request body — the same body a real transport would put on the
    wire — and returns a shortened registro built from it. Tests assert on the
    body, never on a config object (E-1, study note §3.6).
    """

    def chamar(body: dict[str, Any]) -> str:
        conteudo = str(body["messages"][0]["content"])
        # rsplit: the prompt itself names the tags when it explains the
        # boundary, so the real payload is after the LAST opening tag.
        registro = conteudo.rsplit("<registro>", 1)[-1].split("</registro>", 1)[0].strip()
        if regra is not None:
            return regra(registro)
        linhas: list[str] = []
        for entrada in registro.split("\n\n"):
            partes = [linha.strip() for linha in entrada.splitlines() if linha.strip()]
            if not partes:
                continue
            cabeca = partes[0]
            prop = next((p for p in partes if p.startswith("Propriedade:")), "")
            why = next((p for p in partes if p.startswith("Por que:")), "")
            bloco = [cabeca]
            if prop:
                bloco.append("  " + " ".join(prop.split()[:6]))
            if why:
                bloco.append("  " + " ".join(why.split()[:6]))
            linhas.append("\n".join(bloco))
        return "\n\n".join(linhas)

    return chamar


def sumarizador_falso(cfg: RescueConfig | None = None, **overrides: Any) -> Sumarizador:
    """A summariser wired to ``provedor_falso``, for the CLI demo and the bench."""
    from dataclasses import replace

    base = cfg or load_rescue_config()
    if not base.modelo_id:
        overrides.setdefault("modelo_id", "fake-summarizer-v1")
    overrides.setdefault("habilitado", True)
    return Sumarizador(replace(base, **overrides), provedor_falso())
