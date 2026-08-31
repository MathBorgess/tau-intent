"""Fake harness contract. Canonical coverage lives in test_integration.py."""

from __future__ import annotations

import unittest

from tau_intent.fake_provider import FakeHarness, FakeProvider


class TestFakeProviderCompat(unittest.TestCase):
    def test_harness_rejects_raw_max_turns(self) -> None:
        with self.assertRaises(ValueError):
            FakeHarness(max_turns=10)

    def test_provider_exists(self) -> None:
        self.assertTrue(callable(FakeProvider))
        self.assertEqual(FakeProvider.temperature_owner_set, 0)
