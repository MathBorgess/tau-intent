"""Structural gate (G-8, G-1, G-2). No lexical judgement anywhere here."""

import inspect
import unittest

from tau_intent.collect import Region
from tau_intent.gate import CODIGOS, GateConfig, Veredito, portao


def _region(path="src/a.py", start=1, end=3, size=None, **extra):
    region = Region(
        path=path,
        line_start=start,
        line_end=end,
        size=size if size is not None else end - start + 1,
    )
    for key, value in extra.items():
        setattr(region, key, value)
    return region


def _pending(**fields):
    base = {
        "why": "expõe f como incremento único",
        "property": "f retorna int",
        "domain": "demo",
        "symbol": "",
        "unparseable": False,
    }
    base.update(fields)
    return type("P", (), base)()


class TestGate(unittest.TestCase):
    def test_gate_is_pure_no_tau_no_model(self):
        import tau_intent.gate as gate_mod

        source = inspect.getsource(gate_mod)
        self.assertNotIn("tau_agent", source)
        self.assertNotIn("tau_coding", source)
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("httpx", source)
        self.assertNotIn("requests", source)

    def test_taxonomia_e_estrutural(self):
        self.assertEqual(
            set(CODIGOS),
            {
                "AUSENTE",
                "NAO_PARSEAVEL",
                "ANCORA_AMBIGUA",
                "SIMBOLO_NAO_RESOLVIDO",
                "EDICAO_GRANDE_SEM_SIMBOLO",
                "DOMINIO_AUSENTE",
            },
        )
        self.assertEqual(set(GateConfig().codigos), set(CODIGOS))

    def test_v1_diffs_without_assertion_are_blocked(self):
        cfg = GateConfig(n_max=3, limiar_edicao=40)
        for i in range(12):
            region = _region(f"src/f{i}.py", 1, 2)
            verdict = portao([region], {}, set(), cfg, 0)
            self.assertEqual(verdict.tipo, "BLOQUEIA")
            self.assertEqual(verdict.falhas[0].code, "AUSENTE")

    def test_ausente(self):
        verdict = portao([_region()], {}, set(), GateConfig(), 0)
        self.assertEqual(verdict.falhas[0].code, "AUSENTE")
        self.assertEqual(verdict.tipo, "BLOQUEIA")

    def test_v6_nao_parseavel_separado_de_ausente(self):
        """V6 no longer collapses into V1 (G-2)."""
        region = _region()
        pendentes = {"src/a.py": _pending(unparseable=True, raw_arguments="{not json")}
        verdict = portao([region], pendentes, set(), GateConfig(), 0)
        self.assertEqual([f.code for f in verdict.falhas], ["NAO_PARSEAVEL"])

    def test_ancora_ambigua_um_intent_duas_regioes(self):
        shared = _pending()
        regions = [_region(start=1, end=3), _region(start=40, end=42)]
        pendentes = {"src/a.py": shared}
        verdict = portao(regions, pendentes, {"src/a.py::f"}, GateConfig(), 0)
        codes = [f.code for f in verdict.falhas]
        self.assertEqual(codes, ["ANCORA_AMBIGUA", "ANCORA_AMBIGUA"])

    def test_simbolo_nao_resolvido_usa_ast_nao_prosa(self):
        region = _region()
        pendentes = {"src/a.py": _pending(symbol="naoExiste")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual([f.code for f in verdict.falhas], ["SIMBOLO_NAO_RESOLVIDO"])

    def test_simbolo_resolvido_por_node_id_passa(self):
        region = _region()
        pendentes = {"src/a.py": _pending(symbol="f")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual(verdict.tipo, "PASSA")

    def test_edicao_grande_sem_simbolo(self):
        region = _region(start=1, end=80, size=80)
        pendentes = {"src/a.py": _pending(symbol="")}
        verdict = portao([region], pendentes, set(), GateConfig(limiar_edicao=40), 0)
        self.assertIn("EDICAO_GRANDE_SEM_SIMBOLO", [f.code for f in verdict.falhas])

    def test_edicao_grande_com_simbolo_resolvido_passa(self):
        region = _region(start=1, end=80, size=80)
        pendentes = {"src/a.py": _pending(symbol="f")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(limiar_edicao=40), 0)
        self.assertEqual(verdict.tipo, "PASSA")

    def test_dominio_ausente(self):
        region = _region()
        pendentes = {"src/a.py": _pending(domain="", symbol="f")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual([f.code for f in verdict.falhas], ["DOMINIO_AUSENTE"])

    def test_escalar_after_n_max_blocks(self):
        verdict = portao([_region()], {}, set(), GateConfig(n_max=2), bloqueios=2)
        self.assertEqual(verdict.tipo, "ESCALAR")

    def test_passa(self):
        region = _region()
        pendentes = {"src/a.py": _pending(symbol="f")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual(verdict.tipo, "PASSA")
        self.assertIsInstance(verdict, Veredito)


class TestRegressaoD2D7D8(unittest.TestCase):
    """The three defects the roadmap verified line by line at b312672."""

    def test_d2_prosa_de_property_nao_e_mais_evidencia(self):
        """A property citing a symbol nobody defined is not a failure any more.

        The old PROPERTY_SEM_SIMBOLO scraped the property text and compared it
        against a symbol set that the supervisor built from the property texts
        themselves — almost unfalsifiable. Only the typed ``symbol`` field is
        evidence now.
        """
        region = _region()
        pendentes = {"src/a.py": _pending(property="MissingSymbol holds", symbol="")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual(verdict.tipo, "PASSA")

    def test_d2_why_generico_nao_e_mais_falha(self):
        """H15: rationale quality is not a gate. No GENERICA code exists."""
        region = _region()
        pendentes = {"src/a.py": _pending(why="corrige o bug", symbol="f")}
        verdict = portao([region], pendentes, {"src/a.py::f"}, GateConfig(), 0)
        self.assertEqual(verdict.tipo, "PASSA")
        self.assertNotIn("GENERICA", CODIGOS)

    def test_d7_region_size_desconta_contexto(self):
        """Hunk length is not edit size. contexto_diff is declared, not implicit."""
        # 44-line hunk, 3 context lines each side => 38 edited lines, under 40.
        region = _region(start=1, end=44, size=44)
        pendentes = {"src/a.py": _pending(symbol="")}
        cfg = GateConfig(limiar_edicao=40, contexto_diff=3)
        verdict = portao([region], pendentes, set(), cfg, 0)
        self.assertEqual(verdict.tipo, "PASSA")

    def test_d7_edited_lines_exato_vence_a_estimativa(self):
        region = _region(start=1, end=44, size=44, edited_lines=44)
        pendentes = {"src/a.py": _pending(symbol="")}
        cfg = GateConfig(limiar_edicao=40, contexto_diff=3)
        verdict = portao([region], pendentes, set(), cfg, 0)
        self.assertIn("EDICAO_GRANDE_SEM_SIMBOLO", [f.code for f in verdict.falhas])

    def test_d8_stopwords_e_regex_foram_apagados(self):
        """Not disabled — deleted. Checked on the AST, so a docstring mentioning
        the dead names by way of explanation does not fake a pass."""
        import ast

        import tau_intent.gate as gate_mod

        for morto in ("GENERICAS", "_STOP", "_cited_symbols", "GENERICA"):
            self.assertFalse(hasattr(gate_mod, morto), f"ressuscitado: {morto}")

        tree = ast.parse(inspect.getsource(gate_mod))
        nomes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nomes.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                nomes.add(node.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "re", "regex de volta no portão")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "re", "regex de volta no portão")
        self.assertFalse(
            nomes & {"GENERICAS", "_STOP", "_cited_symbols", "GENERICA"},
            f"caminho lexical ressuscitado: {nomes}",
        )


if __name__ == "__main__":
    unittest.main()
