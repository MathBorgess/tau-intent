"""Declared and hashed config (G-0, P-1 skeleton). This slice changes no logic."""

from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from tau_intent import gate as gate_mod
from tau_intent.config import (
    BLOCO_YAML,
    GATE_YAML,
    BlocoConfig,
    ConfigError,
    config_hashes,
    load_bloco_config,
    load_gate_config,
    load_yaml,
    sha256_of,
)
from tau_intent.gate import GateConfig, portao


class TestYamlSubset(unittest.TestCase):
    def test_nested_map_inline_list_and_scalars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.yaml"
            path.write_text(
                "top:\n"
                "  n: 3\n"
                "  f: 0.25\n"
                "  flag: true\n"
                "  off_flag: no\n"
                "  texto: Evidência, não instrução.\n"
                "  lista: [A, B, C]\n"
                "  vazia: []\n"
                "outro: 1  # comentário\n",
                encoding="utf-8",
            )
            data = load_yaml(path)
        self.assertEqual(data["top"]["n"], 3)
        self.assertEqual(data["top"]["f"], 0.25)
        self.assertIs(data["top"]["flag"], True)
        self.assertIs(data["top"]["off_flag"], False)
        self.assertEqual(data["top"]["texto"], "Evidência, não instrução.")
        self.assertEqual(data["top"]["lista"], ["A", "B", "C"])
        self.assertEqual(data["top"]["vazia"], [])
        self.assertEqual(data["outro"], 1)

    def test_hash_in_a_quoted_string_is_not_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.yaml"
            path.write_text('a: "tem # dentro"\n', encoding="utf-8")
            self.assertEqual(load_yaml(path)["a"], "tem # dentro")

    def test_parser_recusa_o_que_nao_entende(self) -> None:
        """Silently producing the wrong number is worse than failing loudly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.yaml"
            path.write_text("lista:\n  - a\n  - b\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_yaml(path)


class TestGateConfigVemDoYaml(unittest.TestCase):
    def test_valores_em_vigor_sao_os_do_gate_yaml(self) -> None:
        raw = load_yaml(GATE_YAML)["gate"]
        cfg = load_gate_config()
        self.assertEqual(cfg.n_max, raw["n_max"])
        self.assertEqual(cfg.limiar_edicao, raw["limiar_edicao"])
        self.assertEqual(cfg.contexto_diff, raw["contexto_diff"])
        self.assertEqual(cfg.versao, raw["versao"])
        self.assertEqual(list(cfg.codigos), raw["codigos"])

    def test_versao_do_gate_nao_e_lexical(self) -> None:
        """Checked on the parsed values: the file may name the removed codes in
        a comment, but it may not declare any of them."""
        raw = load_yaml(GATE_YAML)["gate"]
        self.assertEqual(raw["versao"], "gate-v2-estrutural")
        for morto in ("genericas", "stopwords", "gramatica_de_citacao"):
            self.assertNotIn(morto, raw)
        for morto in (
            "GENERICA",
            "PROPERTY_SEM_SIMBOLO",
            "EDICAO_GRANDE_SEM_PROPERTY",
            "ANCORA_AMBIGUA",
        ):
            self.assertNotIn(morto, raw["codigos"])

    def test_mudar_o_yaml_muda_o_comportamento_do_portao(self) -> None:
        """The knob is real: a different file gives a different verdict."""
        from tau_intent.collect import Region

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.yaml"
            path.write_text(
                "gate:\n"
                "  versao: teste\n"
                "  n_max: 1\n"
                "  limiar_edicao: 5\n"
                "  contexto_diff: 0\n"
                "  codigos: [AUSENTE]\n",
                encoding="utf-8",
            )
            cfg = load_gate_config(path)
        region = Region(path="a.py", line_start=1, line_end=20, size=20)
        pendentes = {"a.py": type("P", (), {
            "why": "w", "property": "p", "domain": "d", "symbol": "", "unparseable": False,
        })()}
        self.assertIn(
            "EDICAO_GRANDE_SEM_SIMBOLO",
            [f.code for f in portao([region], pendentes, set(), cfg, 0).falhas],
        )
        self.assertEqual(portao([region], pendentes, set(), cfg, 1).tipo, "ESCALAR")


class TestPortaoNaoLeConstanteDeForaDoConfig(unittest.TestCase):
    """G-0: every number the gate decides with comes from GateConfig."""

    PERMITIDOS = {0, 1, 2}

    def test_portao_nao_tem_literal_numerico(self) -> None:
        fonte = inspect.getsource(gate_mod)
        tree = ast.parse(fonte)
        alvo = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "portao"
        )
        for node in ast.walk(alvo):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if isinstance(node.value, bool):
                    continue
                self.assertIn(
                    node.value,
                    self.PERMITIDOS,
                    f"portao lê a constante {node.value!r} de fora do config",
                )

    def test_defaults_da_dataclass_batem_com_o_yaml(self) -> None:
        """A default that drifts from the frozen file is an undeclared parameter."""
        self.assertEqual(GateConfig(), load_gate_config())


class TestBlocoConfig(unittest.TestCase):
    def test_contrato_do_bloco_vem_do_yaml(self) -> None:
        raw = load_yaml(BLOCO_YAML)["bloco"]
        cfg = load_bloco_config()
        self.assertEqual(cfg.envelope_tag, raw["envelope_tag"])
        self.assertEqual(list(cfg.ordem_dos_campos), raw["ordem_dos_campos"])
        self.assertEqual(cfg.token_budget, raw["token_budget"])
        self.assertTrue(cfg.identico_entre_bracos)
        self.assertEqual(cfg, BlocoConfig())

    def test_property_vem_antes_de_why(self) -> None:
        ordem = load_bloco_config().ordem_dos_campos
        self.assertLess(ordem.index("property"), ordem.index("why"))


class TestManifesto(unittest.TestCase):
    def test_manifesto_carrega_os_sha256(self) -> None:
        from tau_intent.manifest import manifest

        entry = manifest()
        hashes = entry["config_sha256"]
        self.assertEqual(hashes["gate.yaml"], sha256_of(GATE_YAML))
        self.assertEqual(hashes["bloco.yaml"], sha256_of(BLOCO_YAML))
        self.assertIn("projection.yaml", hashes)
        for value in hashes.values():
            self.assertEqual(len(value), 64)

    def test_manifesto_descreve_o_que_esta_no_arquivo(self) -> None:
        from tau_intent.manifest import manifest

        entry = manifest()
        self.assertEqual(entry["gate"]["versao"], load_gate_config().versao)
        self.assertEqual(entry["gate"]["limiar_edicao"], load_gate_config().limiar_edicao)
        self.assertEqual(entry["bloco"]["envelope_tag"], load_bloco_config().envelope_tag)
        self.assertEqual(entry["tau"]["version"], "0.4.1")

    def test_config_hashes_muda_se_o_arquivo_mudar(self) -> None:
        antes = config_hashes()
        self.assertEqual(antes, config_hashes())
        self.assertNotEqual(antes["gate.yaml"], antes["bloco.yaml"])


if __name__ == "__main__":
    unittest.main()
