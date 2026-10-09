# Bench — frontier strand (shared contract)

**Status:** instrument, not measured collection. Records carry `"draft": true`
like every bench record before G2. Identical copies live in
`MathBorgess/mathai-harness` and `MathBorgess/tau-intent` (`docs/BENCH-FRONTIER.md`);
change both or neither.

## 0. What this strand is

The local strand (V0 / V0.2) runs **small local models** over the **small**
`tidelot` repository, one cell per participant machine, at a Gambiarra event.
This strand runs **three frontier families** over the **same chain of six tasks,
byte for byte**, grown into a **~15x larger repository**, on the owner's machine,
through the owner's own subscriptions:

| Family | Model in round 1 (declared in `frontier.lock.json`) | Reached through | Protocol |
|---|---|---|---|
| anthropic | `claude-haiku-5-5` | `proxies/claude` (Claude Code session) | Anthropic Messages |
| openai | `gpt-6-luna` | `proxies/codex` (Codex CLI ChatGPT session) | Responses (ChatGPT Codex backend) |
| google | `gemini-3.8-flash` | `proxies/antigravity` (Antigravity Google session) | Gemini API, served by Cloud Code Assist |

Round 1 is the light tier of each family (owner decision, 2026-10-08). The lock is
the authority: a later round changes `families.*.model` by pull request and runs
under a new run name, and every run's `freeze.json` carries the lock it ran with.

The contrast the TG reads is **between regimes** (small repository + local model
vs larger repository + frontier model), descriptive. The inferential contrasts stay
**within a cell** (B×A, B×C, paired by task), exactly as in the local strand. Model
class and repository size move together by design; this strand does not separate
them (a "bridge" — frontier models on the small task set — is one line in the lock,
`plan.tasksets: ["harbour", "small"]`, if the owner wants it).

## 1. What is identical across the two strands

| | Local strand | Frontier strand |
|---|---|---|
| Mechanism | tau-intent, arms A/B/C as flags of one binary | same build (`tau_intent_sha` in every record) |
| Agent loop | pinned `tau-ai==0.4.7` `AgentHarness` | same; tau's own provider for each protocol |
| Runner | `tau-intent bench` | same command, `--offline` |
| Tasks | `taskset/` (tidelot, K=6, Q0) | `taskset-harbour/`: same `tasks/`, `qualification/`, `decisions.json`; **`task_hash(k)` equal for every k** (checked by `grow` and by a test) |
| Oracle | hidden tests 1..k, outside the workspace | same tests, same rule |
| Records | `gambiarra-coleta-2` | same schema; the additions of §4 are additive |
| One commit per task per arm, bundles, transcripts, manifests | yes | yes |

## 2. What differs, and where it is declared

| | Local | Frontier | Declared in |
|---|---|---|---|
| Repository | `tidelot` seed, 8 files | `tidelot` + `harbour/` host, 78 files (≈3.1k lines of Python against 210, 189 host tests) | `taskset-harbour/taskset.json` (`derived_from`, `regression`) |
| Wire protocol | OpenAI `/chat/completions` | native per family | record `model.provider_api` |
| Sampling | `temperature=0` + `seed` stamped on the wire | **`provider-default`**: no sampling field sent, and the wire log proves none left (§3) | lock `families.*.sampling`; record `model.sampling`, `model.seed_on_wire` |
| Reasoning depth | n/a | `reasoning_effort` per family (default `high` for all three) | lock; record `model.reasoning_effort` |
| Output cap | tau default | `max_output_tokens`: **no artificial cap** since round 2 -- each model's own maximum (Anthropic 128000, Google 65536; Codex: nothing sent, backend default). Declared as the maximum because tau's Anthropic provider sends 4096 when nothing is declared. Round 1 used 32000 Anthropic/Google | lock; record |
| System prompt | agent prompt | **the same agent prompt and nothing else** (§7.1); a Claude subscription that refuses that gets one identity sentence only if the owner declares it after `probe` measured the refusal | lock `families.anthropic.oauth_identity` (default `false`); record `model.system_prefix` |
| Turn cap / deadline | 8 productive turns, 600 s | **32 productive turns**; deadline 3600 s as a safety ceiling only (round 2, owner decision 2026-10-08). Round 1: 8 / 600 s; design default was 30 / 1800 s | lock `plan` |
| Infrastructure failures | recorded as error, never retried (V0.2) | a unit lost to quota/credentials/provider/proxy is **discarded and re-run from the state before it** (§5) | lock `infra`; record `infra_retries` |
| Host regression | none | frozen host suite run after every unit, descriptive (§6) | record `host_regression` |
| Where it runs | arena + LAN backends | offline, one machine, `mathai_harness.frontier` | `docs/FRONTIER.md` |

