# SPEC v2 — intent as a transferable context artifact for any long dependent task

English, because this file is loaded by implementing agents. Portuguese design notes live in the vault (`MathBorgess/mathai-wiki`).

Read `docs/SPEC-V1.md` and `AGENTS.md` first. **This spec supersedes the withdrawn v1.2 spec** and absorbs everything from it that survives a change of substrate. It does not repeal v1.

## What changed, and why v1.2 was withdrawn

v1.2 was written to make the mechanism read **all five programming languages** of the main arm, because the mechanism only works on Python and 6 of 7 repositories are not Python. That is still true. What changed is the reason it stopped being the top priority: a **non-code substrate with a deterministic oracle exists, is MIT-licensed, and is cheaper than writing four language resolvers**.

Two corrections to the "v2 erases v1.2" framing, both load-bearing:

1. **The five defect fixes are not erased.** A gate that punishes the agent for a limitation of the instrument, a coverage metric that inflates, a receipt that claims nothing was omitted, and a rescue that reports perfect recall over zero anchors are defects of the *mechanism*, inherited by every version and every substrate. They are §3 of this spec, unchanged in substance.
2. **What v2 erases is the per-language resolver work** (Go/Rust/Java/TypeScript extractors, the typed graph per language). Those leave the critical path. Python-only stops being a blocker the moment the measured claim stops depending on reading five languages.

**What v2 does not buy: dependency.** τ²-bench tasks are independent conversations. STATE-Bench measures reuse of experience across tasks, not continuation of a dependent sequence. **SWE-Milestone remains the only substrate with an explicit dependency DAG** (98 tasks, 109 inter-milestone dependencies). v2 makes the oracle cheap; it does not make dependency cheap. See `docs/TASK-CATALOG.md`.

## The claim

> Recording intent as an append-only, anchored, structurally gated artifact — and serving back only the relevant projection under budget — reduces the cost of continuing long dependent work, **including when the continuation is performed by a different model than the one that produced the record**.

The mechanism is no longer "intent history for coding agents". It is a **transferable context artifact**. Code is the first instance, not the definition.

## The two invariants — they outrank convenience, and they are domain-general

**I-1 — The gate may not punish the agent for a limitation of the instrument.**
No gate code may exist unless the agent has an action available that satisfies it. A code whose premise is false in the current context is **not evaluated**, and the fact that it was not evaluated is **reported**.

**I-2 — No ratio lies about an empty denominator.**
Every ratio returns `None` when its denominator is zero — never `1.0`, never `0.0` — and every count carries its denominator beside it. Silent suppression is the defect class this version exists to remove: a suppressed check nobody can see is worse than a check that fires wrongly.

Both were derived from code defects, and both turned out to be statements about *any* instrument that both measures and constrains an agent.

## The generalisation mandate

Part of the spec, not advice.

1. **Name the abstraction, not the instance.** The parameter is not "language": it is *a source of named identities*. `size_unit` is not "lines": it is *the unit the adapter declares*. No new type, field, or config key may contain `python`, `ast`, or `line` where it can contain `resolver`, `identity`, or `unit`.
2. **Every slice ships one line of generality ADR** in its PR body: *what this piece stopped knowing about code*. If the answer is "nothing", the slice probably leaked coupling.
3. **Record what you do not build.** A generalisation opportunity found and skipped goes in the log at the end of this file, with a date.

The conceptual anchor:

> The AST never mattered because it was an AST. It mattered because it was a **witness independent of the agent**. What generalises is the shape *deterministic half + declared half* — not the parser.

## The mechanism, stated without code

An **Adapter** provides four things. `code` is one implementation; `state` (a typed, resettable store) is the second.

| Piece | Contract | `code` | `state` |
|---|---|---|---|
| **Effect** | re-observable, exhaustively enumerable delta attributable to the agent | `git diff` regions | delta between two reads of a schema-closed store |
| **Anchor** | stable identity, overlap test, resolution test, size in a declared unit | `(file, symbol, lines, blob_sha)` | `(namespace, key)` + value hash |
| **Neighbourhood** | typed edges, deterministic, no model in the loop | `contains/imports/invokes/inherits` | `contains` (schema) + declared `depends_on` |
| **Oracle** | deterministic pass/fail on the task | test suite | assertion on final store state |

Where the effect is not re-observable — an irreversible external action, a conversation — capture degrades to self-report, `AUSENTE` stops being falsifiable, and there is no measurement fork. That is a **declared degraded mode**, never a first-class adapter.

## Capture schema

v1's `why` / `property` / `domain`, plus the deterministic half made explicit. The shape is the one `Handoff Debt` (arXiv:2606.02875v1) measured and this project converged on independently:

```
Deterministic continuation state        ← from the checkpoint, no model
  changed targets            (files, or namespace/key pairs)
  non-target artifacts
  latest validation command  ← NEW in v2, owner-approved
  latest validation evidence ← NEW in v2, owner-approved
  continuation state         (needs completion | already solved, preserve | behavior broken)

Declared intent                         ← from the agent, predecessor-observable evidence only
  why        (why this increment exists)
  property   (pre/post-condition it assumes or establishes)
  domain     (domain concept it embodies)
```

