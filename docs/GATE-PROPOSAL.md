# What the gate should guarantee

2026-09-05. Position: **the gate should guarantee attributable, inspectable evidence,
not that a rationale is useful, truthful, atomic, or predictive of task success.**
A deterministic oracle evaluates task success separately. A model judge would collapse
that separation. No proposal below introduces one.

## Audit of the current gate

| Check | What it actually establishes | Limit |
|---|---|---|
| AUSENTE | An independently observed effect lacks a current nonempty why | Presence is not an explanation-quality measure |
| NAO_PARSEAVEL | The current declaration/tool evidence failed local schema validation | Correctable calls must not create permanent debt; historical failures are telemetry |
| DOMINIO_AUSENTE | A domain label is present | It cannot determine whether the label is appropriate |
| SIMBOLO_NAO_RESOLVIDO | A declaration contradicts/misses an available identity witness | Witness false negatives still cause false rejection; a fabricated table cannot certify itself |
| EDICAO_GRANDE_SEM_SIMBOLO | An observed fine identity over the declared size needs an explicit matching declaration | Naming is neither a measure of semantic scope nor proof of an atomic change |

Order today is prerequisite reporting, missing annotation, schema, why, identity/size,
then domain. The early exits avoid explaining absent fields of an invalid object.
Failures and non-evaluable checks remain separate. With gate enabled, failed or
interrupted sessions cannot publish records to the served store.

The owner authorized in-scope improvements after the initial contract. Actionable
correction, coarse-effect exemptions, rejection of mismatched identities, removal of
self-reported effects and guarded publication were implemented and are recorded in
[the delta](DELTA-V1.1-V2.md). They are **not pending proposals disguised as delivered**.

## Proposal I would defend: bind validation evidence to its observed revision

**Status: proposed, not implemented as a gate check.** The approved command/evidence
pair makes a check re-runnable, but does not by itself prove that its result describes
the state being handed off. An agent can change an artifact after the last passing
check. A trusted runner can accidentally reuse old output in a new checkpoint.

Require the validation witness to identify the revision it actually observed. At
handoff, compare that witness with the current revision. On mismatch, the mechanism
must say **validation stale**, not imply that the current state passed. Prefer a
non-blocking unavailable-validation status initially; only an explicitly required
acceptance check should make staleness block publication. This avoids turning optional
validation into an unapproved sixth universal gate code.

| Question | Answer |
|---|---|
| What does it catch that passes today? | A passing check from before a later mutation being served beside the new effect as if current |
| What could it block unfairly? | Unrelated changes invalidate a whole-store/tree hash even if the check reads an unaffected subset; external nondeterminism also complicates replay |
| Survives without a model? | Yes: content/revision identifiers and equality, supplied by the adapter's independent observer |
| Works outside code? | Yes: versioned typed-store snapshots; not irreversible actions without a readable state |
| Boundary / owner decision | Decide whether stale optional evidence is omitted/marked or blocking, and define the check's scope before adding a wire field or code |

The defense is narrow: *a check result is evidence about a specific state*. This
improves epistemic accuracy without claiming to grade prose. It is more useful than
adding a generic “bad intent” code.

## Proposal to reject: unconditional COMPROMISSO_VACUO

**Recommendation: reject as a universal blocking rule; not implemented.** A check
that already held before an action is often exactly the property the agent must
preserve. The approved continuation state “already solved, preserve” makes this
counterexample explicit. A stable invariant is not a vacuous commitment.

| Question | Answer |
|---|---|
| What could it catch that passes today? | An unrelated or trivially true check presented as evidence of a newly achieved transition |
| What could it block unfairly? | Regression prevention, refactoring, safety invariants, maintenance of a valid booking or account balance |
| Survives without a model? | Evaluating before/after can; deciding whether the author promised improvement versus preservation cannot be inferred from prose deterministically |
| Works outside code? | The counterexample and rejection are domain-general |
| Better boundary | A future explicitly declared transition contract may compare before/after; do not infer such a contract or silently expand the frozen schema |

## Smaller candidate: retire mandatory fine-name repetition

**Status: proposed, not implemented.** Once an independent fine anchor exists and an
intent already covers the effect, requiring the agent to repeat its name above a size
threshold adds a declaration, not a new witness. Consider making this a diagnostic
instead of a block; do not recalibrate 51 to disguise the issue.

It catches no new semantic error; its value would be removing avoidable blocking and
measuring whether explicit scoping buys anything. The false-negative risk is letting
one broad why span unrelated changes. However, naming those same identities never
established a common reason either. The proposal remains deterministic and applies to
any adapter with fine identities. Keep the existing block until the owner chooses this
trade-off and records its treatment change before G2.
