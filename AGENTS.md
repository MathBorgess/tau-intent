# tau-intent — rules for implementing agents

Read `docs/SPEC-V1.md` before touching code. Stop there. The vault is not required for v1.

## Hard rules

1. **No fork.** Import `tau_agent`. Do not copy-paste the tau loop. Do not depend on `tau_coding`.
2. **One binary, four mechanism flags:** `capture`, `gate`, `project`, `serve`. `--llm-rescue` is arm C's knob only — not a fifth stage. No `if arm == "A"` outside flag reading.
3. **Gate is a pure function.** No model call, no network, no tau import inside `gate.py`.
4. **Last TurnEndEvent only** (`tool_results == []`). Not every turn.
5. **Turn cap is productive turns.** Blocking turns are a separate budget. Identical raw `max_turns` is a bug (biased against B/C).
6. **Anchors come from git diff.** Tool events attach why/property/symbol/domain. The write/edit argument is `path`, not `file_path`. `bash` also writes files. `record_intent` may span files via `files: [...]` and several AST symbols in the same file. Declared `symbol` scopes the call; omit it to cover every hunk. Flush writes `Region.symbol`.
7. **Arm A must not write intents.jsonl.** Abort if it does.
8. **Temperature 0 is set by the owner on the provider they expose.** If you use tau's built-in provider, stamp the HTTP body and test the body. Do not trust a config object. Do not invent `seed` unless the wire carries it.
   Frontier strand (`docs/BENCH-FRONTIER.md` §3): `--sampling provider-default` is a declared policy, checked on the wire like a stamp (no sampling knob may leave). Do not stamp a field a model refuses, and do not drop the check.
9. **Copy read/write/edit/bash with origin SHA in the docstring (MIT).** Their descriptions are experimental fixtures.
10. **Tests of v1: no API key, no live HTTP to a model.** Fake provider or recorded fixtures.
11. **Do not cite EXPERIMENTO.md or SPEC.md.** Those files must not exist here.
12. **Do not calibrate hyperparameters in v1.** YAML is read, not fitted. `limiar_edicao: 51` is declared: AtomicCommitBench mean hunks/episode, applied as edited lines summed per (file, symbol). Not a hunk cap.
13. **H16 arms:** A = all off. B = capture+gate+project+serve, llm_rescue off. C = B + llm_rescue on. Both B and C project. `render_tudo` is not on a measured arm.
14. **The loop reads hashed YAML.** `run_task` calls `load_gate_config()`. Do not decide with a bare `GateConfig()`.

## Gate codes (structural)

AUSENTE, NAO_PARSEAVEL, SIMBOLO_NAO_RESOLVIDO, EDICAO_GRANDE_SEM_SIMBOLO (sum of edited lines per identity), DOMINIO_AUSENTE. No ANCORA_AMBIGUA. No GENERICA. No regex on why. A label such as fix/refactor lives in the why (authorship), not as a gate code.

## Slices already on main (do not reopen)

| PR | Closed |
|---|---|
| 1–5 on main | pin, store V3, tools/collect/gate v1, supervisor, graph+projector V4 |

v1.1 (this branch / PR #6) owns the structural gate, `files: []`, H16, block contract, rescue hook, and the bench guard `conferir_v4_v5`. V5 labels stay in mathai-harness.

## Merge bar

A PR that needs a model key, edits tau, runs the gate on every turn, uses an identical raw turn cap across arms, or describes B as `--no-project` does not merge.

<!-- mathai-repo-operations:start -->
## Resource cleanup and review

Existing repository-specific retention, immutable-evidence and review/check requirements remain in force. This section does not override longer retention or stricter preservation rules.

Before cleanup, inspect `git status --short`, `git worktree list`, tracked files, ignored/untracked files and active processes. Read this repository's build configuration and `.gitignore` to identify reproducible outputs. Produce a bounded dry-run list with paths, ownership, active-use checks and a recovery plan; remove only confirmed inactive regenerable residue. A directory being ignored does not make it disposable. Never use broad `git clean`, forced worktree removal or recursive deletion across projects.

Stop only temporary processes created by the current task after they are no longer needed. Keep ordinary operational logs for five days, except evidence needed for an open issue. Preserve sources, credentials, local/ignored work and all experiment/evaluation records awaiting human assessment. Age alone does not authorize deletion of projects or conversations. Use the owning application's archive/recovery mechanism for managed worktrees. Report measured cleanup results and unresolved items in short bullets.

### Code Review Rules

Focus on correctness, data loss, security, permission expansion, costs and broken external contracts. State the concrete trigger and consequence of a finding. Put formatting and deterministic checks in CI. Missing required evidence is unverified, not success. Preserve repository-specific human approval and merge rules; this section grants no new merge authority. Report useful architectural decisions separately from blocking risks, in plain language.

<!-- mathai-repo-operations:end -->