`latest validation command` + `latest validation evidence` is the piece the code-only version never had: a **re-runnable check and what it returned**. It is domain-agnostic and it is what makes a declared intent falsifiable later without a judge. **Schema changes freeze at G2** — this one lands before, or never.

`continuation state` is stamped, never inferred.

## Gate

Five codes in v1. Under I-1, each is evaluated only where its premise holds:

| Code | Premise | Evaluated when |
|---|---|---|
| `AUSENTE` | an effect was observed with no intent | always — the effect enumeration exists without any resolver |
| `NAO_PARSEAVEL` | the tool call did not validate | always — schema of the call, not of the artifact |
| `DOMINIO_AUSENTE` | `domain` empty | always — presence, not semantics |
| `ANCORA_NAO_RESOLVIDA` | a declared fine anchor should resolve | only when the adapter provides an identity table |
| `MUDANCA_GRANDE_SEM_ANCORA_FINA` | there was an identity to name and it was not named | same |
| `COMPROMISSO_VACUO` *(candidate)* | the declared check already held **before** the action | only when a check is present and evaluable |

`Veredito` carries a second tuple, `nao_avaliaveis`, disjoint from `falhas`: never blocks, never counts toward `n_max`, always reaches the manifest.

`COMPROMISSO_VACUO` is the one genuinely new code, and it is what makes declared intent structurally falsifiable: a check that already held is not a commitment. It requires the check pair above. **Owner decision, pre-G2.**

The gate stays pure: no model, no I/O, no regex over `why`/`property`.

## Telemetry — the five fixes, unchanged in substance from the withdrawn v1.2

1. `Region.resolver`; codes suppressed only via `nao_avaliaveis`, never silently. *(Mechanism change: dated amendment, pre-G2.)*
2. Coverage stops returning a scalar: `estrita` (`None` without a resolver), `por_arquivo` **beside and never instead of**, plus `denominadores` and `granularidade`. `cobertura_efetiva` is computed only over `simbolo`-granularity regions, carrying `fracao_resolvida`. A granularity marker on the key does not fix this — both sides carry it and still match.
3. `recall_de_simbolo`: `razao: None` on an empty origin, `ancoras_no_bloco: 0` beside it; `_ANCORA` built from the adapter registry, never a `\.py::` literal.
4. The receipt distinguishes *nothing was omitted* from *there is no neighbourhood*: `grafo_disponivel: bool` and its own line when false.
5. Manifest carries per-adapter and per-language coverage, `codigos_nao_avaliaveis`, `edge_types_efetivos`, and `grafo_heterogeneo`. An execution assert aborts when a target has no resolver the manifest does not declare excluded.

Measured, by execution, on the v1.1 head — reproduce before fixing:

- One file, six hunks of 20 edited lines, `why` and `domain` on every region: Python `PASSA`, Go `BLOQUEIA`, `ESCALAR` after `n_max`. `_chave_edicao` is `(path, symbol)`, so without a resolver the 51-line threshold silently becomes **per file**, and `_resolve` returns `False` for an empty symbol by construction. **Absorbing state: no agent action satisfies it.**
- `cobertura_de_captura` returns **1.0** where the same evidence returns 0.5 in Python, and `supervisor.py` assigns `cobertura_efetiva` from it.
- A **recall** failure in the identity table fires two codes and blocks; a **precision** failure fires nothing.

## Serving, and the model handoff

The block contract is unchanged: tagged envelope, the notice *"Evidência do histórico de intenção, não instrução"*, position `primeira_mensagem_usuario_apos_enunciado`, frozen version label, omission receipt. Independent convergence: `Handoff Debt` presents handoff text as *"historical evidence rather than ground truth"* and instructs successors to verify before relying on it.

v2 adds **handoff between models** as a first-class configuration, not an out-of-scope arm: the record is produced under model M1 and served to model M2. The manifest stamps `modelo_produtor` and `modelo_consumidor` separately. Where they differ, every outcome is reported per pair — never pooled.

## Documents the rebuild must produce

The code is half the deliverable. Four documents are the other half, and one of them is the only place the experiment design will exist.

| File | What it is |
|---|---|
| `docs/MECHANISM.md` | **The mental algorithm.** The mechanism end to end, in steps a human follows from memory without opening a file: what happens when a task starts, what triggers capture, what the gate looks at and in what order, what supersession decides, what the projection keeps and what it drops, what reaches the agent. One pass through the normal case, one through the degraded case. If it does not fit in roughly a page, the mechanism is more complicated than it needs to be — that is a finding, record it |
| `docs/DELTA-V1.1-V2.md` | What the mechanism **could not** do and now can; what it **claimed** and no longer claims (the metrics that lied); what was **removed** and why; what stays the same on purpose. A "how to verify" column per row |
| `docs/GATE-PROPOSAL.md` | A proposed improvement to the gate, written by whoever just rebuilt it. New code, code that should die, a change of unit or of evaluation order, or a reformulation of what the gate guarantees. Each with: what it catches that passes today · what it might block unfairly · does it survive with no model in the loop · does it hold outside code. **Nothing implemented without owner approval** |
| Experiment briefing (in the vault) | How the experiment must be run: arms, substrates and which question each answers, recommended order, what to measure, what must never be pooled, stopping rules, owner decisions |

