"""Supervisor arm A. Canonical coverage lives in test_integration.py."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tau_intent.cli import flags_from_args
from tau_intent.supervisor import run_task


class TestSupervisorCompat(unittest.TestCase):
    def test_run_task_arm_a_no_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("x=1\n", encoding="utf-8")
            result = asyncio.run(
                run_task(
                    root,
                    flags_from_args(["--arm", "A", "--fake-provider"]),
                    max_productive_turns=2,
                    diff=(
                        "diff --git a/m.py b/m.py\n"
                        "--- a/m.py\n"
                        "+++ b/m.py\n"
                        "@@ -1,0 +1,1 @@\n"
                        "+x=1\n"
                    ),
                )
            )
            self.assertFalse((root / "intents.jsonl").exists())
            self.assertEqual(result.verdict, "PASSA")
