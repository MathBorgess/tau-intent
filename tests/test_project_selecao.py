"""The v1 selection, declared and tested (P-0, D12, D10, P-5 escopada ao braço B)."""

from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import dataclass

import tau_intent.project as project_mod
from tau_intent.project import (
    DEFAULTS,
    ProjectConfig,
    _custo_do_envelope,
    _guloso_com_fallback_singleton,
    load_project_config,
    render_tudo,
)
from tau_intent.render import render_tudo as render_tudo_oficial


@dataclass(frozen=True)
class _E:
    nome: str


class TestSelecaoDeclarada(unittest.TestCase):
    def test_yaml_declara_a_selecao_e_as_chaves_de_ablacao(self) -> None:
        from tau_intent.config import load_yaml
        from tau_intent.project import DEFAULTS_PATH

        raw = load_yaml(DEFAULTS_PATH)
        self.assertEqual(raw["selecao"], "relevancia-guloso-por-razao+singleton")
        self.assertIs(raw["repr"], False)
        self.assertIs(raw["div"], False)
        cfg = load_project_config()
        self.assertFalse(cfg.repr)
        self.assertFalse(cfg.div)
        self.assertFalse(cfg.llm_rescue)

    def test_peso_de_tipo_veio_do_yaml(self) -> None:
        """Was a bare 1.0/0.7 inside the scoring line — undeclared parameter."""
        cfg = load_project_config()
        self.assertEqual(cfg.peso_tipo_com_property, DEFAULTS["peso_tipo_com_property"])
        self.assertEqual(cfg.peso_tipo_sem_property, DEFAULTS["peso_tipo_sem_property"])
        self.assertNotEqual(cfg.peso_tipo_com_property, cfg.peso_tipo_sem_property)

    def test_projetar_nao_le_constante_de_fora_do_config(self) -> None:
        tree = ast.parse(inspect.getsource(project_mod))
        alvo = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "projetar"
        )
        for node in ast.walk(alvo):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if isinstance(node.value, bool):
                    continue
                self.assertIn(node.value, {0, 1, 2}, f"literal {node.value!r} em projetar")


class TestRecusaFacilityLocation(unittest.TestCase):
    """P-0: the v1 path is relevance-only. No coverage term, no submodularity."""

    def test_sem_apricot_e_sem_similaridade_par_a_par(self) -> None:
        fonte = inspect.getsource(project_mod)
        for proibido in ("apricot", "FacilityLocation", "BidirectionalGreedy", "sample_cost"):
            self.assertNotIn(proibido, fonte)

    def test_valor_de_uma_entrada_nao_depende_das_outras(self) -> None:
        """A facility-location objective would discount a near-duplicate. The
        v1 selector must keep both when both fit."""
        scored = [(1.0, 4, _E("a")), (1.0, 4, _E("a-duplicata")), (0.9, 4, _E("b"))]
        escolhidas, cortadas = _guloso_com_fallback_singleton(scored, 12)
        self.assertEqual({e.nome for e in escolhidas}, {"a", "a-duplicata", "b"})
        self.assertEqual(cortadas, [])


class TestFallbackDeSingleton(unittest.TestCase):
    """The half that makes the Khuller-Moss-Naor guarantee citable."""

    def test_guloso_puro_perderia_e_o_singleton_salva(self) -> None:
        scored = [(1.0, 1, _E("isca")), (40.0, 50, _E("grande"))]
        escolhidas, cortadas = _guloso_com_fallback_singleton(scored, 50)
        self.assertEqual([e.nome for e in escolhidas], ["grande"])
        self.assertEqual([e.nome for e in cortadas], ["isca"])

    def test_guloso_vence_quando_e_melhor(self) -> None:
        scored = [(3.0, 5, _E("a")), (3.0, 5, _E("b")), (5.0, 10, _E("c"))]
        escolhidas, _ = _guloso_com_fallback_singleton(scored, 10)
        self.assertEqual({e.nome for e in escolhidas}, {"a", "b"})

    def test_nada_cabe_e_nada_e_escolhido(self) -> None:
        escolhidas, cortadas = _guloso_com_fallback_singleton([(9.0, 99, _E("x"))], 10)
        self.assertEqual(escolhidas, [])
        self.assertEqual(len(cortadas), 1)


class TestCorteLinear(unittest.TestCase):
    """D12: the block was re-rendered once per candidate — O(n^2) in tokens."""

    def test_render_block_nao_e_chamado_dentro_do_laco(self) -> None:
        fonte = inspect.getsource(_guloso_com_fallback_singleton)
        self.assertNotIn("render_block", fonte)
        self.assertNotIn("count_tokens", fonte)

    def test_custo_por_entrada_e_calculado_uma_vez(self) -> None:
        fonte = inspect.getsource(project_mod.projetar)
        self.assertEqual(fonte.count("count_tokens(render_entry("), 1)

    def test_overhead_do_envelope_e_constante(self) -> None:
        self.assertGreater(_custo_do_envelope(), 0)


class TestRenderTudoTemUmaCasaSo(unittest.TestCase):
    def test_project_reexporta_o_render_oficial(self) -> None:
        """D10: two divergent implementations of the same function, gone."""
        self.assertIs(render_tudo, render_tudo_oficial)
        self.assertIs(project_mod.render_block, __import__(
            "tau_intent.render", fromlist=["render_block"]).render_block)

    def test_project_nao_define_render_proprio(self) -> None:
        tree = ast.parse(inspect.getsource(project_mod))
        definidos = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        self.assertFalse(definidos & {"render_entry", "render_block", "render_tudo"})


class TestPurezaDoBracoB(unittest.TestCase):
    """P-5, escopada ao braço B pela decisão H17 do dono.

    H17 está decidida: o `llm_rescue` do braço C existe e é deliberado (H16).
    A pureza que a P-5 pede vale para **B**: com `llm_rescue=off` nenhum
    componente mediado por modelo entra no caminho de projeção, e nenhum
    sumarizador é chamado nem que o chamador passe um.
    """

    def test_braco_b_nao_chama_sumarizador_nem_se_receber_um(self) -> None:
        import tempfile
        from pathlib import Path

        from tau_intent.graph import build
        from tau_intent.project import projetar

        chamadas = []

        def sumarizador(corpo):
            chamadas.append(corpo)
            return "resumo"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            graph = build(root)
            cfg = load_project_config()
            self.assertFalse(cfg.llm_rescue)
            entradas = [
                type("E", (), {
                    "anchor": type("A", (), {
                        "file": "m.py", "symbol": "f",
                        "node_id": lambda self: "m.py::f"})(),
                    "why": "expõe f", "property": "f retorna int", "ts": "t",
                })()
            ]
            _bloco, tel = projetar(graph, entradas, ["m.py::f"], cfg, summarizer_fn=sumarizador)
        self.assertEqual(chamadas, [])
        self.assertFalse(tel["llm_rescue"])

    def test_modulo_de_projecao_nao_importa_provedor(self) -> None:
        tree = ast.parse(inspect.getsource(project_mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith(("openai", "httpx", "requests")))
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(node.module.startswith(("openai", "httpx", "requests")))


class TestConfigAblacao(unittest.TestCase):
    def test_ligar_repr_ou_div_e_experimento_explicito(self) -> None:
        cfg = ProjectConfig(repr=True)
        self.assertTrue(cfg.repr)
        self.assertFalse(load_project_config().repr)


if __name__ == "__main__":
    unittest.main()
