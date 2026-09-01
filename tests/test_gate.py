import inspect
import unittest

from tau_intent.collect import Region
from tau_intent.gate import GateConfig, Veredito, portao


def _region(path="src/a.py", start=1, end=3, size=None):
    return Region(
        path=path,
        line_start=start,
        line_end=end,
        size=size if size is not None else end - start + 1,
    )


class TestGate(unittest.TestCase):
    def test_gate_is_pure_no_tau_no_model(self):
        import tau_intent.gate as gate_mod

        source = inspect.getsource(gate_mod)
        self.assertNotIn("tau_agent", source)
        self.assertNotIn("tau_coding", source)
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("httpx", source)
        self.assertNotIn("requests", source)

    def test_v1_diffs_without_assertion_are_blocked(self):
        cfg = GateConfig(n_max=3, limiar_edicao=40)
        blocked = 0
        total = 12
        for i in range(total):
            region = _region(f"src/f{i}.py", 1, 2)
            verdict = portao([region], {}, set(), cfg, 0)
            self.assertEqual(verdict.tipo, "BLOQUEIA")
            self.assertEqual(verdict.falhas[0].code, "AUSENTE")
            blocked += 1
        self.assertEqual(blocked / total, 1.0)

    def test_v2_ausente(self):
        verdict = portao([_region()], {}, set(), GateConfig(), 0)
        self.assertEqual(verdict.falhas[0].code, "AUSENTE")
        self.assertEqual(verdict.tipo, "BLOQUEIA")

    def test_v2_generica(self):
        region = _region()
        pending = {"src/a.py": type("P", (), {"why": "corrige o bug", "property": "f ok"})()}
        verdict = portao([region], pending, {"f"}, GateConfig(), 0)
        self.assertEqual(verdict.falhas[0].code, "GENERICA")

    def test_v2_property_sem_simbolo(self):
        region = _region()
        pending = {
            "src/a.py": type(
                "P",
                (),
                {"why": "expõe o contrato de FilterError", "property": "MissingSymbol holds"},
            )()
        }
        verdict = portao([region], pending, {"FilterError"}, GateConfig(), 0)
        codes = [f.code for f in verdict.falhas]
        self.assertEqual(codes, ["PROPERTY_SEM_SIMBOLO"])

    def test_v2_edicao_grande_sem_property(self):
        region = _region(start=1, end=80, size=80)
        pending = {"src/a.py": type("P", (), {"why": "expõe incremento único", "property": ""})()}
        verdict = portao([region], pending, set(), GateConfig(limiar_edicao=40), 0)
        self.assertEqual(verdict.falhas[0].code, "EDICAO_GRANDE_SEM_PROPERTY")

    def test_escalar_after_n_max_blocks(self):
        region = _region()
        verdict = portao([region], {}, set(), GateConfig(n_max=2), bloqueios=2)
        self.assertEqual(verdict.tipo, "ESCALAR")

    def test_passa_when_assertion_is_specific(self):
        region = _region()
        pending = {
            "src/a.py": type(
                "P",
                (),
                {"why": "expõe f como incremento único", "property": "FilterError is raised"},
            )()
        }
        verdict = portao([region], pending, {"FilterError"}, GateConfig(), 0)
        self.assertEqual(verdict.tipo, "PASSA")
        self.assertIsInstance(verdict, Veredito)


if __name__ == "__main__":
    unittest.main()
