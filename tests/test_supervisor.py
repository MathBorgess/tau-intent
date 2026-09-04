"""Supervisor: arms (D1), anchors (D3), montar (H10), AST symbols (D2)."""

from __future__ import annotations

import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path

from tau_intent.cli import flags_from_args
from tau_intent.collect import Region
from tau_intent.config import BlocoConfig
from tau_intent.fake_provider import FakeHarness, passing_script
from tau_intent.supervisor import Flags, ancoras_da_tarefa, montar, run_task

DIFF = (
    "diff --git a/src/mod.py b/src/mod.py\n"
    "--- a/src/mod.py\n"
    "+++ b/src/mod.py\n"
    "@@ -1,0 +1,2 @@\n"
    "+def f():\n"
    "+    return 1\n"
)


def _workspace(root: Path) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return root


class TestBracosH16(unittest.TestCase):
    def test_b_e_c_projetam_e_so_llm_rescue_difere(self) -> None:
        b = flags_from_args(["--arm", "B"])
        c = flags_from_args(["--arm", "C"])
        self.assertTrue(b.project and b.serve and b.capture and b.gate)
        self.assertTrue(c.project and c.serve and c.capture and c.gate)
        self.assertFalse(b.llm_rescue)
        self.assertTrue(c.llm_rescue)
        self.assertEqual(
            (b.capture, b.gate, b.project, b.serve),
            (c.capture, c.gate, c.project, c.serve),
        )

    def test_braco_a_nao_serve_e_nao_captura(self) -> None:
        a = flags_from_args(["--arm", "A"])
        self.assertEqual((a.capture, a.gate, a.project, a.serve, a.llm_rescue),
                         (False, False, False, False, False))

    def test_render_tudo_saiu_dos_bracos(self) -> None:
        """D1: the supervisor no longer serves the whole current store.

        Checked on the AST — the module docstring explains the removal and must
        not be able to fake the assertion."""
        import ast

        import tau_intent.supervisor as sup

        self.assertFalse(hasattr(sup, "render_tudo"))
        tree = ast.parse(inspect.getsource(sup))
        nomes = {
            node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        self.assertNotIn("render_tudo", nomes)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("render_tudo", {a.name for a in node.names})

    def test_serve_sem_projetar_nao_ressuscita_o_desenho_revogado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_task(
                    Path(tmp),
                    Flags(capture=True, gate=False, project=False, serve=True),
                    harness=FakeHarness(passing_script(), max_turns=None),
                    diff=DIFF,
                )
            )
        self.assertTrue(result.telemetry["serve_sem_projecao"])
        self.assertEqual(result.bloco, "")


class TestMontar(unittest.TestCase):
    """H10: the position of the block is declared, not accidental."""

    def test_bloco_adjacente_ao_enunciado_na_primeira_mensagem(self) -> None:
        texto = montar("base", "faça a tarefa", "<bloco/>")
        self.assertTrue(texto.startswith("base\n\nfaça a tarefa"))
        self.assertTrue(texto.endswith("<bloco/>"))

    def test_posicao_vem_do_yaml(self) -> None:
        antes = BlocoConfig(posicao="primeira_mensagem_usuario_antes_do_enunciado")
        texto = montar("", "faça a tarefa", "<bloco/>", antes)
        self.assertTrue(texto.startswith("<bloco/>"))

    def test_posicao_desconhecida_falha_alto(self) -> None:
        with self.assertRaises(ValueError):
            montar("", "t", "<bloco/>", BlocoConfig(posicao="system_prompt"))

    def test_sem_bloco_o_prompt_nao_muda(self) -> None:
        self.assertEqual(montar("", "faça a tarefa", ""), "faça a tarefa")


class TestAncorasDaTarefa(unittest.TestCase):
    """D3: anchors used to be the workspace path, which is not a graph node."""

    def test_ancoras_vem_das_regioes_simbolo_primeiro(self) -> None:
        regions = [Region(path="m.py", line_start=1, line_end=3, symbol="f")]
        self.assertEqual(ancoras_da_tarefa(regions), ["m.py::f", "m.py"])

    def test_explicitas_ganham(self) -> None:
        regions = [Region(path="m.py", line_start=1, line_end=3, symbol="f")]
        self.assertEqual(ancoras_da_tarefa(regions, explicitas=["x.py"]), ["x.py"])

    def test_sem_regioes_cai_no_enunciado(self) -> None:
        class _G:
            nodes = {"m.py": {}, "outro.py": {}}

        self.assertEqual(ancoras_da_tarefa([], _G(), "edite m.py agora"), ["m.py"])

    def test_sem_nada_e_lista_vazia_nao_um_caminho_de_workspace(self) -> None:
        self.assertEqual(ancoras_da_tarefa([], None, ""), [])

    def test_ancora_nunca_e_o_caminho_do_workspace(self) -> None:
        """The old code passed [str(workspace)] — a path, never a graph node."""
        import tempfile

        regions = [Region(path="src/mod.py", line_start=1, line_end=3, symbol="f")]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn(tmp, ancoras_da_tarefa(regions))
            self.assertNotIn(tmp, ancoras_da_tarefa([], None, tmp))


