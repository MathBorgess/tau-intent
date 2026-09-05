# SPEC v1.2 — capture that does not depend on Python

English, because this file is loaded by implementing agents. Portuguese design notes live in the vault (`MathBorgess/mathai-wiki`).

Read `docs/SPEC-V1.md` and `AGENTS.md` first. **This spec adds; it does not repeal.** Where it changes v1 behaviour it says so explicitly, and those changes are mechanism changes that must land **before the G2 freeze**.

## Purpose

Today the mechanism runs on **1 of the 7 repositories** of the main arm. v1.2 makes it able to receive **all 98 tasks** — and does so by removing a dependency on Python, not by adding Python-shaped special cases.

The reason the second half of that sentence matters: this package exists to test whether recorded intent helps an agent continue long dependent work. If that holds for code, the same mechanism should help **any hand-off of context between agents on long tasks**. Every abstraction in v1.2 is therefore written so that `code` is *one* instance of it. See `docs/V2-GENERALIZATION.md`.

## The measured facts this spec answers to

Verified by execution against the v1.1 head, not by reading:

1. One file, six hunks of 20 edited lines, every region carrying `why` and `domain` — **Python `PASSA`, Go `BLOQUEIA`** with `EDICAO_GRANDE_SEM_SIMBOLO`, and `ESCALAR` after `n_max`. `_chave_edicao` is `(path, symbol)`, so without a resolver every region of a file collapses into `(path, "")` and the 51-line threshold silently becomes **per file**. `_resolve` returns `False` for an empty symbol by construction, so the second condition of the code is always satisfied. **It is an absorbing state: no agent action satisfies it.**
2. `cobertura_de_captura` returns **1.0** for the same evidence that returns 0.5 in Python, because `chave()` degrades regions and entries to the file level **together**. `supervisor.py` assigns `cobertura_efetiva = cobertura_de_captura`, and that is the moderator of the primary model.
3. A **recall** failure in a symbol table fires two gate codes and blocks; a **precision** failure fires nothing.

## Two invariants, and they outrank convenience

**I-1 — The gate may not punish the agent for a limitation of the instrument.**
No gate code may exist unless the agent has an action available that satisfies it. A code whose premise is false in the current context is **not evaluated**, and the fact that it was not evaluated is **reported**.

**I-2 — No ratio lies about an empty denominator.**
Every ratio returns `None` when its denominator is zero — never `1.0`, never `0.0` — and every count carries its denominator beside it. Silent suppression is the defect class this whole version exists to remove; a suppressed check that nobody can see is worse than a check that fires wrongly.

## The generalisation mandate

Three working rules for whoever implements this. They are part of the spec, not advice.

1. **Name the abstraction, not the instance.** The parameter is not "language": it is *a source of named identities*. `size_unit` is not "lines": it is *the unit the adapter declares*. No new type, field, or config key may contain `python`, `ast`, or `line` where it can contain `resolver`, `identity`, or `unit`.
2. **Every slice ships one line of generality ADR** in its PR body: *what this piece stopped knowing about code*. If the answer is "nothing", the slice probably leaked coupling — revisit before merging.
3. **Record what you do not build.** A generalisation opportunity you find and skip goes into `docs/V2-GENERALIZATION.md` with a date. It never dies in a conversation.

The conceptual anchor, and it is load-bearing:

> The AST never mattered because it was an AST. It mattered because it was a **witness independent of the agent**. What generalises is the shape *deterministic half + declared half* — not the parser.

## Interfaces

Static registry, never a runtime plugin: a plugin loaded at runtime does not freeze under a hash.

```python
# tau_intent/langs/__init__.py
class Identity(NamedTuple):
    name: str          # "Server.Handle" (Go, receiver included); "Type::method" (Rust impl)
    line_start: int
    line_end: int
    kind: str          # "func" | "method" | "type" | "class" — declared, never semantic

class LanguageResolver(Protocol):
    lang: str                      # "python" | "go" | "rust" | "java" | "ts"
    extensions: tuple[str, ...]
    nivel: int                     # the level it CLAIMS; the bench verifies
    size_unit: str = "linhas_editadas"

    def identities(self, source: str) -> list[Identity]: ...
    def edges(self, source: str, fid: str, file_ids: set[str]) -> list[tuple[str, str, str]]: ...

REGISTRO: dict[str, LanguageResolver]          # by extension, built at import
def resolver_para(path: str) -> LanguageResolver | None: ...
```

