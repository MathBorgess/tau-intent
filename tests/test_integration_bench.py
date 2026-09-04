"""Bancada B × C (P-4, V2, V4, P9). Provedor falso, sem chave e sem HTTP."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tau_intent.cli import flags_from_args
from tau_intent.config import config_hashes, load_bloco_config
from tau_intent.fake_provider import FakeHarness, passing_script
from tau_intent.manifest import RelatoIncoerente, conferir_v4_v5, manifest_da_execucao
from tau_intent.model import Anchor, IntentEntry
from tau_intent.rescue import simbolos_ancorados, sumarizador_falso
from tau_intent.store import IntentStore
from tau_intent.supervisor import run_task

DIFF = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
)


def _semear(root: Path) -> Path:
    """Workspace with a real tree and a store that already holds intent."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "mod.py").write_text(
        "def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8"
    )
    store = IntentStore(root)
    for i, symbol in enumerate(("f", "g"), start=1):
        store.append(
            IntentEntry(
                id=f"seed-{i}",
                ts=f"2026-09-0{i}T00:00:00Z",
                task_id="seed",
                anchor=Anchor(
                    file="src/mod.py",
                    symbol=symbol,
                    line_start=1 + (i - 1) * 4,
                    line_end=2 + (i - 1) * 4,
                    blob_sha="0" * 40,
                ),
                why=f"expõe {symbol} porque a tarefa anterior precisava desse recorte e não de outro",
                property=f"{symbol} retorna int e nunca levanta em entrada vazia",
                domain="demo",
            )
        )
    return root


def _rodar(root: Path, arm: str):
    flags = flags_from_args(["--arm", arm])
    return asyncio.run(
        run_task(
            root,
            flags,
            harness=FakeHarness(passing_script(), max_turns=None),
            diff=DIFF,
            summarizer_fn=sumarizador_falso() if flags.llm_rescue else None,
        )
    )


class TestBlocoDeCNaoEVazio(unittest.TestCase):
    """O buraco que deixou o D3 passar por um merge inteiro."""

    def test_c_serve_bloco_nao_vazio_no_caminho_integrado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resultado = _rodar(_semear(Path(tmp)), "C")
        self.assertTrue(resultado.bloco.strip())
        self.assertFalse(resultado.telemetry["bloco_vazio"])
        self.assertFalse(resultado.telemetry["ancoras_vazias"])
        self.assertGreater(resultado.telemetry["tokens_served"], 0)
        self.assertIn("src/mod.py::f", resultado.telemetry["ancoras"])

    def test_b_tambem_serve_bloco_projetado(self) -> None:
        """H16: B projeta. Se B servisse o store inteiro, isto passaria por
        acidente — por isso o teste olha o recibo, não só o tamanho."""
        with tempfile.TemporaryDirectory() as tmp:
            resultado = _rodar(_semear(Path(tmp)), "B")
        self.assertTrue(resultado.bloco.strip())
        self.assertIn("Recibo:", resultado.bloco)
        self.assertIn("recibo", resultado.telemetry)
        self.assertNotIn("serve_sem_projecao", resultado.telemetry)

    def test_a_nao_serve_nada_e_nao_escreve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _semear(Path(tmp))
            antes = (root / "intents.jsonl").read_text(encoding="utf-8")
            resultado = _rodar(root, "A")
            depois = (root / "intents.jsonl").read_text(encoding="utf-8")
        self.assertEqual(resultado.bloco, "")
        self.assertEqual(antes, depois)


