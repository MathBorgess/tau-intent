"""Telemetry (G-4, P-3, D5) and the graph cache key (P-6, D11)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tau_intent.collect import Region, collect_events, regions_from_diff
from tau_intent.graph import build_cached, cache_info, estado_da_arvore
from tau_intent.model import Anchor, IntentEntry
from tau_intent.telemetry import (
    TOKENIZER,
    aproveitamento_do_bloco,
    chave,
    cobertura_de_captura,
    count_tokens,
    latencia_de_captura,
    superadas_omitidas,
)


def _entry(file="src/mod.py", symbol="f", eid="1"):
    return IntentEntry(
        id=eid,
        ts="2026-09-02T00:00:00Z",
        task_id="t",
        anchor=Anchor(file=file, symbol=symbol, line_start=1, line_end=3, blob_sha="0" * 40),
        why="w",
        property="p",
        domain="d",
    )


class TestEspacoDeChave(unittest.TestCase):
    """D5: the two sides of the ratio used to be counted in different units."""

    def test_regiao_e_entrada_normalizam_para_a_mesma_chave(self) -> None:
        region = Region(path="src/mod.py", line_start=1, line_end=3, symbol="f")
        self.assertEqual(chave(region), "src/mod.py::f")
        self.assertEqual(chave(_entry()), "src/mod.py::f")
        self.assertEqual(chave(region), chave(_entry()))

    def test_sem_simbolo_dos_dois_lados_ainda_e_a_mesma_chave(self) -> None:
        region = Region(path="src/mod.py", line_start=1, line_end=3)
        self.assertEqual(chave(region), "src/mod.py")
        self.assertEqual(chave(_entry(symbol=None)), "src/mod.py")

    def test_simbolo_de_um_lado_so_nao_conta_como_coberto(self) -> None:
        """The silent break D5 warned about: fix symbol on one side and the
        old comparison would have gone on returning 1.0."""
        region = Region(path="src/mod.py", line_start=1, line_end=3, symbol="f")
        self.assertEqual(cobertura_de_captura([region], [_entry(symbol=None)]), 0.0)
        self.assertEqual(
            cobertura_de_captura([region], [_entry(symbol=None)], por_arquivo=True), 1.0
        )

    def test_cobertura_de_captura_e_uma_razao(self) -> None:
        regions = [
            Region(path="a.py", line_start=1, line_end=2, symbol="f"),
            Region(path="b.py", line_start=1, line_end=2, symbol="g"),
        ]
        self.assertEqual(cobertura_de_captura(regions, [_entry(file="a.py", symbol="f")]), 0.5)
        self.assertEqual(cobertura_de_captura([], [_entry()]), 0.0)


class TestLatenciaDeCaptura(unittest.TestCase):
    DIFF = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+def f():\n"
        "+    return 1\n"
    )

    def test_turnos_entre_a_escrita_e_o_record_intent(self) -> None:
        regions = regions_from_diff(self.DIFF)
        events = [
            {"tool_name": "write", "args": {"path": "src/mod.py", "content": "x"}},
            {"tool_name": "read", "args": {"path": "src/mod.py"}},
            {"tool_name": "bash", "args": {"command": "pytest", "description": "run"}},
            {"tool_name": "record_intent", "args": {
                "file": "src/mod.py", "why": "w", "domain": "d"}},
        ]
        tel = latencia_de_captura(collect_events(events, regions))
        self.assertEqual(tel["media"], 3)
        self.assertEqual(tel["maxima"], 3)
        self.assertEqual(tel["regioes_sem_intencao"], 0)

    def test_regiao_sem_intencao_e_contada_a_parte(self) -> None:
        regions = regions_from_diff(self.DIFF)
        events = [{"tool_name": "write", "args": {"path": "src/mod.py", "content": "x"}}]
        tel = latencia_de_captura(collect_events(events, regions))
        self.assertEqual(tel["regioes_sem_intencao"], 1)
        self.assertIsNone(tel["media"])


class TestAproveitamentoDoBloco(unittest.TestCase):
    def test_esqueleto_conta_reaparicao(self) -> None:
        servidas = [_entry(file="a.py", symbol="f"), _entry(file="b.py", symbol="g", eid="2")]
        depois = [Region(path="a.py", line_start=1, line_end=2, symbol="f")]
        tel = aproveitamento_do_bloco(servidas, depois)
        self.assertEqual(tel["servidas"], 2)
        self.assertEqual(tel["reaproveitadas"], 1)
        self.assertEqual(tel["razao"], 0.5)

    def test_sem_nada_servido_e_zero_nao_erro(self) -> None:
        self.assertEqual(aproveitamento_do_bloco([])["razao"], 0.0)


class TestSuperadas(unittest.TestCase):
    def test_conta_o_que_o_bloco_nao_serve(self) -> None:
        todas = [_entry(eid="1"), _entry(eid="2"), _entry(eid="3")]
        self.assertEqual(superadas_omitidas(todas, [todas[0]]), 2)


class TestTokenizador(unittest.TestCase):
    def test_declarado_e_nunca_chars_por_quatro(self) -> None:
        self.assertEqual(TOKENIZER, "whitespace-v1")
        self.assertEqual(count_tokens("um dois tres"), 3)
        self.assertEqual(count_tokens("   "), 0)


class TestCacheDoGrafo(unittest.TestCase):
    """P-6 / D11: same SHA, different tree states must not collide."""

    def test_pre_edicao_e_pos_edicao_no_mesmo_sha_nao_colidem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alvo = root / "m.py"
            alvo.write_text("def f():\n    return 1\n", encoding="utf-8")
            antes = estado_da_arvore(root)
            g1 = build_cached(str(root), "sha-fixo")
            self.assertIn("m.py::f", g1.nodes)
            self.assertNotIn("m.py::g", g1.nodes)

            alvo.write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8")
            depois = estado_da_arvore(root)
            self.assertNotEqual(antes, depois)

            g2 = build_cached(str(root), "sha-fixo")
            self.assertIn("m.py::g", g2.nodes)
            self.assertIsNot(g1, g2)

    def test_mesmo_estado_reaproveita_o_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            antes = cache_info().hits
            primeiro = build_cached(str(root), "sha-fixo")
            segundo = build_cached(str(root), "sha-fixo")
            self.assertIs(primeiro, segundo)
            self.assertGreater(cache_info().hits, antes)

    def test_estado_da_arvore_e_por_conteudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alvo = root / "m.py"
            alvo.write_text("a = 1\n", encoding="utf-8")
            primeiro = estado_da_arvore(root)
            alvo.write_text("a = 2\n", encoding="utf-8")  # same size, same tick
            self.assertNotEqual(primeiro, estado_da_arvore(root))
            alvo.write_text("a = 1\n", encoding="utf-8")
            self.assertEqual(primeiro, estado_da_arvore(root))


if __name__ == "__main__":
    unittest.main()