`size_unit` stays `linhas_editadas` across all five **on purpose**: keeping the unit keeps `limiar_edicao: 51` the *same* declared hyperparameter — badly calibrated outside Python, which is a stated threat — instead of five new ones. G-0 forbids fitting; five per-language thresholds would be fitting with extra steps.

## Gate changes (mechanism change — dated amendment, pre-G2)

`Region` gains `resolver: str | None`. `Veredito` gains a second tuple, `nao_avaliaveis`, disjoint from `falhas`.

| Code | v1.2 behaviour |
|---|---|
| `AUSENTE` | unchanged — fed by the diff, which exists without any resolver |
| `NAO_PARSEAVEL` | unchanged — schema of the tool call, not of the artifact |
| `DOMINIO_AUSENTE` | unchanged — presence, not semantics |
| `SIMBOLO_NAO_RESOLVIDO` | evaluated **only** when `region.resolver is not None`; otherwise `NaoAvaliavel(code, region, motivo="sem_resolvedor:.go")` |
| `EDICAO_GRANDE_SEM_SIMBOLO` | same rule. Its premise — *there was an identity to name and it was not named* — is false without a symbol table |

`nao_avaliaveis` never blocks, never counts toward `n_max`, and always reaches the manifest.

## Telemetry changes

`cobertura_de_captura` stops returning a scalar:

```python
{"estrita":       {"python": 0.5, "go": None},   # None, never 1.0, never 0.0
 "por_arquivo":   {"python": 1.0, "go": 1.0},    # beside, never instead of
 "denominadores": {"python": 2,   "go": 2},
 "granularidade": {"python": "simbolo", "go": "arquivo"}}
```

`cobertura_efetiva` is computed **only over regions of `simbolo` granularity**, and carries `fracao_resolvida` beside it. A granularity marker on the key does not fix this: if both sides carry the same marker they still match, and the number still inflates.

`aproveitamento_do_bloco` gets the same treatment: `razao_estrita` (`None` without a resolver) beside `razao_por_arquivo`, with denominators. It is declared descriptive, but a number that is ~1.0 in six of seven repositories will be read as a language effect no matter how it is labelled.

`recall_de_simbolo` (`rescue.py`): `razao: None` when `origem` is empty, plus `ancoras_no_bloco: 0`. `_ANCORA` is built from `REGISTRO`, never the `\.py::` literal — today `preservar_obrigatorio` is **vacuously satisfied** outside Python.

The receipt distinguishes *nothing was omitted* from *there is no graph*: a `grafo_disponivel: bool`, and its own line when false. The receipt exists to say what is not being shown; today, with a zero-node graph, it prints `0 nós alcançáveis não expandidos`.

## Manifest additions

```yaml
resolvedores:
  go:   {versao: r1, nivel: 2, sha256: <of the .py module>}
  rust: {versao: r1, nivel: 1, sha256: ...}
saida:
  cobertura_de_captura: {estrita: {...}, por_arquivo: {...}, denominadores: {...}}
  cobertura_efetiva: {valor: 0.5, base_regioes_resolvidas: 2, base_regioes_totais: 4, fracao_resolvida: 0.5}
  codigos_nao_avaliaveis: {EDICAO_GRANDE_SEM_SIMBOLO: {go: 6}}
  arquivos_por_linguagem: {go: 10, ts: 3}
  edge_types_efetivos: {go: [contains, imports], rust: [contains]}
  grafo_heterogeneo: true
```

An execution assert — in the spirit of the existing `capture=off wrote intents.jsonl` — aborts the run if a file has no resolver and the manifest does not declare it excluded.

## Resolvers