class TestBxC(unittest.TestCase):
    """Envelope, posição e recibo idênticos; só o corpo difere, e só em C."""

    def _dois(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            b = _rodar(_semear(raiz / "b"), "B")
            c = _rodar(_semear(raiz / "c"), "C")
            return b, c

    def test_envelope_e_posicao_identicos(self) -> None:
        cfg = load_bloco_config()
        b, c = self._dois()
        for resultado in (b, c):
            self.assertTrue(resultado.bloco.startswith(f"<{cfg.envelope_tag}>"))
            self.assertTrue(resultado.bloco.rstrip().endswith(f"</{cfg.envelope_tag}>"))
            self.assertIn(cfg.aviso, resultado.bloco)
        self.assertEqual(
            b.telemetry["bloco_posicao"], c.telemetry["bloco_posicao"]
        )
        self.assertEqual(b.telemetry["bloco_versao"], c.telemetry["bloco_versao"])

    def test_recibo_identico(self) -> None:
        b, c = self._dois()
        self.assertEqual(b.telemetry["recibo"], c.telemetry["recibo"])
        linha_b = [l for l in b.bloco.splitlines() if l.startswith("Recibo:")]
        linha_c = [l for l in c.bloco.splitlines() if l.startswith("Recibo:")]
        self.assertEqual(linha_b, linha_c)
        self.assertTrue(linha_b)

    def test_so_o_corpo_difere_e_so_com_llm_rescue(self) -> None:
        b, c = self._dois()
        self.assertNotEqual(b.bloco, c.bloco)
        self.assertFalse(b.telemetry["llm_rescue"])
        self.assertTrue(c.telemetry["llm_rescue"])
        self.assertTrue(c.telemetry["llm_rescue_aplicado"])
        self.assertLess(
            c.telemetry["llm_rescue_tokens_depois"],
            c.telemetry["llm_rescue_tokens_antes"],
        )

    def test_mesmas_flags_de_mecanismo(self) -> None:
        b, c = self._dois()
        self.assertEqual(
            (b.flags.capture, b.flags.gate, b.flags.project, b.flags.serve),
            (c.flags.capture, c.flags.gate, c.flags.project, c.flags.serve),
        )
        self.assertNotEqual(b.flags.llm_rescue, c.flags.llm_rescue)

    def test_simbolo_ancorado_sobrevive_ao_resgate(self) -> None:
        b, c = self._dois()
        self.assertTrue(simbolos_ancorados(b.bloco))
        self.assertEqual(
            c.telemetry["llm_rescue_recall_de_simbolo"]["perdidos"], []
        )


class TestAproveitamentoDoBloco(unittest.TestCase):
    """P-3 / P9 medido com provedor falso. Descritivo, nunca desfecho."""

    def test_sai_por_condicao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            b = _rodar(_semear(raiz / "b"), "B")
            c = _rodar(_semear(raiz / "c"), "C")
        for resultado in (b, c):
            tel = resultado.telemetry["aproveitamento_do_bloco"]
            self.assertEqual(tel["servidas"], 2)
            self.assertGreaterEqual(tel["razao"], 0.0)
            self.assertLessEqual(tel["razao"], 1.0)
        self.assertIn("cobertura_de_captura", b.telemetry)
        self.assertIn("latencia_de_captura", b.telemetry)


class TestManifestoDaExecucao(unittest.TestCase):
    def test_c_grava_o_bloco_servido(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            c = _rodar(_semear(Path(tmp)), "C")
            entry = manifest_da_execucao(c.flags, c.telemetry)
        self.assertEqual(entry["execucao"]["llm_rescue_bloco_servido"], c.bloco)
        self.assertTrue(entry["flags"]["project"])
        self.assertTrue(entry["catalogo_tem_record_intent"])
        self.assertEqual(entry["config_sha256"], config_hashes())


class TestV4ComV5(unittest.TestCase):
    """P-4: fechar a V4 cortando tudo é trivial; a V5 é o que impede."""

    def _relato(self, hashes):
        return {"config_sha256": hashes, "tokens": 700}

    def test_v4_sem_v5_e_recusado(self) -> None:
        with self.assertRaises(RelatoIncoerente):
            conferir_v4_v5(self._relato(config_hashes()), None)

    def test_v4_e_v5_sobre_yaml_diferentes_sao_recusados(self) -> None:
        outro = dict(config_hashes())
        outro["projection.yaml"] = "0" * 64
        with self.assertRaises(RelatoIncoerente) as ctx:
            conferir_v4_v5(self._relato(config_hashes()), self._relato(outro))
        self.assertIn("projection.yaml", str(ctx.exception))

    def test_mesmo_sha256_passa(self) -> None:
        hashes = config_hashes()
        conferir_v4_v5(self._relato(hashes), self._relato(hashes))

    def test_relato_sem_hash_nao_e_auditavel(self) -> None:
        with self.assertRaises(RelatoIncoerente):
            conferir_v4_v5({"tokens": 1}, {"tokens": 1})


if __name__ == "__main__":
    unittest.main()
