"""Bench V0: `tau-intent bench` (docs/BENCH-V0-CONTRACT.md §2-§5).

V0 is instrumentation, not measured collection: every record carries
``"draft": true`` and nothing it produces is a TG result before G2.
"""

RUNNER_NAME = "tau-intent"
SCHEMA_VERSION = "gambiarra-coleta-2"
TASKSET_SCHEMA = "tg-taskset-1"