Pure-Python declaration extractors, not parsers. This is the only option that fits all three walls at once: `dependencies = []`, CI with `NO_NETWORK: "1"`, and freezing by hash of a file **in the tree**. tree-sitter breaks all three (binary wheel, build-time download, artifact outside the tree). ctags would only fit because the manifest already freezes `imagem: <digest>`, and it caps at L2.

**Order, by tasks unlocked — not by repository count, and not by ease:** Go (+32) → Rust (+24) → TypeScript (+18) → Java (+12).

**The resolver does not need to be good. It needs to be measured.** With `L` edited lines in a file and hit rate `p` over declarations, the unresolved residue lands in the `(path, "")` bucket, and blocking requires `L·(1−p) > 51`. So it does not block while:

> **`p ≥ 1 − 51/L`** — 0.49 at `L`=100 · 0.75 at 200 · 0.83 at 300 · 0.90 at 500

The binding criterion is **recall**: a missing name fires two codes and blocks legitimate work; an extra name only loosens the gate. Precision is reported, not optimised — but it is reported, because an over-loose gate moves B toward A and that is a construct threat.

Known error classes to expect and test: generics with `<...>` containing braces (Java/TS/Rust); closures and assigned anonymous functions, which do not become identities; Rust macros generating items; Go methods needing the receiver (`func (s *Server) Handle` → `Server.Handle`); multiline strings and block comments confusing brace counting.

## Graph

`contains` in all five. `imports` where cheap: Go (`import (...)` block), Java (`import a.b.C;` plus directory convention), TS (relative; `tsconfig` `paths` is not cheap). Rust `use`/`mod` with crate paths and re-exports is **not** cheap — Rust may stop at `contains`.

`invokes` by regex is **out**: it would inflate the mean degree and therefore move hub pruning (`lambda_grau=3.0`), which is implicit fitting and violates G-0.

The graph may sit **below** the anchor level, provided `edge_types_efetivos` is stamped per language and the write-up reports that B in Rust measures a poorer projection than B in Python. A varying edge set that does not appear in the manifest is not acceptable.

`estado_da_arvore` must hash the extensions the registry knows, not `*.py`. Today editing a `.go` file does not invalidate the graph cache — bounded impact, because non-Python never enters the graph anyway, but the declared invariant (P-6/D11) is broken.

## Bench

| Test | Criterion |
|---|---|
| **V-equiv** | The `code` adapter reproduces pre-refactor behaviour: `Veredito`, block, and `intents.jsonl` lines identical modulo `id`/`ts`. All 203 existing tests pass unmodified |
| **V-lang** | Arm-B session over a Go fixture: zero symbol failures, `linguagem_suportada=false` in the manifest, `razao: None` from rescue, coverage marked file-granularity, receipt not claiming absence of omission |
| **V-simb-\<lang\>** | Hand-annotated fixture per language: **recall binding**, precision reported; and stability — running the language's official formatter does not change the key set |
| **V-grafo** | Every `node_id` in the store exists as a graph node; zero false `imports` resolutions on an annotated corpus |
| **V-desconhecida** | A fixture in a sixth language behaves as L1 (declared, non-blocking), not as L0 (broken) |

`config_sha256` covers only the five YAML/prompt files, so a pure Python refactor leaves it invariant **by construction**. What moves is the commit SHA — which is exactly why all of this lands before G2.

## Merge bar for v1.2

A PR does not merge if it: adds a runtime dependency · needs network in CI · suppresses a gate code without emitting `nao_avaliaveis` · returns `1.0` or `0.0` for an empty denominator · calibrates a threshold per language · names a type or config key after `python`/`ast`/`line` where an adapter-neutral name exists · changes `config_sha256` · lands a resolver without its `V-simb` fixture · omits the one-line generality ADR from the PR body.

## Out of v1.2

Anything that changes the capture **schema** — including the `latest validation command` / `latest validation evidence` pair discussed in `docs/V2-GENERALIZATION.md` — is out unless the owner decides otherwise, because the schema freezes at G2. `invokes`/`inherits`. tree-sitter. Per-language V5 labelled sets. Non-code adapters.