class TestSimbolosDoAst(unittest.TestCase):
    """D2: the known set no longer comes from the property texts themselves."""

    def test_symbols_from_pending_nao_existe_mais(self) -> None:
        import ast

        import tau_intent.supervisor as sup

        self.assertFalse(hasattr(sup, "_symbols_from_pending"))
        tree = ast.parse(inspect.getsource(sup))
        definidos = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertNotIn("_symbols_from_pending", definidos)

    def test_portao_recebe_a_tabela_do_ast(self) -> None:
        vistos: list[set] = []

        def espiao(regions, pendentes, symbols, cfg, bloqueios):
            from tau_intent.gate import Veredito

            vistos.append(set(symbols))
            return Veredito.passa()

        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(Path(tmp))
            asyncio.run(
                run_task(
                    root,
                    Flags(capture=True, gate=True, project=False, serve=False),
                    harness=FakeHarness(passing_script(), max_turns=None),
                    diff=DIFF,
                    gate_fn=espiao,
                )
            )
        self.assertEqual(vistos, [{"src/mod.py::f"}])


class TestAncoraGravada(unittest.TestCase):
    def test_symbol_e_blob_sha_reais_no_store(self) -> None:
        """§5.3: while blob_sha was "0"*40 no anchor was verifiable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(Path(tmp))
            result = asyncio.run(
                run_task(
                    root,
                    flags_from_args(["--arm", "B"]),
                    harness=FakeHarness(passing_script(), max_turns=None),
                    diff=DIFF,
                )
            )
            from tau_intent.store import IntentStore

            entries = IntentStore(root).current()
        self.assertTrue(entries)
        anchor = entries[0].anchor
        self.assertEqual(anchor.symbol, "f")
        self.assertNotEqual(anchor.blob_sha, "0" * 40)
        self.assertEqual(len(anchor.blob_sha), 40)
        self.assertEqual(result.verdict, "PASSA")

    def test_flush_ancora_pelo_symbol_da_regiao_nao_pelo_declarado(self) -> None:
        """Store identity is the hunk's AST. Declared symbol is gate-only."""
        from tau_intent.collect import Pending
        from tau_intent.store import IntentStore
        from tau_intent.supervisor import _flush_pendentes

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text(
                "def f():\n    return 1\n\ndef g():\n    return 2\n",
                encoding="utf-8",
            )
            region = Region(
                path="src/a.py", line_start=4, line_end=5, symbol="g"
            )
            pending = Pending(
                region=region,
                why="feat: recorte com helper",
                property="g é puro",
                domain="demo",
                symbol="f",
            )
            store = IntentStore(root)
            _flush_pendentes(store, {region.key(): pending}, "t1", root)
            entries = store.current()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].anchor.symbol, "g")
        self.assertEqual(entries[0].why, "feat: recorte com helper")

    def test_flush_mesmo_why_property_diferente_sao_duas_linhas(self) -> None:
        from tau_intent.collect import Pending
        from tau_intent.store import IntentStore
        from tau_intent.supervisor import _flush_pendentes

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text(
                "def f():\n    return 1\n\ndef g():\n    return 2\n",
                encoding="utf-8",
            )
            rf = Region(path="src/a.py", line_start=1, line_end=2, symbol="f")
            rg = Region(path="src/a.py", line_start=4, line_end=5, symbol="g")
            why = "feat: recorte com helper"
            pendentes = {
                rf.key(): Pending(
                    region=rf, why=why, property="f retorna int", domain="demo"
                ),
                rg.key(): Pending(
                    region=rg, why=why, property="g é puro", domain="demo"
                ),
            }
            store = IntentStore(root)
            _flush_pendentes(store, pendentes, "t1", root)
            entries = store.current()
        self.assertEqual(len(entries), 2)
        por_simbolo = {e.anchor.symbol: e for e in entries}
        self.assertEqual(por_simbolo["f"].why, por_simbolo["g"].why)
        self.assertEqual(por_simbolo["f"].property, "f retorna int")
        self.assertEqual(por_simbolo["g"].property, "g é puro")


class TestSupervisorCompat(unittest.TestCase):
    def test_run_task_arm_a_no_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(Path(tmp))
            result = asyncio.run(
                run_task(
                    root,
                    flags_from_args(["--arm", "A", "--fake-provider"]),
                    max_productive_turns=2,
                    diff=DIFF,
                )
            )
            self.assertFalse((root / "intents.jsonl").exists())
            self.assertEqual(result.verdict, "PASSA")

    def test_andaime_de_merge_removido(self) -> None:
        """§5.2: a silent second implementation of the gate and the collector."""
        import tau_intent

        raiz = Path(tau_intent.__file__).parent
        self.assertFalse((raiz / "_slice4_fallbacks.py").exists())
        self.assertFalse((raiz / "_pr4_local.py").exists())

    def test_laco_le_o_yaml_do_portao(self) -> None:
        """G-0: the hashed file is what run_task decides with, not GateConfig()."""
        import tau_intent.supervisor as sup

        self.assertIn("load_gate_config", inspect.getsource(sup.run_task))


if __name__ == "__main__":
    unittest.main()