## 3. Sampling: why `provider-default`, and how it is checked

AGENTS.md rule 8 (tau-intent) says sampling is stamped on the wire and checked on
the wire. Frontier models **refuse** sampling fields: Claude Opus 5.5 rejects
`temperature`/`top_p`/`top_k` with a 400, and the reasoning models on the ChatGPT
Codex backend (GPT-6 Sol and Luna) do not take `temperature`. Gemini 3.x accepts
them, but Google advises leaving `temperature` at its default (lower values can
loop). The lock therefore declares `provider-default` for every family in every
round, uniformly, and the runner
**checks** it the same way it checks a stamp: `WireLog.report()["conferida_no_fio"]`
is true only if no request body carried any sampling knob of its protocol
(`SAMPLING_KNOBS` in `provider_api.py`). No protocol of the three carries the cell's
seed under this policy: `seed` is a label of the cell (and picks the arm order), not
a property of the call. `stamped` remains available per family (Gemini would get
`generationConfig.temperature` and `generationConfig.seed`); the preflight refuses a
cell whose model rejects what was declared (HTTP 400 before any counted unit).

Consequence for the analysis: frontier trajectories are **not deterministic**
replays; the paired within-cell design and the seeds (replicates) carry the noise.

## 4. Runner additions (`tau-intent bench`)

