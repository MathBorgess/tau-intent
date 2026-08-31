"""CLI flags. Canonical coverage also lives in test_integration.py."""

from __future__ import annotations

import unittest

from tau_intent.cli import flags_from_args, parse_args


class TestCliFlags(unittest.TestCase):
    def test_four_independent_flags(self) -> None:
        args = parse_args(["--capture", "--gate", "--no-project", "--serve"])
        self.assertTrue(args.capture)
        self.assertTrue(args.gate)
        self.assertFalse(args.project)
        self.assertTrue(args.serve)

    def test_arm_a_only_in_flag_reading(self) -> None:
        flags = flags_from_args(["--arm", "A"])
        self.assertFalse(flags.capture)
        self.assertFalse(flags.gate)
        self.assertFalse(flags.project)
        self.assertFalse(flags.serve)

    def test_arm_c(self) -> None:
        flags = flags_from_args(["--arm", "C"])
        self.assertTrue(flags.capture and flags.gate and flags.project and flags.serve)
