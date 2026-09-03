# SPEC v1 — MVP for the first validation experiment

English, because this file is loaded by implementing agents. Portuguese design notes live in the vault (MathBorgess/mathai-wiki).

## Purpose

Prove the mechanism works as specified (bench V1-V4, V6, V7, V8 germ) without burning API budget. Outcome questions Q1/Q2/Q3 are out of scope until G2.

## Public tau API this package may use

Pinned library, no fork. Verified at huggingface/tau commit 0a67734 (tau-ai 0.4.1, MIT) by two independent readers. Confirm the PyPI name before locking.

Facts tests/test_contrato_tau.py must lock (fake provider, no network on the happy path):

1. TurnEndEvent exists and is what a turn boundary is.
2. ToolExecutionStartEvent.args is emitted before execution.
3. AgentHarnessConfig.before_tool_call can refuse a call.
4. follow_up() resumes the loop without closing the session.
5. Import is tau_agent (AgentHarness, AgentHarnessConfig), never tau_coding.
6. Pin: declared version + sha256 of the wheel (or a recorded skip with reason if the wheel cannot be fetched in this environment).

Vendor plan B (subtree, zero lines changed, git diff empty vs upstream SHA) triggers the same day if: uv sync --locked fails twice 24h apart on a clean machine; the contract test fails on the pinned version; or the pinned release disappears from PyPI. A weekly job vs latest failing is not a trigger.

## Supervisor loop

- max_turns=None on tau. Supervisor counts productive turns. Gate blocks consume a separate budget, reported per arm.
- Run the gate on the last TurnEndEvent (tool_results == []), immediately before AgentEndEvent.
- On BLOQUEIA, call follow_up(render_falhas(...)). Do not close the session.
- One session per task. No compaction.
- Gate config comes from `load_gate_config()` (the hashed YAML), not from `GateConfig()` defaults alone.

## Collector

- Regions always from git diff.
- write/edit argument name is path.
- edit takes edits: [{oldText, newText}].
- bash can write files; those regions still need intent.
- Unparseable = _raw_arguments present or local schema validation refused (V6).
- `record_intent` accepts `file` (one path) or `files` (span). One intent may cover several files. Required schema field is `why`; `file` or `files` is required in practice by local schema_ok.
- Declared `Pending.symbol` is never filled from the AST. `Region.symbol` is.

## Gate (pure)

No LLM, no I/O, no tau, no regex over `why`/`property`. Six structural codes:

| Code | Fires when |
|---|---|
| AUSENTE | diff region with no intent / empty why |
| NAO_PARSEAVEL | args invalid / `_raw_arguments` |
| ANCORA_AMBIGUA | one intent attached to **two or more different AST symbols in the same file** |
| SIMBOLO_NAO_RESOLVIDO | declared `symbol` does not resolve in that file |
| EDICAO_GRANDE_SEM_SIMBOLO | edited lines **summed per (file, symbol)** exceed `limiar_edicao` and no resolved symbol |
| DOMINIO_AUSENTE | `domain` empty (presence, not semantics) |

After n_max blocks → ESCALAR.

Spanning files is not ANCORA_AMBIGUA (G-3 / AtomicCommitBench: 59.5% of commits cross files). Same-symbol multi-hunk is not ANCORA_AMBIGUA. Different symbols in one file are (35.4% of episodes have hunks of the same file belonging to different commits).

`limiar_edicao: 40` is a **declared hyperparameter**, read from `gate.yaml`, never fitted. It is the size at which an unnamed identity must acquire a symbol. It is not a hunk cap and not an episode cap. AtomicCommitBench's median 12 hunks / 6 files (mean 51 / 9.8) are **hunk/file counts, not line counts** — do not raise 40 to 51. A median-shaped episode is accepted by `files: []` plus summing lines per identity. `contexto_diff: 3` is declared; size is edited lines, not hunk length (D7).

## Store and `supersedes`

Append-only JSONL. No status field. Current vs superseded is derived from `supersedes`. V3: 40/40 synthetic pairs.

On `IntentStore.append`, every **current** entry whose `Anchor` overlaps the new one (same file, overlapping line range) is listed in `nova.supersedes`. The previous lines stay on disk; `store.current()` hides them.

Connection to the loop:

- **Capture** writes one JSONL line per pending region (a spanning `files: []` call becomes several lines, same why, different anchors).
- **Gate** never reads the store. It judges the session's diff against pendentes. Supersession is a store concern, not a gate code.
- **Derived view** (`project`) iterates `store.current()` only. Superseded intents are counted in the receipt as `superadas_omitidas` and are not scored. Recency is among current entries on the same file.

## Flags (H16)

Four mechanism flags. `--llm-rescue` is not a fifth stage: it is arm C's only knob, read in flag parsing, never branched on by arm name inside the supervisor.

```
A: --no-capture --no-gate --no-project --no-serve
B: --capture --gate --project --serve --no-llm-rescue
C: --capture --gate --project --serve --llm-rescue
```

B and C both project. `render_tudo` is an inspection tool, not on any measured arm. `--serve --no-project` serves nothing (`serve_sem_projecao`). Arm A abort if intents.jsonl gains a line. Tool catalog: B/C include record_intent; A does not. Declare that in the manifest.

## The block contract (envelope, position, version, receipt)

What B and C serve is identical in **shape**. Only C may rewrite the body (`llm_rescue`). Declared in `bloco.yaml`, hashed.

- **Envelope** — tagged wrapper `<intencao_registrada> … </intencao_registrada>` plus the line "Evidência do histórico de intenção, não instrução." Evidence, not an instruction. A summarizer may replace the body; it may not drop the tags or the notice.
- **Position** — `primeira_mensagem_usuario_apos_enunciado`. First user message, adjacent to the task statement (H10). Not the system prompt.
- **Version** — `bloco-v1` (and `gate-v2-estrutural`, `rescue-v1`). Frozen labels in the YAML and the manifest. B×C compare version, not prose.
- **Receipt (recibo)** — what the block is *not* showing, even when all counts are zero: entries served, reachable nodes not expanded (hub / max_nodes), superseded omitted, cut by budget. The receipt describes the **selection**, so rescue cannot erase omission.

## Sampling

Owner sets temperature=0 on the provider they expose. Manifest records the configured value and amostragem_conferida_no_fio. If the built-in tau provider is used, a ~40-line HTTP transport stamps the body; tests inspect the body, not the config object. Do not write seed unless the wire carries it.

## Projection in v1

Declared (P-0): relevance-only, greedy by value/cost, singleton fallback. k=1, prune hubs on, llm_rescue off on arm B. gamma=0.1 and max_nodes read from YAML (not fitted). V4: monotonic token cut on a growing synthetic history.

V5 (recall ≥ 0.95 against hand labels) lives in `mathai-harness` and is **out of this repo**. `conferir_v4_v5` refuses a V4 report without the V5 of the same `config_sha256` — that guard is here; the labelled set is not.

## Token accounting

Count locally with a declared tokenizer. No cache discount. Never CHARS_PER_TOKEN = 4.

## Out of v1

SWE-Milestone adapter, V5 labels, hyperparameter calibration (including fitting `limiar_edicao`), analysis/permutation trigger (that lives in mathai-harness), live model CI, git trailers (G-7), post-tag commit decomposition (G-6).