Flags, all offline-only (the arena's schemas know local runners):

```
--provider-api {openai-completions,anthropic-messages,openai-codex-responses,google-generative-ai}
--sampling {stamped,provider-default}     required for any protocol but openai-completions
--reasoning-effort LEVEL                  Anthropic output_config.effort / Codex reasoning.effort / Gemini thinkingConfig
--max-output-tokens N
--model-family NAME   --strand NAME
--infra-retries N  --infra-wait-s S  --infra-max-wait-s S
```

Record additions (additive; the local strand's records are unchanged):

- `model.provider_api`, `model.sampling`, `model.seed_on_wire`, `model.reasoning_effort`,
  `model.max_output_tokens`, `model.system_prefix`, `model.family`; `model.runner_kind` is `"other"`.
- `error.kind` gains three infrastructure kinds read from the proxy's HTTP status:
  `quota_exhausted` (429), `credentials_unavailable` (401/403), `provider_unavailable`
  (500/502/503/504/529), or, when the provider fails inside a 200 stream, from its error
  text (rate/usage limit, quota, resource exhausted -> `quota_exhausted`; overloaded,
  service unavailable -> `provider_unavailable`). Like `backend_unreachable`, the analysis
  drops them; they are never a failed task.
- `infra_retries[]` (only when a unit was retried): each discarded attempt with its
  kind, detail, **tokens**, turns, times, the tag of its commit and where its
  artifacts went.
- `host_regression` (only when the task set declares one): the oracle block of the
  frozen host suite, `per_test` limited to tests that did not pass.
- `cell.json`: `strand`, `protocol`, `infra_retry_policy`, `host_regression`, and the
  preflight's `status`, `sampling_ok`, `answered_by`.

Tokens: outcome tokens are the provider's own usage per call, as in the local strand.
tau 0.4.7's Google parser drops `usageMetadata`; the runner reads it off the response
bytes (`UsageFromWire`) and records it as `provider_usage` (it is the provider's
figure, read one layer lower), with `thoughtsTokenCount` counted as output.

### 4.1 `--bloco-yaml` (2026-10-09)

`bloco.yaml` (default) is the v1 pushed block. `bloco-consulta.yaml` is the pulled view of
the arm-B grilling: B gets an instruction, an index and the `recall_intent` tool. A cell
that combines it with arm C stops before the first unit (`bad_assign`, decision Q13). The
manifest's `bench.bloco_yaml` and the record's `bloco_versao`/`visao_modo` say which ran.

### 4.2 Heavyweight brownfield task sets (2026-10-09)

Three optional declarations, all inside the hashed task set, for a host that needs a built
environment (the SWE-Milestone scikit-learn chain):

- `environment`: `{"setup": [argv], "bin": "<dir>", "timeout_s": N}`. The setup runs once per
  arm workspace, before the arm's first unit and outside its clock, with `ENV_DIR`
  (`<arm root>/env`, outside the agent's tree), `WORKSPACE`, `TASKSET_ROOT` and
  `BENCH_PYTHON`. `ENV_DIR/bin` goes first on the agent's PATH and is the interpreter of the
  oracle and the regression. A failed setup stops the cell (`environment_failed`). After an
  infrastructure retry the setup runs again, because the reset cleans ignored files.
- `oracle_scope`: `cumulative` (default, tasks 1..k) or `own` (task k's directory only).
- `TAU_INTENT_ORACLE_MODE` (`oracle` | `snapshot`) is set for every test run, so the task set's
  conftest can narrow a run.

`--snapshot-oracle every-edit` runs task k's tests after every turn that called `write`, `edit` or
`bash`, outside the agent's tree. The supervisor takes that time off the deadline
(`fora_do_relogio_s`). Each run is a line of `snapshots.jsonl`; the record gets
`snapshot_oracle.turns_to_green`, the first turn at which the snapshot was green (Q6).

**Build check** (owner decision after the SWE-Milestone pilot, 2026-10-09). Inside
`environment`, `"build_check": "<script>"` (and `build_check_timeout_s`, default 900) names a
script the bench runs with `bash` in the agent's tree, with the arm's interpreter first on
PATH: exit 0 means the package builds. It runs before each session, after each editing turn
(next to the snapshot) and at the end. A session that starts on a broken build gets the
notice `prompts/aviso-de-build-v1.txt` after the task statement, with the check's last 30
output lines; the text is the same in every arm. The record gets `build`: `inicio_ok`,
`fim_ok`, `aviso_enviado`, `quebrou` (started working, ended broken), `recuperou` (started
broken, ended working; `null` when it started working), `turno_quebra`, `turno_recuperacao`,
`turnos_com_build_quebrada`; `build.json` keeps both outputs and each snapshot line its
`build_ok`.

## 5. Infrastructure retries

Subscriptions have windows (five-hour, weekly) and sessions expire; a long run will
meet both. A unit whose provider call ended in one of the four infrastructure kinds
is **discarded and run again from the state before it**: the arm's repository is reset
to the commit before the unit (the discarded commit is kept under the tag
`infra/<arm>-task-<k>/attempt-<n>`, so `bundle --all` carries it), the arm's intent
store is restored byte for byte, the unit's artifacts move to `<unit>.infra-<n>/`, and
the runner waits `min(wait_s * 2^(n-1), max_wait_s)` before the next attempt. After
`retries` attempts the unit is recorded as that infrastructure error. Nothing is
hidden: every discarded attempt, its tokens included, is in the final record.

Known limit: a rescue call of arm C refused for quota mid-unit degrades that unit to
B for that call (`falha_politica: degradar_sem_sumarizar`, recorded in
`mechanism_telemetry.llm_rescue_*`); it is not retried.

## 6. The grown task set

`python -m mathai_harness.taskset grow taskset taskset-hosts/harbour taskset-harbour`
composes `seed` and every `reference/k` as *small tree + host overlay*, copies
`tasks/`, `qualification/`, `decisions.json` byte for byte, freezes the composed seed's
`tests/` as `regression/tests`, and refuses an overlay that touches any file a task
changes or replaces a seed file it did not declare. Sanity adds **R5**: the seed and
every reference pass the host suite (so a red host suite is the agent's doing). The
committed `taskset-harbour/` is checked against a fresh `grow` by a test (no drift).

## 7. Proxies (`mathai_harness.proxies`)

Same design as `graph-engineering-lab/proxy`: the client's own provider owns tool
schemas, ids and streaming; the proxy adds the credential and nothing else (§7.1). It reads the credential the vendor's CLI saved
(on every request, never refreshed or rewritten, with one opt-in in-memory exception
for Antigravity) and forwards. Header forwarding, untranslated upstream errors and a
metadata event log follow `jev-gateway`. The Antigravity proxy serves the public
Gemini API surface (model and method in the path, `?alt=sse`) and wraps/unwraps
Cloud Code Assist's `v1internal` envelope; its hosts, envelope fields, project and
model names are configuration because they are **not verified live**.

| Proxy | Port | Credential (first found) | Missing/expired |
|---|---|---|---|
| claude | 8801 | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`), Keychain `Claude Code-credentials`, `~/.claude/.credentials.json` | 401 `proxy_credentials_unavailable` + fix |
| codex | 8802 | `CODEX_ACCESS_TOKEN`+`CODEX_ACCOUNT_ID`, `~/.codex/auth.json` (`tokens`) | same |
| antigravity | 8803 | `ANTIGRAVITY_ACCESS_TOKEN`, `ANTIGRAVITY_TOKEN_FILE`, keyring service `gemini` account `antigravity` | same |

### 7.1 No vendor harness on the wire

The model under test must see the mechanism's harness (tau-intent's agent prompt, its
tool catalogue, the task) and nothing of Claude Code, Codex or Antigravity. Each
layer, what it puts on the wire, and how that is enforced:

| Layer | Puts on the wire | Never | Enforced by |
|---|---|---|---|
| tau-intent runner | agent prompt (`prompts/agent-system-v1.txt`), tools `read`/`write`/`edit`/`bash` (+ `record_intent` in B/C), the task; preflight and rescue calls carry **no** system prompt and **no** tools | any vendor prompt, beta or tool | `tests/test_frontier_protocols.py::TestNoHarnessOnTheWire` (every request of a whole cell, three protocols) |
| tau's own providers (pinned, not edited) | protocol knobs: Anthropic `cache_control` breakpoints, `max_tokens` (4096 if not declared); Codex `text.verbosity: "low"`, `include: ["reasoning.encrypted_content"]`, `tool_choice: "auto"`, `parallel_tool_calls: true`, and **`instructions: "You are a helpful assistant."` when the system prompt is empty** (preflight and rescue only); Gemini nothing beyond the declared caps | system text of their own on agent calls | same test (the Codex fallback is the only text allowed on a bare call) |
| claude proxy | the subscription bearer; `anthropic-beta: oauth-2025-04-20`; body byte for byte | `claude-code-*` betas, Claude Code's system prompt or tools | `tests/test_proxies.py` (only `authorization` and `anthropic-beta` differ); extra betas only via `CLAUDE_PROXY_EXTRA_BETAS`, declared at `/health` |
| codex proxy | the subscription bearer, `chatgpt-account-id`; `stream: true`, `store: false` (the backend serves nothing else) | Codex's instructions, tools or `originator` | `tests/test_proxies.py` (a tau request crosses unchanged) |
| antigravity proxy | the subscription bearer, `User-Agent: mathai-harness-proxy` (the owner's runs declare the `agy` client instead, see below); envelope `{model, project, request}` with `request` the client's body unchanged | `requestType: "agent"`, `userAgent`, Antigravity's system instruction or tools | `tests/test_proxies.py`; extras only via `ANTIGRAVITY_ENVELOPE_EXTRA` / `ANTIGRAVITY_USER_AGENT`, declared at `/health` |
| whole chain | — | any of the above | `frontier e2e`: the fake vendor upstreams answer 401 to any call whose system text is not the agent's own (or empty), whose tools are not the mechanism's, that carries a `claude-code` beta or an envelope field beyond `{model, project, request}`; negative controls (re-enabling the Claude Code beta or the agent envelope) make the e2e fail |

Every proxy declares at `/health` (`adds`) exactly what it changes; `frontier` records
those declarations in `proxies/proxies.json` and in `export/freeze.json`
(`proxy_declarations`), so the dataset cites what reached the model.

Measured on the owner's subscriptions (§9), two exceptions are declared: the Claude identity sentence below, and the `agy` User-Agent on the Antigravity proxy (a header, not prompt or envelope content).

The one exception that may be needed is measured, not assumed: some Claude
subscription tokens are only served to Claude Code and refuse a call without the
sentence `You are Claude Code, Anthropic's official CLI for Claude.` as the first
system block. `frontier probe` tries the pure call first; only if it is refused does
it try once with the sentence and tell the owner to declare
`families.anthropic.oauth_identity = true`. Declared, the sentence is one block
before the agent's prompt, identical in every arm, stamped as `model.system_prefix`.
Nothing else of Claude Code comes with it (no beta, no prompt, no tools).

## 8. Orchestration (`python -m mathai_harness.frontier`)

`frontier.lock.json` declares task sets (with frozen `task_set_sha`), the plan
(seeds, arm orders, `k_max`, deadline, turn cap), the infrastructure policy, the
families and the proxy ports. A cell is one (family, task set, seed); seed *i* runs the
arms in `arm_orders[i mod 3]`, so with three seeds every arm is first, second and third
once per family. Families run side by side; cells of a family run one after the other
(one subscription's quota). A finished cell is never re-run; an interrupted one is
parked in `.aborted/` and restarted. `probe` makes one real round trip per family
(preflight + Q0, which needs tool calls) before anything counted. `export` writes
records, cells, a summary, the bundles and `freeze.json` (lock, hashes, runner build,
proxy log digests).

## 9. Not verified, and open for the owner

- **Measured on the owner's subscriptions (2026-10-08).** The Claude subscription refuses the pure call (HTTP 429) and serves the model with the identity sentence: `families.anthropic.oauth_identity = true` (owner decision F-8). The Antigravity backend (`cloudcode-pa`) finds the owner's project only for a client that identifies as `agy` (`ANTIGRAVITY_USER_AGENT=antigravity/1.2.10 darwin/arm64`, owner decision G2; envelope still `{model, project, request}`), and serves Gemini 3.8 Flash as `gemini-3.8-flash-tiered` (`proxies.antigravity.model_map`). Both are declared at `/health` and recorded in `freeze.json`.
- Sampling `provider-default` for all three families (§3), effort `high` for all three,
  output caps (none beyond each model's maximum since round 2), turn cap 32 and deadline 3600 s: declared, owner decisions.
- Terms of service of each subscription for automated use: the owner's call.
