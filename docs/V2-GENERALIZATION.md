# V2 — detaching the mechanism from code

Status: **proposal, not scheduled.** Nothing here lands before the G2 freeze. This file exists so that generalisation opportunities found while implementing v1.2 are recorded with a date instead of dying in a conversation (rule 3 of the generalisation mandate in `docs/SPEC-V1.2.md`).

Portuguese design notes: the vault's `pesquisa/tcc/2026-09-05-generalizacao-de-linguagem-e-intencao-geral.md` and `pesquisa/tcc/2026-09-05-handoff-e-heranca-de-contexto-entre-agentes.md`.

## The thesis, and the two clauses that were withdrawn

An earlier formulation said the mechanism generalises to *"any task whose effect is a **versioned** artifact, with a **parser** producing stable named identities, typed relations between them, and a deterministic oracle."* Two independent reviews withdrew two of the four clauses:

> **Versioning was a proxy for a witness of the change that is not the agent. Parsing was a proxy for a typed, resettable state space.** The formulation had the extension right and the intension wrong.

What survives:

> The mechanism generalises as far as there is (i) a **witness of the change independent of the agent** and (ii) a **typed, resettable state space** — and not one step further. The axis was never "long-running task". It is **observability of the effect**.

Two consequences worth stating plainly. Git and the AST are one instance of (i), not its definition. And where (i) fails — an irreversible external action, a conversation, a negotiation — capture degrades to self-report, `AUSENTE` stops being falsifiable, and there is no fork, so no measurement replica. That is a **declared degraded mode**, never a first-class adapter.

## What the handoff literature already validates

`Handoff Debt` (arXiv:2606.02875v1, read in primary source) runs the closest published experiment: interrupt a coding agent at deterministic handoff points, freeze the repository, give successors four views. 75 source tasks → 181 handoff tasks → 724 takeover runs per successor.

Its **structured notes** format is the shape this project should generalise, because it is already domain-neutral:

```
Deterministic continuation state       ← from checkpoint metadata, no model
  Changed source files
  Non-source artifacts
  Latest validation command
  Latest validation evidence
  Continuation state: unresolved; needs completion

Previous-agent notes                   ← from the agent, predecessor-observable evidence only
  Problem understanding
  Work completed
  Evidence observed
  Remaining uncertainty
  Recommended next action
```

Three things to take from it:

1. **The two-half shape is the generalisable unit**, not the parser. `tau-intent` already has both halves — diff/AST and `why`/`property`/`domain`.
2. **`latest validation command` + `latest validation evidence`** is the missing piece: a re-runnable command and what it returned. It is domain-agnostic, it is the *verifiable check* an anchor can be built on, and it is the cheapest single addition on this page. It changes the capture schema, so it is an owner decision, pre-G2 or never.
3. Their prompts present handoff text as *"historical evidence rather than ground truth"* — the same contract as the `<intencao_registrada>` envelope. Independent convergence on the envelope is evidence the envelope is right.

Their measured failure modes are **requirements** for any v2: a compact note that drops the exact validation command; a successor that over-trusts the predecessor instead of rechecking; raw traces too noisy to use. They report a *negative* solved-rate cell for note-based handoff. **Context can hurt.** Whatever v2 becomes, the regression census stays unconditional.

## Anchoring candidates, and what survived scrutiny

| Candidate | Verdict |
|---|---|
| **Observable world state** — `(namespace, key)` for `(file, symbol)`, delta between two observations for the diff, value hash for `blob_sha` | **Strongest.** Breaks on two points: observation is not exhaustive (a diff sees everything; a poll sees what you remembered to ask), so `AUSENTE` only survives under a schema-closed state space; and irreversibility kills the measurement fork |
| **Verifiable commitment** — intent declares a `check` evaluable against state; identity `hash(target, normalised check)`; supersession = incompatible checks on the same target | **Strong, and it makes declared intent falsifiable.** Two pure defences against a lying agent: the check must syntactically reference the target, and it is evaluated against the state **before** the action — if it already held, it is vacuous (`COMPROMISSO_VACUO`). `property` already exists in the schema and today the gate only tests its presence |
| **Tool invocation with canonical arguments** — identity `(tool, canonical(args))` | **Cheapest that keeps an independent witness**, because the harness records the call, not the agent. Sub-merges or over-merges silently, and anchors in *action* rather than *effect* |
| **Rejected alternatives** as identity | **Fails.** Sets are authorial, `{A,B}` and `{A,B,C}` become different identities, and it is gameable: to avoid being superseded, add an alternative. Survives as *evidence* — an alternative declared rejected and later adopted is a detectable contradiction |
| **Temporal-causal adjacency** | **Fails.** Order of execution is a sequence, not a relation; `gamma**hops` would become recency, which is already a scorer term |

