# tau-intent — rules for implementing agents

Read `docs/SPEC-V1.md` before touching code. Stop there. The vault is not required for v1.

## Hard rules

1. **No fork.** Import `tau_agent`. Do not copy-paste the tau loop. Do not depend on `tau_coding`.
2. **One binary, four flags:** `capture`, `gate`, `project`, `serve`. No `if arm == "A"` outside flag reading.
3. **Gate is a pure function.** No model call, no network, no tau import inside `gate.py`.
4. **Last TurnEndEvent only** (`tool_results == []`). Not every turn.
5. **Turn cap is productive turns.** Blocking turns are a separate budget. Identical raw `max_turns` is a bug (biased against B/C).
6. **Anchors come from git diff.** Tool events attach why/property. The write/edit argument is `path`, not `file_path`. `bash` also writes files.
7. **Arm A must not write intents.jsonl.** Abort if it does.
8. **Temperature 0 is set by the owner on the provider they expose.** If you use tau's built-in provider, stamp the HTTP body and test the body. Do not trust a config object. Do not invent `seed` unless the wire carries it.
9. **Copy read/write/edit/bash with origin SHA in the docstring (MIT).** Their descriptions are experimental fixtures.
10. **Tests of v1: no API key, no live HTTP to a model.** Fake provider or recorded fixtures.
11. **Do not cite EXPERIMENTO.md or SPEC.md.** Those files must not exist here.
12. **Do not calibrate projection hyperparameters in v1.** Ship the dumb 1-hop projector that passes synthetic V4. YAML is read, not fitted.

## PR slices (do not combine)

| PR | Owns | Closes |
|---|---|---|
| 1 | pin.py, tests/test_contrato_tau.py, CI | six API facts + pin check |
| 2 | model.py, store.py, tests/test_store.py | V3 40/40 |
| 3 | tools.py, collect.py, gate.py, their tests | V1, V2, V6 |
| 4 | supervisor.py, cli.py, render.py, telemetry.py, integration test | last-turn gate, follow_up, productive cap, serve, A writes nothing |
| 5 | graph.py, project.py, tests/test_project.py | V4 synthetic |

Out of v1: SWE-Milestone adapter, V5 labels, analysis scripts, live calibration.

## Merge bar

A PR that needs a model key, edits tau, runs the gate on every turn, or uses an identical raw turn cap across arms does not merge.
