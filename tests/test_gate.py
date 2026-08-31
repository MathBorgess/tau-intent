import unittest

from tau_intent.gate import evaluate_gate


class TestGate(unittest.TestCase):
    def test_v1_all_without_assertion_block(self):
        blocks = [
            {"path": "a.py", "size": 2, "pending_assertion": False, "why": "", "property": ""},
            {"path": "b.py", "size": 8, "pending_assertion": False, "why": "", "property": ""},
        ]
        result = evaluate_gate(blocks, symbols={"ok"}, blocked_count=0, n_max=2)
        self.assertEqual(result["verdict"], "BLOQUEIA")
        self.assertEqual([f["code"] for f in result["failures"]], ["AUSENTE", "AUSENTE"])

    def test_v2_generica(self):
        blocks = [
            {
                "path": "a.py",
                "size": 2,
                "pending_assertion": True,
                "why": "refatora",
                "property": "ok_symbol must remain",
            }
        ]
        result = evaluate_gate(blocks, symbols={"ok_symbol"}, blocked_count=0, n_max=2)
        self.assertIn("GENERICA", [f["code"] for f in result["failures"]])

    def test_v2_property_sem_simbolo(self):
        blocks = [
            {
                "path": "a.py",
                "size": 2,
                "pending_assertion": True,
                "why": "explica mudança",
                "property": "unknown_symbol remains stable",
            }
        ]
        result = evaluate_gate(blocks, symbols={"known_symbol"}, blocked_count=0, n_max=2)
        self.assertIn("PROPERTY_SEM_SIMBOLO", [f["code"] for f in result["failures"]])

    def test_v2_edicao_grande_sem_property(self):
        blocks = [
            {
                "path": "a.py",
                "size": 20,
                "pending_assertion": True,
                "why": "explica mudança",
                "property": "",
            }
        ]
        result = evaluate_gate(blocks, symbols={"known_symbol"}, blocked_count=0, n_max=2)
        self.assertIn("EDICAO_GRANDE_SEM_PROPERTY", [f["code"] for f in result["failures"]])

    def test_v2_ausente(self):
        blocks = [{"path": "a.py", "size": 2, "pending_assertion": False, "why": "", "property": ""}]
        result = evaluate_gate(blocks, symbols={"ok_symbol"}, blocked_count=0, n_max=2)
        self.assertIn("AUSENTE", [f["code"] for f in result["failures"]])

    def test_escalar_after_n_max_blocks(self):
        blocks = [{"path": "a.py", "size": 2, "pending_assertion": False, "why": "", "property": ""}]
        result = evaluate_gate(blocks, symbols={"ok_symbol"}, blocked_count=2, n_max=2)
        self.assertEqual(result["verdict"], "ESCALAR")