## Outcomes without an LLM judge

The hard clause. Reversal observed and rework cost survive a committee but not a calendar (human latency). The one genuinely new candidate:

**Structural contradiction between current intents** — decidable **if and only if** `property` is typed as `(variable, relation, value)` instead of free text. Then `timeout ≤ 30` against `timeout ≥ 60` on the same anchor contradicts by interval arithmetic, with zero model calls. It is H15's spirit one level up, and it makes the mechanism self-falsifying, which is rare.

The objection both reviewers accepted: it measures **consistency, not correctness**. A perfectly consistent and perfectly wrong agent passes. It is a secondary, mechanistic outcome — it does not replace `suite_pass`.

An honest cost, recorded against this project's own rules: comparing reversal across arms would require arm A to have checks **evaluated but not served**. Today arm A aborts if it writes `intents.jsonl`. A general mechanism would have to redefine isolation as *"not served"* rather than *"not captured"*. That is a design change, not a patch.

## Substrate — the part that may be much cheaper than assumed

The v1 conclusion was that a non-code substrate means authoring both a task set and an oracle, i.e. a second thesis. A search on 2026-09-05 suggests otherwise, and **none of it is verified** — verifying it is the first task of any v2 work:

- **τ²-bench** (`sierra-research/tau2-bench`, arXiv 2506.07982) — conversational agents in **non-code** domains (retail, airline, telecom, banking knowledge), dual control, and reportedly scored by **exact match of the final database state against a target state**. If that holds, it instantiates all four requirements outside code: re-observable effect, diff, named identity `(table, record, field)`, deterministic oracle.
  > ⚠️ **Name collision.** This package imports `tau_agent` from `tau-ai==0.4.1`, the Hugging Face harness. τ²-bench is Sierra's, and is a different thing. **Do not imply any relationship** anywhere, in code or prose, until someone verifies it.
- **STATE-Bench** — reportedly has an *Agent Learning* track that feeds trajectories from earlier tasks and tests whether stored memory improves held-out tasks, with deterministic state assertions. If accurate, that is close to a ready-made v2 design.
- **AMA-Bench** (arXiv 2602.22769) — **rejected as a substrate**, on principle: graded by LLM-as-judge. Useful as a taxonomy of memory dimensions (Recall, Causal Inference, State Updating, State Abstraction) and as related work.

## A mechanism designed from scratch, if there were no v1

Recorded because it is the cleanest statement of what the v1 defects taught:

- **Core:** append-only log of **commitments** — `(addressable target, check in a decidable fragment, why in NL, plan node, rejected alternatives, declared edges)`.
- **No parser and no extracted graph.** Identity by `hash(target, check)`. Supersession by decidable contradiction. Declared edges, audited: temporal ordering, target reference, and — the good one — **failure consequence**: `B depends on A` is a *predictive* claim, so if A's check later fails and B's still holds, the declared dependency is **refuted** and stops being traversed.
- **Gate with three codes:** `AUSENTE`, `COMPROMISSO_VACUO`, `COMPROMISSO_INEXPRESSAVEL` — plus invariant I-1 from `SPEC-V1.2.md`, which is what kills unsatisfiable codes at the root.
- **Projection:** same greedy selection under budget with an omission receipt — keep it whole. But the score replaces `gamma**hops` with *current commitments whose check references a target the current task touches*: relevance by reference, not graph distance. Three unjustified hyperparameters (`gamma`, `max_nodes`, `lambda_grau`) die with it.
- **The known limit, and it is the central bet:** the agent can only express what the fragment allows. Unexpressible intent is uncaptured intent, and coverage becomes a function of the check language's expressiveness. Nobody knows whether a fragment small enough to be decidable is large enough for open tasks.

## Log of generalisation opportunities

Append one line per finding, dated, during v1.2 implementation. Never delete a line; supersede it.

| Date | Found while | Opportunity | Status |
|---|---|---|---|
| 2026-09-05 | analysing the gate across languages | Invariant I-1 (no unsatisfiable gate code) is domain-general, not a language fix | adopted in v1.2 |
| 2026-09-05 | analysing telemetry | Invariant I-2 (`None` on an empty denominator) is domain-general | adopted in v1.2 |
| 2026-09-05 | reading Handoff Debt §C.1 | `latest validation command` / `latest validation evidence` as the re-runnable check | **owner decision — schema change, pre-G2 or never** |
| 2026-09-05 | reading Handoff Debt §2.3 | The three handoff states (*needs completion* / *already solved; preserve* / *existing behavior broken*) are domain-neutral and cheap to stamp | candidate |
