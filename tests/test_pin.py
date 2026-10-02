"""The pin must be exercised, not skipped (P-2): CI runs it with tau-ai installed."""

import contextlib
import io
import unittest
from importlib.metadata import PackageNotFoundError
from unittest import mock

from tau_intent import pin

try:
    import tau_agent  # noqa: F401
    TAU_INSTALLED = True
except ImportError:  # pragma: no cover - depends on the environment
    TAU_INSTALLED = False


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = pin.main(argv)
    return rc, out.getvalue()


class TestPin(unittest.TestCase):
    def test_skip_is_exit_zero_by_default_and_failure_when_installation_is_required(self):
        with mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError):
            rc, text = _run(["--check"])
            self.assertEqual(rc, 0)
            self.assertIn("SKIP", text)
            rc, text = _run(["--check", "--require-installed"])
            self.assertEqual(rc, 1)
            self.assertIn("SKIP", text)

    def test_version_mismatch_fails(self):
        with mock.patch("importlib.metadata.version", return_value="0.4.1"):
            rc, text = _run(["--check"])
        self.assertEqual(rc, 1)
        self.assertIn("mismatch", text)

    @unittest.skipUnless(TAU_INSTALLED, "needs the pinned tau-ai (pip install .[tau])")
    def test_installed_wheel_passes_and_matches_its_record(self):
        rc, text = _run(["--check", "--require-installed"])
        self.assertEqual(rc, 0, text)
        self.assertNotIn("SKIP", text)
        self.assertEqual(pin.local_edits(), [])

    def test_local_edit_of_an_installed_file_is_reported(self):
        class Hash:
            mode = "sha256"
            value = "AAAA"

        class Entry:
            hash = Hash()

            def __str__(self):
                return "tau_agent/loop.py"

        class Located:
            def read_bytes(self):
                return b"patched"

        class Dist:
            files = [Entry()]

            def locate_file(self, entry):
                return Located()

        with mock.patch("importlib.metadata.distribution", return_value=Dist()):
            self.assertEqual(pin.local_edits(), ["tau_agent/loop.py"])

    def test_declared_pin_is_the_owner_decision(self):
        self.assertEqual((pin.PINNED_DIST, pin.PINNED_VERSION), ("tau-ai", "0.4.7"))
        self.assertEqual(len(pin.PINNED_SHA256), 64)
