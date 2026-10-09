"""The derived view, pulled by the agent (Q5/Q12, owner 2026-10-09).

In ``consulta`` mode nothing is pushed beside the statement. The first message
carries an instruction and an index of the files that have recorded intent;
the agent calls ``recall_intent`` with the files or symbols it is about to
touch and gets the same projection the v1 block used — deterministic, 1 hop,
deduplicated, budgeted, with the omission receipt — anchored where it asked.

Why pull: the owner wants to measure *when* the agent believes it needs the
history and in which cases it does not. A pushed block answers that question
for the agent; a tool lets it answer, and every call is telemetry.

Selection stays model-free. ``llm_rescue`` is not defined here (Q13: arm C is
not part of the experiment that uses this mode), and the supervisor refuses
the combination instead of silently serving arm B.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from tau_intent.config import BlocoConfig, load_bloco_config
from tau_intent.project import _colapsar_duplicadas, load_project_config, projetar
from tau_intent.store import IntentStore
from tau_intent.telemetry import chave, count_tokens

SEM_HISTORICO = "No recorded intent for these files or symbols."
INDICE_VAZIO = "No intent has been recorded yet."


def instrucao_de_consulta(entries: Sequence[Any], cfg: BlocoConfig | None = None) -> str:
    """The instruction of the first message, with the index of files that have history.

    The index names files and how many distinct entries each has; it carries no
    entry text, so what the agent learns from it is *where* to ask, not *what*.
    """
    cfg = cfg or load_bloco_config()
    indice = ""
    if cfg.consulta_indice:
        unicas, _ = _colapsar_duplicadas(list(entries))
        por_arquivo = Counter(str(getattr(getattr(e, "anchor", None), "file", "") or "") for e in unicas)
        por_arquivo.pop("", None)
        indice = ("Files with recorded intent: "
                  + ", ".join(f"{f} ({n})" for f, n in sorted(por_arquivo.items())) + "."
                  if por_arquivo else INDICE_VAZIO)
    return cfg.texto_de_consulta().format(indice=indice).strip()


class RecallService:
    """What ``recall_intent`` runs. One instance per unit; it logs every call.

    The store is re-read on every call: the log is append-only and another
    unit may have published since this object was built.
    """

    def __init__(self, store: Any, adapter: Any, workspace: Path | str, *,
                 bloco_cfg: BlocoConfig | None = None) -> None:
        self.store_path = Path(getattr(store, "path", store))
        self.adapter = adapter
        self.workspace = Path(workspace)
        self.cfg = replace(load_project_config(), llm_rescue=False,
                           edge_types=tuple(getattr(adapter, "edge_types", ()) or load_project_config().edge_types))
        self.orcamento = (bloco_cfg or load_bloco_config()).token_budget
        #: Set by the supervisor when it sees the tool start, so a call knows its turn.
        self.turno_atual: int | None = None
        self.chamadas: list[dict[str, Any]] = []
        self.servidas: list[Any] = []

    def __call__(self, paths: Sequence[str] = (), symbols: Sequence[str] = ()) -> dict[str, Any]:
        store = IntentStore(self.store_path)
        correntes = store.current()
        graph = self.adapter.neighbourhood(self.workspace)
        ancoras = self._ancoras(paths, symbols, graph, correntes)
        bloco, tel = (projetar(graph, correntes, ancoras, self.cfg, self.orcamento,
                               superadas=max(len(store._entries) - len(correntes), 0))
                      if ancoras else ("", {"servidas": [], "recibo": None, "duplicadas_colapsadas": 0}))
        servidas = list(tel.get("servidas") or [])
        texto = bloco if servidas else SEM_HISTORICO
        self.servidas.extend(servidas)
        self.chamadas.append({
            "ordem": len(self.chamadas) + 1,
            "turno": self.turno_atual,
            "paths": list(paths),
            "symbols": list(symbols),
            "ancoras": ancoras,
            "n_entradas": len(servidas),
            "entradas": [getattr(e, "id", None) for e in servidas],
            "chaves": [chave(e) for e in servidas],
            "tokens": count_tokens(texto),
            "recibo": tel.get("recibo"),
            "duplicadas_colapsadas": tel.get("duplicadas_colapsadas", 0),
        })
        return {"ok": True, "intent": texto}

    def _ancoras(self, paths: Sequence[str], symbols: Sequence[str], graph: Any,
                 correntes: Sequence[Any]) -> list[str]:
        """Graph node ids for what the agent asked.

        A bare name matches every ``file::name`` and every dotted def that ends
        in it (``fit`` finds ``file::LDA.fit``); the projection maps a dotted
        name to its graph node.
        """
        conhecidos = set(getattr(graph, "nodes", {}) or {}) | {chave(e) for e in correntes}
        ancoras: list[str] = []
        for path in paths:
            path = str(path).strip().removeprefix("./")
            if path:
                ancoras.append(path)
        for symbol in symbols:
            symbol = str(symbol).strip().removeprefix("./")
            if not symbol:
                continue
            if "::" in symbol:
                ancoras.append(symbol)
            else:
                ancoras.extend(sorted(n for n in conhecidos
                                      if n.endswith("::" + symbol) or n.endswith("." + symbol)))
        return list(dict.fromkeys(ancoras))
