"""The runner against the real task set (``tidelot-chain``, built in mathai-harness).

Skipped unless the directory is present (a sibling checkout of mathai-harness, or
``TAU_INTENT_REAL_TASKSET``) and pytest is available. There is no import of
mathai-harness: the hash and the oracle are the runner's own implementation, and
this test is what ties it to the other repo's exact encoding and layout.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
    HAVE_PYTEST = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_PYTEST = False

from tau_intent.bench.oracle import run_oracle
from tau_intent.bench.taskset import load_taskset

REAL = Path(os.environ.get("TAU_INTENT_REAL_TASKSET")
            or Path(__file__).resolve().parents[2] / "mathai-harness" / "taskset")
#: task_set_sha announced for tidelot-chain 0.1.0. Update it when the task set is re-frozen.
EXPECTED_SHA = "9189ebc0f99df7f3c0c1bd41572bdec832fda06184897d658828693ecfc38dbc"


@unittest.skipUnless(HAVE_PYTEST and (REAL / "taskset.json").is_file(),
                     "needs pytest and the real task set (sibling mathai-harness/taskset)")
class TestRealTaskset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = load_taskset(REAL)

    def test_task_set_sha_matches_the_one_the_task_set_repo_prints(self):
        self.assertEqual(self.ts.sha, EXPECTED_SHA)
        self.assertEqual((self.ts.id, len(self.ts.tasks)), ("tidelot-chain", 6))
        self.assertEqual(self.ts.qualification.id, "Q0")

    def workspace_from(self, tmp: Path, source: Path) -> Path:
        target = tmp / "ws"
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        return target

    def test_sanity_rules_of_the_contract_hold_under_the_runners_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            seed = self.workspace_from(tmp, self.ts.seed)
            self.assertFalse(run_oracle(self.ts, 1, seed)["pass"], "the seed must not already solve task 1")
            for k in range(1, 7):
                ref = tmp / f"ref{k}"
                shutil.copytree(self.ts.root / "reference" / f"{k:02d}", ref,
                                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
                result = run_oracle(self.ts, k, ref)
                self.assertTrue(result["pass"], f"reference/{k:02d} must pass the oracle of task {k}\n"
                                                f"{result['output_tail']}")
                self.assertEqual({t["nodeid"].split("/")[1] for t in result["per_test"]},
                                 {f"{j:02d}" for j in range(1, k + 1)})  # regression included
                if k > 1:
                    previous = tmp / f"ref{k - 1}"
                    self.assertFalse(run_oracle(self.ts, k, previous)["pass"],
                                     f"reference/{k - 1:02d} must not already solve task {k}")

    def test_qualification_task_q0(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            seed = tmp / "seed"
            shutil.copytree(self.ts.qualification.seed, seed)
            ref = tmp / "ref"
            shutil.copytree(self.ts.root / "qualification" / "reference", ref)
            self.assertFalse(run_oracle(self.ts, 0, seed)["pass"])
            self.assertTrue(run_oracle(self.ts, 0, ref)["pass"])


if __name__ == "__main__":
    unittest.main()
