# V2 reconstruction — execution ledger

Contract: SPEC-V2.md; owner request 2026-09-05. No benchmark, no live model,
no runtime dependency, no PR. Synthetic fixtures only. Execute inline.
The design and slices were supplied by the owner; no new gate proposal is authorized.

Baseline cb1fdee99e7dd68229c47a54135bc61d66b39c7f: 203 tests pass;
pin skipped (tau-ai absent, NO_NETWORK=1). All three reported defects reproduced.
Normal code golden and config hashes captured before edits in tests/fixtures/v1_1_code.json.
Owner authorized updating only test expectations incompatible with V2 on 2026-09-05.

Each slice: write regression, observe failure, implement, run affected tests,
record separate local commit with generality ADR. Wave 1 owns disjoint source/test files.

| Slice | Files / responsibility | Verification |
|---|---|---|
| P1 | collect.py, gate.py; resolver provenance, unavailable checks | test_v2_p1.py; Go 6x20 and strict case |
| P2 | telemetry.py; structured coverage and empty denominators | test_v2_p2.py, test_telemetry.py |
| P3 | rescue.py; format registry and empty recall | test_v2_p3.py |
| P4 | render.py, project.py; absent neighbourhood receipt | test_v2_p4.py, test_render.py |
| P5 | manifest.py, supervisor.py; coverage distribution and exclusion assert | test_v2_p5.py; config hash golden |
| P6 | adapters protocol/registry/code; move substrate routines unchanged | test_v2_equivalence.py; golden and moved-source hashes |
| P7 | checkpoint schema, model/store/collector rendering | test_v2_checkpoint.py; deterministic round trip |
| P8 | adapters/state.py; typed store delta/anchor/graph/oracle | test_v2_state.py; synthetic end-to-end, no ast import |
| P9 | serve.py; read-only retrieval surface | test_v2_serve.py; top_k and no writes |
| P10 | manifest/report model pair validation | test_v2_handoff.py; pooled reports rejected |
| D | MECHANISM, DELTA, GATE-PROPOSAL, vault briefing | claims reconciled with execution; no preregistration edit |

P1 is a mechanism change, not a behavior-preserving repair. Threshold remains 51.
Adapter-neutral wire migration does not rename the frozen legacy gate code identifiers.