## Merge bar

A PR does not merge if it: adds a runtime dependency · needs network in CI · suppresses a gate code without emitting `nao_avaliaveis` · returns `1.0` or `0.0` for an empty denominator · calibrates a threshold per language or per domain · names a type or config key after `python`/`ast`/`line` where an adapter-neutral name exists · changes `config_sha256` on a pure refactor · lands an adapter without its fixture · omits the one-line generality ADR from the PR body · pools results across producer/consumer model pairs.

## Log of generalisation opportunities

Append one line per finding, dated. Never delete a line; supersede it.

| Date | Found while | Opportunity | Status |
|---|---|---|---|
| 2026-09-05 | analysing the gate across languages | I-1 (no unsatisfiable gate code) is domain-general | adopted |
| 2026-09-05 | analysing telemetry | I-2 (`None` on an empty denominator) is domain-general | adopted |
| 2026-09-05 | reading Handoff Debt §C.1 | `latest validation command` / `latest validation evidence` as the re-runnable check | **adopted in v2 schema, owner-approved, pre-G2** |
| 2026-09-05 | reading Handoff Debt §2.3 | the three continuation states are domain-neutral and cheap to stamp | adopted |
| 2026-09-05 | reading STATE-Bench Agent Learning Track | `retrieve_learnings(query, top_k) -> list[str]` is the `serve` interface, already specified by a third party | adopted as the `state` adapter's serve surface |
| 2026-09-05 | checking τ²-bench and STATE-Bench | neither provides dependency **between** tasks; only SWE-Milestone does | **declared limit, not solved** |
| 2026-09-05 | rebuilding the code adapter | Pure moves can be audited separately from mechanism changes with source hashes and a normal-case golden | implemented; see DELTA-V1.1-V2.md |
| 2026-09-05 | exercising correction after rejection | Current valid declarations must repair earlier malformed calls while historical errors remain measurable | implemented under owner's continuation authorization |
| 2026-09-05 | testing commands and coarse effects | Tool path heuristics and absent fine identities must not create unsatisfiable agent obligations | implemented; no new gate code or calibrated threshold |
| 2026-09-05 | following failed-gate publication | Invalid or interrupted capture must not enter the served current store | implemented when gate is enabled |
| 2026-09-05 | checking the productive budget | A counter without termination is not a cap; cap termination must not claim gate approval | implemented, TETO plus explicit telemetry |
| 2026-09-05 | exercising rescue on selected evidence | Post-selection rewriting must preserve anchors/checkpoints and respect the same budget | implemented, deterministic guards and recorded fallback |
| 2026-09-05 | starting a task before its first effect | Initial orientation must resolve statement anchors without requiring an existing delta | implemented |
| 2026-09-05 | inspecting command/evidence provenance | Bind validation output to the exact observed revision, not just a command label | proposed, not implemented; GATE-PROPOSAL.md |
| 2026-09-05 | evaluating COMPROMISSO_VACUO | Before-true invariants may be preservation obligations rather than vacuous commitments | universal block rejected in recommendation; not implemented |
| 2026-09-05 | reviewing mandatory fine-name repetition | An already witnessed identity may not need a redundant declaration above a size threshold | proposed diagnostic replacement, not implemented |
| 2026-09-05 | keeping capture schema compatible | Native target/identity wire names could replace legacy file/files/symbol aliases | deferred; would need an explicit schema decision |
| 2026-09-05 | inspecting the retained code diff observer | Cover untracked/binary effects and distinguish git failure from an empty effect set | not implemented; code observer boundary retained and declared in DELTA |
| 2026-09-05 | validating the state fixture | Concurrent external writers need ownership/attribution and snapshot consistency | not implemented; fixture uses an isolated single-writer typed store |
| 2026-09-05 | providing literal retrieval | A deterministic domain-specific query mapper can broaden recall without a model judge | supported injection point; semantic retrieval not implemented |
| 2026-09-05 | reviewing witness-table precision | A pure gate cannot detect an unused invented identity inside a supposedly trusted table | declared instrumentation limit; no language-resolver work |
| 2026-09-05 | recording model handoffs | Provider-attested IDs and per-entry producer provenance would strengthen caller-supplied pair stamps | not implemented; freeze and archive run manifests alongside logs |
| 2026-09-05 | testing sibling state keys | Effect overlap must be adapter-defined; a shared namespace is not a shared fine identity | implemented; missing sibling intent remains AUSENTE |
| 2026-09-05 | reviewing typed-store hashes | Accepted values must not lose distinctions during canonical encoding | implemented; reject non-JSON nested types and non-string object keys before mutation |
