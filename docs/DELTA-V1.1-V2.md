# What changed from v1.1 to v2

2026-09-05 · baseline `cb1fdee99e7dd68229c47a54135bc61d66b39c7f`.
This is a capability and measurement delta, not a commit changelog.
No benchmark or paid model session was run. All execution evidence is synthetic.

## Reproduced before changing the mechanism

| Fixture | Executed v1.1 result | V2 result / how to verify |
|---|---|---|
| One file, six regions, twenty edited units each; every region annotated | Python PASSA; Go BLOQUEIA with EDICAO_GRANDE_SEM_SIMBOLO, ESCALAR at three prior blocks | Both PASSA; Go reports unavailable checks. `tests/test_v2_p1.py` |
| Two regions, one recorded; same evidence at different granularities | Python coverage 0.5; Go coverage 1.0; supervisor copied that scalar into effective coverage | Fine coverage 0.5 for resolved identities, None without a resolver; separate target coverage. `tests/test_v2_p2.py`, `test_v2_p5.py` |
| Table omits a true identity, or includes an extra invented identity | Omission fired two codes; extra identity fired none | An incomplete witness can still cause a false rejection; unused false-positive identities remain undetectable by the pure gate. Conflicting declared/effect identities are now rejected. `test_v2_p1.py`, `test_v2_gate_actions.py` |

The third result is an **instrument accuracy limitation**, not something a pure gate
can repair by believing the declaration. No language resolver was added.

## Capabilities and claims

| Before | Now | How to verify |
|---|---|---|
| Core execution knew diff/parser details | Static `Adapter` contract for effect, anchor, neighbourhood and oracle; code routines moved, not rewritten | `test_v2_equivalence.py`; moved-source hashes in `tests/fixtures/moved_source_hashes.json` |
| No non-code effect substrate | Closed typed store, independently re-read delta, namespace/key anchors, value hashes, contains/depends_on graph and deterministic assertions | `test_v2_state.py` |
| Missing resolver became the agent's unsatisfiable failure | Unavailable checks travel separately from failures; they do not spend blocking budget | `test_v2_p1.py`, `test_v2_p5.py` |
| “Coverage” silently changed its unit | Fine and coarse populations have separate numerators and denominators; `fracao_resolvida` accompanies effective coverage | `test_v2_p2.py`; supervisor manifest fixture |
| Empty origin could claim perfect recall; no consumption could claim zero reuse | Undefined ratios return None; recall reports origin count as `ancoras_no_bloco` | `test_v2_p3.py`, `test_telemetry.py` |
| Rescue recognized only a particular extension | Anchor formats come from the static adapter registry | `test_v2_p3.py`; state anchor format in registry |
| Receipt of zeros could conceal unavailable neighbourhood | Boolean availability and a dedicated rendered notice; notice is budgeted | `test_v2_p4.py` |
| Declarative rationale was the entire continuation record | Optional trusted checkpoint: changed targets, other artifacts, validation command/result, explicit continuation-state stamp | `test_v2_checkpoint.py` |
| Retrieval tied to supervisor call shape | `IntentRetrieval.retrieve_learnings(query, top_k) -> list[str]`, read-only, re-reading current records at each handoff | `test_v2_serve.py` |
| Producer and consumer could be conflated | Separate model stamps on every execution; report builder and validator reject mixed pairs and missing pair IDs | `test_v2_handoff.py` |
| Instrument reach absent from run provenance | Adapter version/source hashes, per-adapter/per-language coverage, excluded targets, unavailable checks, effective edge types and served IDs/status | `test_v2_p5.py`, `test_v2_handoff.py` |

**P1 is a mechanism change.** It changes verdict and blocking-turn distributions.
It requires a dated pre-G2 experimental amendment. Calling it merely a repair would
hide a treatment change. The preregistration was not edited.

## Further corrections authorized during reconstruction

The owner subsequently authorized in-scope improvements, particularly to the gate.
These are additional behavioral changes; none calibrates a parameter or adds a gate code.

