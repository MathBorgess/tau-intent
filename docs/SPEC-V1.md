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

## Collector

- Regions always from git diff.
- write/edit argument name is path.
- edit takes edits: [{oldText, newText}].
- bash can write files; those regions still need intent.
- Unparseable = _raw_arguments present or local schema validation refused (V6).

## Gate (pure)

Four codes: AUSENTE, GENERICA (regex on why), PROPERTY_SEM_SIMBOLO (AST lookup), EDICAO_GRANDE_SEM_PROPERTY. After n_max blocks → ESCALAR. No LLM.

## Store

Append-only JSONL. No status field. Current vs superseded is derived from supersedes. V3: 40/40 synthetic pairs.

## Flags

A: --no-capture --no-gate --no-project --no-serve
B: --capture --gate --no-project --serve
C: --capture --gate --project --serve

serve must exist in v1 even if arm D is not run. Arm A abort if intents.jsonl gains a line. Tool catalog: B/C include record_intent; A does not. Declare that in the manifest.

## Sampling

Owner sets temperature=0 on the provider they expose. Manifest records the configured value and amostragem_conferida_no_fio. If the built-in tau provider is used, a ~40-line HTTP transport stamps the body; tests inspect the body, not the config object. Do not write seed unless the wire carries it.

## Projection in v1

Dumb: k=1, prune hubs on, llm_rescue off, gamma=0.1 and max_nodes read from YAML (not fitted). V4: monotonic token cut on a growing synthetic history. Not V5.

## Token accounting

Count locally with a declared tokenizer. No cache discount. Never CHARS_PER_TOKEN = 4.

## Out of v1

SWE-Milestone adapter, V5 labels, hyperparameter calibration, analysis/permutation trigger (that lives in mathai-harness), live model CI.
