"""Block contract (P-1, D9, D10). Shape, order, receipt."""

from __future__ import annotations

import unittest

from tau_intent.config import load_bloco_config
from tau_intent.model import Anchor, IntentEntry
from tau_intent.render import Recibo, envelope, render_block, render_entry, render_tudo


def _entry(file="src/mod.py", symbol="f", why="expõe f", prop="f retorna int"):
    return IntentEntry(
        id="1",
        ts="2026-09-02T00:00:00Z",
        task_id="t",
        anchor=Anchor(file=file, symbol=symbol, line_start=1, line_end=3, blob_sha="0" * 40),
        why=why,
        property=prop,
        domain="demo",
    )


class TestEnvelope(unittest.TestCase):
    def test_forma_do_envelope(self) -> None:
        cfg = load_bloco_config()
        bloco = render_block([_entry()])
        self.assertTrue(bloco.startswith(f"<{cfg.envelope_tag}>"))
        self.assertTrue(bloco.rstrip().endswith(f"</{cfg.envelope_tag}>"))
        self.assertIn(cfg.aviso, bloco)
        self.assertIn("evidência", cfg.aviso.lower())
        self.assertIn("não instrução", cfg.aviso.lower())

    def test_tag_vem_do_yaml_nao_do_codigo(self) -> None:
        from tau_intent.config import BlocoConfig

        outra = BlocoConfig(envelope_tag="outra_tag")
        self.assertIn("<outra_tag>", render_block([_entry()], cfg=outra))

    def test_ancora_usa_node_id(self) -> None:
        self.assertIn("src/mod.py::f", render_entry(_entry()))
        self.assertNotIn("::", render_entry(_entry(symbol=None)))


class TestOrdemDosCampos(unittest.TestCase):
    def test_property_antes_de_why(self) -> None:
        texto = render_entry(_entry())
        self.assertLess(texto.index("Propriedade:"), texto.index("Por que:"))

    def test_ordem_e_declarada_no_yaml(self) -> None:
        from tau_intent.config import BlocoConfig

        invertida = BlocoConfig(ordem_dos_campos=("file", "symbol", "why", "property"))
        texto = render_entry(_entry(), invertida)
        self.assertLess(texto.index("Por que:"), texto.index("Propriedade:"))


class TestRecibo(unittest.TestCase):
    def test_recibo_aparece_com_zero_omissoes(self) -> None:
        """A missing receipt and a receipt of zeros say different things."""
        bloco = render_block([_entry()])
        self.assertIn("Recibo:", bloco)
        self.assertIn("0 nós alcançáveis não expandidos", bloco)
        self.assertIn("0 superadas omitidas", bloco)
        self.assertIn("0 cortadas por orçamento", bloco)

    def test_recibo_tem_as_tres_metades_de_omissao(self) -> None:
        bloco = render_block(
            [_entry()], [_entry(symbol="g")], saltos_omitidos=4, superadas_omitidas=2
        )
        self.assertIn("1 entradas servidas", bloco)
        self.assertIn("4 nós alcançáveis não expandidos", bloco)
        self.assertIn("2 superadas omitidas", bloco)
        self.assertIn("1 cortadas por orçamento", bloco)

    def test_recibo_como_dado(self) -> None:
        recibo = Recibo(entradas=1, saltos_omitidos=2, superadas_omitidas=3, cortadas_por_orcamento=4)
        self.assertEqual(
            recibo.as_dict(),
            {
                "entradas": 1,
                "saltos_omitidos": 2,
                "superadas_omitidas": 3,
                "cortadas_por_orcamento": 4,
            },
        )
        self.assertFalse(recibo.vazio())

    def test_bloco_totalmente_vazio_nao_vira_envelope(self) -> None:
        self.assertEqual(render_block([]), "")

    def test_zero_entradas_mas_com_omissao_ainda_avisa(self) -> None:
        """Serving nothing while hiding something is the case the agent most
        needs told."""
        bloco = render_block([], superadas_omitidas=3)
        self.assertIn("3 superadas omitidas", bloco)
        self.assertIn("<", bloco)


class TestEnvelopeReusavel(unittest.TestCase):
    def test_corpo_sumarizado_mantem_envelope_e_recibo(self) -> None:
        """llm_rescue rewrites the body; it may not touch envelope or receipt."""
        cfg = load_bloco_config()
        recibo = Recibo(entradas=2, cortadas_por_orcamento=5)
        texto = envelope("resumo de duas linhas", recibo)
        self.assertTrue(texto.startswith(f"<{cfg.envelope_tag}>"))
        self.assertIn(cfg.aviso, texto)
        self.assertIn("5 cortadas por orçamento", texto)
        self.assertIn("resumo de duas linhas", texto)


class TestRenderTudoTemUmaCasaSo(unittest.TestCase):
    def test_render_e_a_casa_do_contrato(self) -> None:
        """D10: render.py owns render_entry/render_block/render_tudo. The twin
        copy in project.py is removed by PR-6, whose test asserts the identity
        of the two names."""
        import tau_intent.render as render_mod

        for nome in ("render_entry", "render_block", "render_tudo", "envelope"):
            self.assertTrue(callable(getattr(render_mod, nome)))

    def test_render_tudo_sem_orcamento_e_sem_envelope(self) -> None:
        texto = render_tudo([_entry(), _entry(symbol="g")])
        self.assertIn("src/mod.py::f", texto)
        self.assertIn("src/mod.py::g", texto)
        self.assertNotIn("Recibo:", texto)


if __name__ == "__main__":
    unittest.main()
