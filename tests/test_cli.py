import unittest

from tau_intent.cli import parse_args


class TestCliFlags(unittest.TestCase):
    def test_four_independent_flags(self):
        args = parse_args(["--capture", "--gate", "--no-project", "--serve"])
        self.assertTrue(args.capture)
        self.assertTrue(args.gate)
        self.assertFalse(args.project)
        self.assertTrue(args.serve)
