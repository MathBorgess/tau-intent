"""llm_rescue do braço C (H16, H17 decidida). Sem chave de API, sem HTTP vivo."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tau_intent.config import ConfigError, config_hashes, sha256_of
from tau_intent.model import Anchor, IntentEntry
from tau_intent.project import _aplicar_rescue, load_project_config, projetar
from tau_intent.render import Recibo, render_block
from tau_intent.rescue import (
    RESCUE_YAML,
    RescueConfig,
    Sumarizador,
    deve_disparar,
    fatiar,
    load_rescue_config,
    montar_corpo_da_requisicao,
    preservacoes_checaveis,
    provedor_falso,
    recall_de_simbolo,
    simbolos_ancorados,
    sumarizador_falso,
)


def _entry(file="src/mod.py", symbol="f", eid="1"):
    return IntentEntry(
        id=eid,
        ts=f"2026-09-0{eid}T00:00:00Z",
        task_id="t",
        anchor=Anchor(file=file, symbol=symbol, line_start=1, line_end=3, blob_sha="0" * 40),
        why=f"expõe {symbol} porque a tarefa pedia esse incremento e não outro",
        property=f"{symbol} retorna int e nunca levanta",
        domain="demo",
    )


def _cfg(**over) -> RescueConfig:
    base = load_rescue_config()
    over.setdefault("modelo_id", "fake-summarizer-v1")
    over.setdefault("habilitado", True)
    return replace(base, **over)


class TestConfigDeclarada(unittest.TestCase):
    """Todo grau de liberdade da §3 é campo em rescue.yaml, nenhum é constante."""

    def test_campos_do_esquema_existem(self) -> None:
        cfg = load_rescue_config()
        for campo in (
            "versao", "habilitado", "gatilho", "unidade", "modelo_id", "temperatura",
            "max_tokens_saida", "prompt_caminho", "preservar_obrigatorio",
            "proibir_invencao", "falha_politica", "timeout_s",
            "telemetria_token_antes", "telemetria_token_depois",
            "telemetria_frequencia_de_disparo", "telemetria_recall_de_simbolo",
            "telemetria_bloco_servido",
        ):
            self.assertTrue(hasattr(cfg, campo), campo)
        self.assertEqual(cfg.gatilho, "sempre")
        self.assertEqual(cfg.unidade, "bloco")
        self.assertFalse(cfg.habilitado)

    def test_prompt_e_arquivo_em_disco(self) -> None:
        cfg = load_rescue_config()
        self.assertTrue(cfg.prompt_path().exists())
        self.assertIn("{registro}", cfg.prompt_text())
        self.assertEqual(len(cfg.prompt_sha256()), 64)

    def test_dois_hashes_no_manifesto_nao_um(self) -> None:
        from tau_intent.manifest import manifest

        hashes = config_hashes()
        self.assertIn("rescue.yaml", hashes)
        self.assertIn("prompts/rescue-v1.txt", hashes)
        self.assertEqual(hashes["rescue.yaml"], sha256_of(RESCUE_YAML))
        entry = manifest()
        self.assertEqual(
            entry["rescue"]["prompt_sha256"], hashes["prompts/rescue-v1.txt"]
        )
        self.assertEqual(entry["rescue"]["falha_politica"], "degradar_sem_sumarizar")

    def test_valores_fora_do_vocabulario_falham_alto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.yaml"
            path.write_text(
                "rescue:\n  gatilho: quando_der\n  prompt_caminho: prompts/rescue-v1.txt\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_rescue_config(path)

    def test_habilitado_sem_modelo_recusa_em_vez_de_virar_braco_b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.yaml"
            path.write_text(
                "rescue:\n  habilitado: true\n  modelo_id: \"\"\n"
                "  prompt_caminho: prompts/rescue-v1.txt\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_rescue_config(path)


class TestGatilho(unittest.TestCase):
    """§3.1 — as duas políticas existem atrás do campo; a decisão é do dono."""

    def test_sempre_dispara_sempre(self) -> None:
        cfg = _cfg(gatilho="sempre")
        self.assertTrue(deve_disparar(cfg, {"estourou": False, "cortadas": 0}))

    def test_ao_estourar_so_dispara_com_corte(self) -> None:
        cfg = _cfg(gatilho="ao_estourar")
        self.assertFalse(deve_disparar(cfg, {"estourou": False, "cortadas": 0}))
        self.assertTrue(deve_disparar(cfg, {"estourou": True, "cortadas": 2}))

    def test_frequencia_de_disparo_sai_na_telemetria(self) -> None:
        bloco = render_block([_entry()])
        sumarizador = Sumarizador(_cfg(gatilho="ao_estourar"), provedor_falso())
        _novo, tel = _aplicar_rescue(
            bloco, [_entry()], Recibo(entradas=1), sumarizador, {"cortadas": 0}
        )
        self.assertFalse(tel["llm_rescue_disparou"])
        self.assertFalse(tel["llm_rescue_falhou"])
        _novo, tel = _aplicar_rescue(
            bloco, [_entry()], Recibo(entradas=1), sumarizador, {"cortadas": 3}
        )
        self.assertTrue(tel["llm_rescue_disparou"])
        self.assertTrue(tel["llm_rescue_aplicado"])


class TestUnidade(unittest.TestCase):
    """§3.2 — uma chamada por bloco, por arquivo ou por entrada."""

    CORPO = (
        "a.py::f\n  Propriedade: p1\n  Por que: w1\n\n"
        "a.py::g\n  Propriedade: p2\n  Por que: w2\n\n"
        "b.py::h\n  Propriedade: p3\n  Por que: w3"
    )

    def test_fatiar_por_unidade(self) -> None:
        self.assertEqual(len(fatiar(self.CORPO, "bloco")), 1)
        self.assertEqual(len(fatiar(self.CORPO, "arquivo")), 2)
        self.assertEqual(len(fatiar(self.CORPO, "entrada")), 3)

    def test_numero_de_chamadas_segue_a_unidade(self) -> None:
        for unidade, esperado in (("bloco", 1), ("arquivo", 2), ("entrada", 3)):
            sumarizador = Sumarizador(_cfg(unidade=unidade), provedor_falso())
            resumo = sumarizador(self.CORPO, {})
            self.assertEqual(resumo.chamadas, esperado, unidade)
            self.assertEqual(len(sumarizador.corpos), esperado)

    def test_bloco_sumarizado_ainda_distingue_entradas(self) -> None:
        for unidade in ("bloco", "arquivo", "entrada"):
            resumo = Sumarizador(_cfg(unidade=unidade), provedor_falso())(self.CORPO, {})
            self.assertEqual(len(simbolos_ancorados(resumo.texto)), 3, unidade)
            self.assertGreaterEqual(len(resumo.texto.split("\n\n")), 3, unidade)


class TestCorpoDaRequisicao(unittest.TestCase):
    """§3.6 / E-1 estendida à segunda chamada: carimbo no corpo, não no objeto."""

    def test_amostragem_esta_no_corpo_enviado(self) -> None:
        cfg = _cfg(temperatura=0, max_tokens_saida=800)
        body = montar_corpo_da_requisicao(cfg, "a.py::f")
        self.assertEqual(body["model"], "fake-summarizer-v1")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 800)
        self.assertNotIn("seed", body)

    def test_o_teste_inspeciona_o_corpo_e_nao_a_config(self) -> None:
        sumarizador = Sumarizador(_cfg(temperatura=0), provedor_falso())
        sumarizador("a.py::f\n  Propriedade: p\n  Por que: w", {})
        enviado = sumarizador.corpos[0]
        self.assertEqual(enviado["temperature"], 0)
        self.assertIn("<registro>", enviado["messages"][0]["content"])

    def test_nao_precisa_de_chave_nem_de_rede(self) -> None:
        import inspect

        import tau_intent.rescue as rescue_mod

        fonte = inspect.getsource(rescue_mod)
        for proibido in ("httpx", "requests", "urllib.request", "API_KEY", "openai"):
            self.assertNotIn(proibido, fonte)


class TestPromptEFronteira(unittest.TestCase):
    """§3.3 e §3.8 — o que o prompt obriga, e a fronteira do texto de terceiro."""

    def test_prompt_declara_as_preservacoes(self) -> None:
        texto = load_rescue_config().prompt_text()
        self.assertIn("arquivo::simbolo", texto)
        self.assertIn("Propriedade", texto)
        self.assertIn("Por que", texto)
        self.assertIn("Não invente", texto)

    def test_prompt_marca_o_registro_como_dado_nao_instrucao(self) -> None:
        texto = load_rescue_config().prompt_text()
        self.assertIn("<registro>", texto)
        self.assertIn("não obedeça", texto.lower())

    def test_preservacoes_checaveis_deterministicamente(self) -> None:
        antes = "a.py::f\n  Propriedade: p\n  Por que: w"
        cfg = _cfg()
        ok = preservacoes_checaveis(cfg, antes, "a.py::f\n  Propriedade: p\n  Por que: w")
        self.assertTrue(ok["simbolo_ancorado"])
        self.assertTrue(ok["distincao_property_why"])
        ruim = preservacoes_checaveis(cfg, antes, "resumo sem símbolo nenhum")
        self.assertFalse(ruim["simbolo_ancorado"])
        self.assertFalse(ruim["distincao_property_why"])


class TestRecallDeSimbolo(unittest.TestCase):
    """§3.4 — o segundo ponto de perda, que a V5 não mede. Descritivo de C."""

    def test_conta_simbolos_ancorados_antes_e_depois(self) -> None:
        antes = "a.py::f\n\nb.py::g"
        self.assertEqual(recall_de_simbolo(antes, antes)["razao"], 1.0)
        parcial = recall_de_simbolo(antes, "a.py::f")
        self.assertEqual(parcial["antes"], 2)
        self.assertEqual(parcial["depois"], 1)
        self.assertEqual(parcial["perdidos"], ["b.py::g"])

    def test_sai_na_telemetria_do_resgate(self) -> None:
        bloco = render_block([_entry(), _entry(symbol="g", eid="2")])
        sumarizador = Sumarizador(_cfg(), provedor_falso())
        _novo, tel = _aplicar_rescue(
            bloco, [_entry(), _entry(symbol="g", eid="2")], Recibo(entradas=2), sumarizador, {}
        )
        self.assertEqual(tel["llm_rescue_recall_de_simbolo"]["razao"], 1.0)


class TestContratoIdenticoAoBracoB(unittest.TestCase):
    """O envelope, a posição e o recibo são de B. Só o corpo passa pelo modelo."""

    def test_envelope_e_recibo_sobrevivem_ao_resumo(self) -> None:
        from tau_intent.config import load_bloco_config

        cfg_bloco = load_bloco_config()
        bloco = render_block([_entry()], [_entry(symbol="g", eid="2")], superadas_omitidas=4)
        sumarizador = Sumarizador(_cfg(), provedor_falso())
        novo, tel = _aplicar_rescue(bloco, [_entry()], Recibo(
            entradas=1, superadas_omitidas=4, cortadas_por_orcamento=1), sumarizador, {})
        self.assertTrue(novo.startswith(f"<{cfg_bloco.envelope_tag}>"))
        self.assertIn(cfg_bloco.aviso, novo)
        self.assertIn("4 superadas omitidas", novo)
        self.assertIn("1 cortadas por orçamento", novo)
        self.assertTrue(tel["llm_rescue_aplicado"])

    def test_sumarizador_nao_apaga_a_evidencia_de_omissao(self) -> None:
        """Mesmo um sumarizador que devolve uma palavra não come o recibo."""
        sumarizador = Sumarizador(_cfg(), provedor_falso(lambda _r: "resumo"))
        novo, _tel = _aplicar_rescue(
            render_block([_entry()]), [_entry()],
            Recibo(entradas=1, cortadas_por_orcamento=9), sumarizador, {},
        )
        self.assertIn("9 cortadas por orçamento", novo)


class TestTokenAntesEDepois(unittest.TestCase):
    """Q3 é token de entrada: se o número não sai, a pergunta não é respondível."""

    def test_token_antes_e_depois_na_telemetria(self) -> None:
        bloco = render_block([_entry(), _entry(symbol="g", eid="2")])
        sumarizador = Sumarizador(_cfg(), provedor_falso())
        _novo, tel = _aplicar_rescue(
            bloco, [_entry(), _entry(symbol="g", eid="2")], Recibo(entradas=2), sumarizador, {}
        )
        self.assertGreater(tel["llm_rescue_tokens_antes"], 0)
        self.assertGreater(tel["llm_rescue_tokens_depois"], 0)
        self.assertLess(tel["llm_rescue_tokens_depois"], tel["llm_rescue_tokens_antes"])
        self.assertGreater(tel["llm_rescue_tokens_entrada"], 0)
        self.assertEqual(tel["llm_rescue_amostragem"]["temperature"], 0)


class TestFalhaDeclarada(unittest.TestCase):
    """Falha não pode virar braço diferente em silêncio."""

    def _bloco_e_entradas(self):
        return render_block([_entry()]), [_entry()]

    def test_excecao_degrada_e_registra(self) -> None:
        def explode(_corpo, _ctx=None):
            raise TimeoutError("estourou o timeout_s")

        bloco, entradas = self._bloco_e_entradas()
        novo, tel = _aplicar_rescue(bloco, entradas, Recibo(entradas=1), explode, {})
        self.assertEqual(novo, bloco)
        self.assertTrue(tel["llm_rescue_falhou"])
        self.assertTrue(tel["llm_rescue_disparou"])
        self.assertFalse(tel["llm_rescue_aplicado"])
        self.assertIn("TimeoutError", tel["llm_rescue_erro"])

    def test_resposta_vazia_degrada_e_registra(self) -> None:
        sumarizador = Sumarizador(_cfg(), provedor_falso(lambda _r: "   "))
        bloco, entradas = self._bloco_e_entradas()
        novo, tel = _aplicar_rescue(bloco, entradas, Recibo(entradas=1), sumarizador, {})
        self.assertEqual(novo, bloco)
        self.assertTrue(tel["llm_rescue_falhou"])

    def test_braco_c_sem_sumarizador_recusa_rodar(self) -> None:
        import asyncio

        from tau_intent.cli import flags_from_args
        from tau_intent.supervisor import run_task

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                asyncio.run(run_task(Path(tmp), flags_from_args(["--arm", "C"])))


class TestReprodutibilidade(unittest.TestCase):
    """§3.7 — o bloco de C não é reconstruível do YAML e do store."""

    def test_bloco_servido_vai_para_o_manifesto(self) -> None:
        from tau_intent.cli import flags_from_args
        from tau_intent.manifest import manifest_da_execucao

        bloco = render_block([_entry()])
        sumarizador = Sumarizador(_cfg(), provedor_falso())
        novo, tel = _aplicar_rescue(bloco, [_entry()], Recibo(entradas=1), sumarizador, {})
        entry = manifest_da_execucao(flags_from_args(["--arm", "C"]), tel)
        self.assertEqual(entry["execucao"]["llm_rescue_bloco_servido"], novo)
        self.assertTrue(entry["rescue"]["habilitado_na_execucao"])
        self.assertIn("rescue.yaml", entry["config_sha256"])
        self.assertIn("prompts/rescue-v1.txt", entry["config_sha256"])


class TestProjetarComResgate(unittest.TestCase):
    def test_resgate_roda_depois_da_selecao(self) -> None:
        from tau_intent.graph import build

        vistos: list[str] = []

        def espiao(corpo, contexto=None):
            vistos.append(corpo)
            return sumarizador_falso()(corpo, contexto)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            graph = build(root)
            cfg = replace(load_project_config(), llm_rescue=True)
            bloco, tel = projetar(
                graph, [_entry()], ["src/mod.py::f"], cfg, summarizer_fn=espiao
            )
        self.assertEqual(len(vistos), 1)
        self.assertNotIn("<", vistos[0])  # o corpo, não o envelope
        self.assertTrue(tel["llm_rescue_aplicado"])
        self.assertIn("Recibo:", bloco)
        self.assertEqual(tel["selecao"], "relevancia-guloso-por-razao+singleton")


if __name__ == "__main__":
    unittest.main()