| Executed counterexample / old behavior | Change and reason | How to verify |
|---|---|---|
| Rejected call followed by valid correction still blocked | Current annotation can be repaired; historical errors remain in manifest | `test_v2_gate_actions.py` |
| Valid command without a redirection was NAO_PARSEAVEL | Absence of a tool-specific path is not a schema error; effect enumeration is the witness | `test_v2_gate_actions.py` |
| Non-object arguments crashed collection; non-text rationale became a string and passed | Validate object and declared-field types; do not crash or stringify invalid declarations | `test_v2_gate_actions.py` |
| Sibling state keys could inherit range-overlap lookup from code | Match state effects by adapter-defined overlap; an unannotated sibling is AUSENTE | `test_v2_state.py` |
| Nested numeric object keys were accepted but hashed like string keys, hiding a state mutation | Recursively require JSON values and string object keys before mutation; rejected writes leave the snapshot intact | `test_v2_state.py` |
| Declaration alone manufactured a region and stored intent | Capture only independently observed effects | `test_v2_gate_actions.py` |
| Valid resolver, large top-level change, no observable fine identity still blocked | Size check unavailable for an observed coarse effect; missing why/domain still block | `test_v2_gate_actions.py` |
| Another valid name could certify the wrong effect | A declaration cannot contradict the independently resolved effect identity | `test_v2_gate_actions.py` |
| Partial replacement inherited fields from an older declaration | A valid replacement supplies its own declared half; omitted fields are not borrowed | `collect.py`; gate correction tests |
| Stored anchor could fall back to a name declared without a witness | Code capture persists the observed identity only, or a coarse anchor | `adapters/code.py`; normal golden unchanged |
| Live regions were read only before the session | Re-observe at final boundaries and termination; state mutation fixture now drives real capture | `test_v2_state.py` |
| Requested productive cap 1 admitted 3 productive turns and PASSA | Stop at cap with TETO; no gate call at a productive boundary; manifest declares cap hit | `test_v2_boundary.py` |
| Failed gate still published annotated but invalid records | With gate enabled, only PASSA publishes; withheld pending count is recorded | `test_v2_gate_actions.py` |
| First effect was effectively required to orient a new task | Use literal known IDs in the statement when no initial effect exists | `test_v2_task_orientation.py` |
| Rescue could lose evidence or exceed the projection budget | Deterministic post-selection guards; declared fallback, accounting for rejected output too | `test_v2_rescue_guards.py` |

These changes affect capture, serving, cost and verdict distributions and must be
included in the version freeze, not retrospectively mixed with v1.1 trajectories.

## Compatibility that was preserved — and deliberately not faked

- **Original suite:** 203 tests were run unchanged before edits and passed. The
  owner authorized changing only expectations incompatible with v2, then authorized
  the further mechanism improvements above. In `test_telemetry.py`, scalar assertions
  now inspect the structured field and empty-population assertions expect None.
  `test_render.py` expects the new receipt availability field. No old test was deleted,
  skipped to conceal a failure, or made to accept both behaviors.
- The normal code golden preserves verdict, served block and JSONL modulo id/ts.
  Optional checkpoints are omitted for old callers, so legacy records remain identical.
  This is a fixture equivalence proof, not a claim that v2 preserves every v1.1 verdict.
- Diff parsing, resolver, blob hashing and graph routines have source-equivalence
  checks against their pre-move contents. New adapter methods and shared-core fixes
  are outside that pure move and are documented above.
- All five `config_sha256` members remain byte-identical to the baseline fixture.
  Threshold 51, unit declared by adapter, YAML values, prompt, envelope version,
  productive/blocking budget separation, flag meanings and append-only history remain.
- Legacy gate identifiers and `file/files/symbol` tool arguments remain wire aliases.
  State uses encoded `state://namespace::key` IDs; it adds no code-named capture fields.
- `dependencies = []`; CI still declares `NO_NETWORK: "1"`; no tau fork or language
  resolver. The pin check is **skipped**, not passed: tau-ai is absent in this environment.

## Operational entry points and honest limits

Run the synthetic suite from this checkout:

```sh
PYTHONPATH=src NO_NETWORK=1 python3 -m unittest discover -s tests -v
```

- Code: `supervisor.run_task(..., adapter="code", harness=...)`.
- State: `TypedStore` + `StateAdapter`; supply one task-lifetime baseline per adapter.
  The executable integration example is `test_v2_state.py`.
- Validation: `CodeAdapter.validate(argv, workspace)` records exit/stdout/stderr;
  `StateAdapter(checks=...).validate(name)` executes a named local assertion. Freeze
  that check registry and task snapshot with the future experiment.
- Capture: pass `checkpoint_source` from the trusted runner. Missing evidence/state
  stays None. Old callers may omit checkpoints; they do not gain validation evidence
  retroactively. Agent arguments cannot populate the checkpoint.
- Handoff: explicitly pass producer/consumer IDs. Fake harness defaults identify
  the synthetic provider; configuration-only `manifest()` reports missing IDs as
  None and cannot enter a report. IDs remain caller-supplied provenance, not provider
  attestation. `RunResult.manifest` is JSON-ready; CLI `--manifest PATH` can save it.
- Retrieval: query literal known IDs, or supply a deterministic mapper. `top_k` counts
  evidence blocks, each a neighbourhood projection, not individual JSONL rows.
- `grafo_heterogeneo` means multiple effective edge types; language coverage is a
  separate distribution. Fine coverage still cannot measure the witness's own recall.
- Code retains v1.1's tracked-text diff boundary. Untracked/binary effects and command
  failures need a stronger code effect contract before claiming exhaustive filesystem
  coverage. No benchmark connector, dependency DAG runner, provider verification or
  external oracle was exercised. Typed-store changes reverted before the second read
  are net-zero effects, not an operation history.

General adapter support is delivered; a result about **every** long task is not.
See [the gate proposals](GATE-PROPOSAL.md) for changes intentionally not implemented.
