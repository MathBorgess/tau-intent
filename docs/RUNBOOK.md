# Runbook — how to execute each substrate

Companion to `docs/TASK-CATALOG.md`, which says *what* can be tested and what to expect. This says *how*. Nothing here overrides `AGENTS.md` or the pre-registration in the vault.

## 0. Before any run

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v   # must be green
python3 -m tau_intent.pin --check                         # pin intact, no local edit of tau
```

Exit 0 means the mechanism **behaves as specified**, not that it changes a downstream outcome. That second question is the experiment.

**Three rules that apply to every substrate below:**

1. **One session per task. No compaction.** The supervisor counts productive turns; gate blocks consume a separate budget, reported per arm.
2. **Never intervene in a running trajectory.** Stuck on infrastructure → discard the whole trajectory and re-run. Stuck because the agent failed → **that is data**.
3. **The trajectory follows the first measurement replica, always.** Picking the best contaminates.

**Arms are flags of one binary.** Never `if arm == "A"` anywhere but flag parsing.

```
A: capture=off gate=off project=off serve=off
B: capture=on  gate=on  project=on  serve=on   llm_rescue=off
C: capture=on  gate=on  project=on  serve=on   llm_rescue=on
```

Arm A aborts if `intents.jsonl` gains a line. The tool catalog differs: B/C expose `record_intent`, A does not — declare it in the manifest.

## 1. Sanity ladder — run in this order, never skip

Each step is cheap and each one has killed a bad run somewhere.

| Step | Command shape | Passes when |
|---|---|---|
| **S1 — bench** | the two commands above | green |
| **S2 — smoke, one task, arm B** | fake provider, no API key | block is non-empty, receipt printed, `intents.jsonl` has lines |
| **S3 — arm isolation** | same task, arm A | `intents.jsonl` **unchanged**; run aborts if not |
| **S4 — B vs C shape** | same task, both arms | block *shape* identical; only the body may differ |
| **S5 — one real session, one task** | live provider, temperature 0 | measures `c`, the unit cost. **Do this before any budget arithmetic** — it collapses three unknowns into one measurement |

**S5 is the single most valuable cheap thing in this document.** No dollar figure in any plan is real until it runs.

## 2. Code — greenfield (Commit0). Runs today, no adapter work

Python-only, so the mechanism reads it as-is. This is the ceiling arm and the place to fail cheaply.

1. Pick a library from Commit0, preferring the **least popular** ones — contamination.
2. Rename API, modules and domain vocabulary **before** generating task statements.
3. Slice into 10–12 dependent tasks by the CodeFlowBench method: AST dependency tree, paired test per subproblem.
4. Review the slices by hand; write the statements from the existing specification.
5. Run the original implementation as the **reference** — it already exists, do not rewrite it.
6. Freeze in a tag. **No edits after.**

Order of execution: fixed task order, one session per task, one commit per task. At each measurement point, fork the snapshot and run `r` replicas with distinct seeds.

Record per task: diff, intent log, telemetry, transcript, suite result, static checkpoint metrics.

**Stop rule:** if condition A's erosion slope per checkpoint is ≤ 0, stop. The substrate is not measuring the phenomenon — increase horizon or coupling and repeat the pilot.

## 3. Code — brownfield (SWE-Milestone). The primary arm

**Reachable today: scikit-learn only — 12 of 98 tasks.** The other six repositories need an identity resolver for their language, or they run under `nao_avaliaveis` with the fine gate codes suppressed and declared.

1. Read the SWE-Milestone agent adapter and specify the plug-in point. The agent layer is declared decoupled from the evaluation engine, and the agent is chosen in `trial_config.yaml`; it also accepts a custom task set, so the **same orchestrator** runs both code substrates.
2. Verify the execution budget config, and measure whether gate blocking consumes enough budget to produce a false failure. This is a real threat, not a hypothetical.
3. Choose the repository batch. **Order by tasks unlocked, not by ease:** Go (+32) → Rust (+24) → TypeScript (+18) → Java (+12).
4. Instrument effective coverage per task — it is the covariate the whole design rests on, and today it inflates where there is no resolver.
5. Instrument training-contamination measurement: structural similarity between condition A's output and the original commit. **Contamination discards nothing** — it is measured, published per project, and reported as a covariate. The bias is conservative for the hypothesis.

**Budget warning:** the paper reports ≈US$500 for one full evaluation with a frontier model. Do not start without S5.

**Per-language honesty:** the manifest must carry coverage and `codigos_nao_avaliaveis` per language. A repository that is polyglot produces a *distribution*, not a label — and inside one measurement point the gate will be strict on files with a resolver and lenient on files without. That asymmetry is reported, never hidden.

## 4. Outside code — STATE-Bench. Needs the `state` adapter

The cheapest non-code arm, and the interface is already specified by the benchmark.

1. Implement the `state` adapter: effect = delta between two reads of the task-local sandbox database; anchor = `(namespace, key)` plus value hash; neighbourhood = schema `contains` plus declared `depends_on`; oracle = the benchmark's deterministic assertions.
2. Wire `serve` into the retrieval hook:

   ```python
   def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]
   ```

   Return exactly `list[str]`; the benchmark enforces `top_k` and validates the type. Retrieval is **read-only** — domain tools stay benchmark-controlled.
3. Extract intent from the **100 train trajectories per domain**. Never from the 50 held-out test tasks: test definitions and environments *must not* be used as oracle inputs for learning extraction. Violating this invalidates the run.
4. Use the deterministic assertions as the outcome. **Refuse the LLM-judged UX score** as an outcome; record it as descriptive only, and say so in writing.
5. `pass@1` is already averaged over five runs per task — that is an `r = 5` you do not pay for separately.

**What this arm measures, stated precisely:** whether intent captured on earlier tasks improves performance on *held-out* tasks. That is **reuse of experience across tasks**, not continuation of a dependent sequence. It is a different claim from the code arm and is reported separately — never pooled with it.

## 5. Model handoff

New in v2, and it is a configuration, not an arm.

1. Produce the record under model **M1**, serve it to model **M2**.
2. Manifest stamps `modelo_produtor` and `modelo_consumidor` separately, always, even when equal.
3. **Never pool outcomes across producer/consumer pairs.** Report per pair.
4. The reference expectation comes from `Handoff Debt`: the effect is consistent on cost and small and model-dependent on outcome, and one cell was negative.
5. τ²-bench is the cleanest place to isolate this, because its tasks are independent — the handoff is the only thing varying.

## 6. Sampling and freezing

- The owner sets `temperature = 0` on the provider they expose. The manifest records the configured value **and** whether sampling was verified on the wire. If the built-in provider is used, stamp the HTTP body and test the body — never trust a config object. Do not write `seed` unless the wire carries it.
- Count tokens locally with a declared tokenizer. No cache discount. Never `CHARS_PER_TOKEN = 4`.
- **After the G2 freeze the mechanism does not change.** Any change invalidates **all** trajectories, not some. Stop, retag, restart. A freeze without a hash is not a freeze.

## 7. What to record, every run

Non-negotiable, because none of it is reconstructible afterwards:

- diff or state delta · intent log · full telemetry · transcript · suite/assertion result · static checkpoint metrics
- manifest: mechanism flags, `config_sha256`, mechanism tag, model ids, `modelo_produtor` / `modelo_consumidor`, adapter versions and hashes, per-language and per-adapter coverage, `codigos_nao_avaliaveis`, `edge_types_efetivos`
- **which entries were served and the status of each.** If this field does not exist before the freeze, the revoked-intent-served outcome dies permanently — the data is not reconstructible later.

## 8. Analysis order — frozen, do not reorder

Fit the outcome model per point and condition first. Decide the interpretability branch **before** looking at the effect of interest. Run the regression census unconditionally. Then the primary contrast, then intention-to-treat, then the co-primary, then cost. Everything outside the declared family is labelled exploratory in every mention.

No new test after seeing the aggregate. No peeking. The analysis script is frozen before it touches real data, and is validated first against synthetic data with a planted effect — it must recover the planted effect and must not find one where there is none.
