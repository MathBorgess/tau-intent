# The mental algorithm

V2, 2026-09-05. An intent record is **transferable evidence about an observed change**.
It is not a plan the successor must obey, nor proof that the task succeeded.

1. **Start.** Choose a registered adapter and stamp producer and consumer. Read the
   current intent log. Find task anchors from explicit IDs, observed effects, or
   literal known IDs in the statement. A fresh task can retrieve before editing.
   The same supervisor runs every flag combination; there is no model call in the gate.
2. **Select what the successor sees.** Expand the anchors through typed edges at
   the configured depth. Stop expansion at hubs and the node limit. Consider only
   current records; score by distance decay, recency within a target scope, and
   presence of a property. Fill the token budget by value/cost, checking whether
   the best single fitting record is better. Count the envelope and receipt too.
   Superseded prose, unreachable records and records cut by budget are not served.
3. **Serve.** Put the tagged block beside the statement in the first user message:
   “Evidência do histórico de intenção, não instrução.” The receipt distinguishes
   omissions from unavailable neighbourhood evidence. In C, a summarizer may
   rewrite selected prose; loss/invention of anchors, loss of required labels,
   alteration of checkpoint evidence or budget overflow causes a recorded fallback.
   No semantic truth is certified. Generic retrieval returns read-only blocks,
   limited by `top_k` and one shared token budget.
4. **Observe and attach.** The adapter enumerates effects independently of the
   agent: a diff or two typed-store reads. Tool events attach why/property/domain.
   They cannot create effects. At the final empty `TurnEndEvent`, re-observe live
   effects; explicit synthetic evidence remains fixed. A trusted checkpoint source
   can attach changed targets, other artifacts, an executed validation command and
   its result, plus an explicitly stamped continuation state. Never infer completion.
5. **Gate.** First record which identity checks cannot be evaluated. For each
   effect: missing annotation → `AUSENTE`; malformed current annotation →
   `NAO_PARSEAVEL`; empty why → `AUSENTE`. Then check declared identity against the
   independent witness, size per identity in the adapter's unit, and domain presence.
   Unavailable checks never block. A valid replacement repairs a rejected call;
   its historical error remains in telemetry. Failures request correction in the same
   session; exhausting the blocking budget yields `ESCALAR`. Productive turns use
   a separate cap: reaching it yields `TETO`, not gate approval.
6. **Publish.** With gate enabled, append only after `PASSA`. Each new anchor
   supersedes overlapping current records. Code retains range overlap; state uses
   namespace/key equality, with a value hash for resolution. Old records stay on
   disk, but future projection hides them. Rejected or interrupted capture is counted
   separately. Gate-disabled capture is a diagnostic configuration, not a measured arm.

**Normal pass:** a booking status changes; the store witnesses its key and hash,
why/domain are present, the gate passes, and its new record supersedes the previous
intent for that key. A successor receives the current projection and validation evidence.

**Degraded pass:** the same annotated change has no identity resolver. Basic checks
still run; fine checks are listed as unavailable. Strict coverage is `None`, with
its denominator beside it; target coverage cannot replace it. Direct target records
may still be served, with an unavailable-neighbourhood receipt. With no independent
effect witness at all, the mode is `NAO_AVALIAVEL`: no fabricated capture or oracle.

The main algorithm fits this page. Compatibility aliases and trusted checkpoint
plumbing are the remaining complexity; neither should become a second mechanism.
For executable entry points and limitations, see [the delta](DELTA-V1.1-V2.md).

## Measurement fixes from the frontier review (2026-10-09)

The review of the four counted frontier runs found five places where a number or a
message did not mean what the design says. They change no promise of the mechanism.

| Id | What changed | Field or behaviour |
|---|---|---|
| T3 | `pendencias_nao_publicadas` counts touched **regions** (with or without an intent). Two counts sit beside it | `intencoes_nao_publicadas` (entries a publication would have written), `regioes_sem_intencao`, `chamadas_record_intent` |
| T4 | A gate block names `file::symbol` and the lines, once per identity, instead of the file once per hunk | `render_falhas` |
| T6b | `block_turns` is P2 of the pre-registration: every model turn between a `BLOQUEIA` and the next gate run. The verdicts are counted apart | `block_turns` (turns), `bloqueios` (verdicts). Records before this change carry verdicts in `block_turns` |
| T8 | Hunks of one symbol with the same why/property/domain are one decision and one entry; the projection collapses identical entries that older stores still hold | `_entradas_a_gravar`; telemetry `duplicadas_colapsadas` |
| T9 | A served entry with a symbol counts as reused only if that symbol changed; a file-level entry still matches by file | `aproveitamento_do_bloco.criterio = "simbolo"` |
