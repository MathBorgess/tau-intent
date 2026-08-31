import unittest


class TestPackageImports(unittest.TestCase):
    def test_version(self):
        from tau_intent import __version__

        self.assertEqual(__version__, "0.1.0")
