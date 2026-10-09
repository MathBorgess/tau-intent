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

## Exact region names (owner decision after the SWE-Milestone pilot, 2026-10-09)

The pilot's gate asked for names the agent could not give. A hunk was named by the
innermost def around *all* its lines, so three things went wrong: a decorator sits
before its `def` in the AST (an edit of `@validate_params(...)` was named by the
module); the three context lines of the diff crossed into the previous def (a
signature change was named by the class); and the name was bare (`fit`, never
`QuadraticDiscriminantAnalysis.fit`). In one unit that made 11 block turns and an
`ESCALAR`.

The resolver (`stdlib-identities-v2`) now names each **changed line**:

- by the innermost def or class around it, with the decorators inside the def, by its
  dotted name (`Pipeline.predict`); module-level lines name the file;
- an added line in the post-edit tree, a removed line in the pre-edit tree (`git show
  base:path`), so a deleted method keeps its own name;
- context lines name nothing; blank changed lines join the nearest non-blank change; a
  line removed and added back unchanged is not a change.

A hunk is split where the name changes: one region per def. A declared symbol covers a
region when it is the region's dotted name or its last parts (`fit` covers
`LDA.fit`, never `LDA.partial_fit`). Two regions of different defs never stand in for
each other at the gate. The code graph keeps bare node names; the projection and
`recall_intent` map a dotted name to its graph node. Tests: `tests/test_v3_nome_exato.py`.

**The agent acts on the list** (owner decision after pilot run 09c). Exact names were not
enough: the agent read `AUSENTE: ...::Pipeline.predict` as a code problem and kept editing,
33 block turns in one run. Three changes:

- the block message (`prompts/portao-bloqueio-v1.txt`, hashed) is in the session's
  language and each line says what clears it: `record_intent` with this file and this
  symbol, or with the file alone for module-level lines and for files without names; the
  header says that editing the code again clears nothing;
- a declared symbol also covers the defs inside its def: `f` covers `f.wrapper`, and
  `Pipeline` covers `Pipeline.predict`;
- a declared symbol scopes a call file by file. A file with no observable names (Cython,
  opaque, unparseable) is claimed whole by an intent that lists it; before, it was dropped
  whenever another listed file had names. Tests: `tests/test_v3_agir_sobre_a_lista.py`.

## Arm B v2 (owner decisions of the arm-B grilling, 2026-10-09)

Decided by the owner in the vault note `wiki/projects/harness-tau/2026-10-09-decisoes-grilling-braco-b`.
Each change is a declared config member (hashed) or a tool description.

1. **Graceful stop (Q2/Q11).** Two productive turns before the cap, and at 90% of the deadline,
   the supervisor steers a budget notice into the session (`supervisor.yaml`,
   `prompts/aviso-de-fim-v1.txt`). Every arm gets it; with capture on it adds one sentence:
   record your intents in one call. The notice spends no turn: it rides on the next one.
2. **Publication at the end (Q2/Q11).** `TETO`, `ESCALAR` and `DEADLINE` run the gate once
   more, on the final state, without a model turn, and publish the entries whose regions pass.
   `PASSA` still publishes everything; `ERRO` publishes nothing. Telemetry: `publicacao`
   (`total` | `parcial` | `nenhuma`), `intencoes_publicadas`, `portao_no_encerramento`.
3. **Registration in one call (Q3/Q14).** `record_intent` takes `intents: [...]`; the single
   form still works. The description asks, in English, for what the code and the git log
   cannot say: the reason, the property to keep, the rejected alternative.
4. **The pulled view (Q5/Q12).** With `bloco-consulta.yaml` the first message carries an
   instruction and an index of the files that have recorded intent, and nothing else of the
   history. `recall_intent(paths, symbols)` returns the v1 projection anchored where the agent
   asked: deterministic, 1 hop, deduplicated, at most `token_budget` tokens per call, with the
   receipt. Every call is telemetry (`consultas`: turn, arguments, entries, tokens, and how
   many of them the unit then changed). `bloco.yaml` keeps the v1 push, byte for byte.
   `llm_rescue` is not defined with the pulled view (Q13) and is refused.
5. **Turn classes (Q15).** Every model turn has `classe`: `trabalho` (marked `misto` when it
   also called a mechanism tool), `registro`, `consulta`, `resposta_a_bloqueio`,
   `encerramento`, `final`. A turn that answers a block is the block's, whatever it called
   (the pre-registration's anti-double-count rule). `turnos_do_mecanismo` = registro +
   consulta + resposta_a_bloqueio.
6. **What counts toward the cap (Q4).** `supervisor.teto_conta_resposta_a_bloqueio` declares
   it. `true` counts every turn with a tool call in every arm; `false` gives the answers to a
   block their own budget (rule 5 of `AGENTS.md`) under a hard ceiling of three caps.
