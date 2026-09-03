import unittest

from tau_intent.collect import collect_events, regions_from_diff
from tau_intent.tools import ORIGIN_SHA, catalog, record_intent, tool_specs


class TestCollect(unittest.TestCase):
    DIFF = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,1 +1,4 @@\n"
        "+def f():\n"
        "+    return 1\n"
    )

    def test_regions_come_from_git_diff(self):
        regions = regions_from_diff(self.DIFF)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].path, "src/mod.py")
        self.assertEqual(regions[0].line_start, 1)

    def test_path_not_file_path(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "write",
                "args": {"file_path": "src/mod.py", "content": "x"},
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertTrue(any(p.unparseable for p in pendentes.values()))

    def test_edit_takes_oldtext_newtext(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "edit",
                "args": {
                    "path": "src/mod.py",
                    "edits": [{"oldText": "a", "newText": "b"}],
                },
            },
            {
                "tool_name": "record_intent",
                "args": {
                    "file": "src/mod.py",
                    "why": "expõe f",
                    "property": "f retorna int",
                    "domain": "demo",
                },
            },
        ]
        pendentes = collect_events(events, regions)
        pending = next(iter(pendentes.values()))
        self.assertFalse(pending.unparseable)
        self.assertEqual(pending.why, "expõe f")
        self.assertEqual(pending.property, "f retorna int")

    def test_v6_raw_arguments_is_unparseable(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "write",
                "args": {"path": "src/mod.py", "content": "x"},
                "_raw_arguments": "{not json",
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertTrue(next(iter(pendentes.values())).unparseable)

    def test_bash_redirect_attaches_to_region(self):
        regions = regions_from_diff(self.DIFF)
        events = [
            {
                "tool_name": "bash",
                "args": {"command": "echo hi > src/mod.py", "description": "Writing file"},
            }
        ]
        pendentes = collect_events(events, regions)
        self.assertIn("src/mod.py", {p.region.path for p in pendentes.values()})


class TestTools(unittest.TestCase):
    def test_record_intent_typed(self):
        import asyncio

        result = asyncio.run(
            record_intent("src/a.py", "f", "why", "prop", "domain")
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["anchor"], "src/a.py::f")

    def test_origin_sha_in_copied_schemas(self):
        specs = {spec["name"]: spec for spec in tool_specs(capture=True)}
        for name in ("read", "write", "edit", "bash"):
            self.assertIn(ORIGIN_SHA, specs[name]["description"])
        self.assertIn("path", specs["write"]["parameters"]["properties"])
        self.assertNotIn("file_path", specs["write"]["parameters"]["properties"])
        self.assertEqual(
            set(specs["edit"]["parameters"]["properties"]["edits"]["items"]["properties"]),
            {"oldText", "newText"},
        )

    def test_catalog_record_intent_only_when_capture(self):
        names_a = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=False)]
        names_b = [t["name"] if isinstance(t, dict) else t.name for t in catalog(capture=True)]
        self.assertNotIn("record_intent", names_a)
        self.assertIn("record_intent", names_b)


class TestEvidenciaEstrutural(unittest.TestCase):
    """G-2/G-3: what the collector used to compute and throw away."""

    MULTI_HUNK = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,2 +1,3 @@\n"
        " import os\n"
        "+def f():\n"
        "+    return 1\n"
        "@@ -20,2 +30,3 @@\n"
        " x = 1\n"
        "-y = 2\n"
        "+y = 3\n"
    )

    def test_v6_separado_de_v1_na_fixture(self):
        """A refused schema is NAO_PARSEAVEL evidence, not a missing intent."""
        from tau_intent.gate import GateConfig, portao

        regions = regions_from_diff(TestCollect.DIFF)
        events = [{"tool_name": "write", "args": {"file_path": "src/mod.py", "content": "x"}}]
        pendentes = collect_events(events, regions)
        self.assertTrue(all(p.unparseable for p in pendentes.values()))
        codes = [f.code for f in portao(regions, pendentes, set(), GateConfig(), 0).falhas]
        self.assertEqual(codes, ["NAO_PARSEAVEL"])

        limpo = regions_from_diff(TestCollect.DIFF)
        vazio = collect_events([], limpo)
        codes = [f.code for f in portao(limpo, vazio, set(), GateConfig(), 0).falhas]
        self.assertEqual(codes, ["AUSENTE"])

    def test_ancora_ambigua_com_fixture_multi_hunk(self):
        """Two hunks of the same file without distinct AST symbols are one identity."""
        from tau_intent.gate import GateConfig, portao

        regions = regions_from_diff(self.MULTI_HUNK)
        self.assertEqual(len(regions), 2)
        events = [
            {"tool_name": "edit", "args": {
                "path": "src/mod.py", "edits": [{"oldText": "y = 2", "newText": "y = 3"}]}},
            {"tool_name": "record_intent", "args": {
                "file": "src/mod.py", "why": "duas hunks da mesma função",
                "property": "f retorna int", "domain": "demo", "symbol": "f"}},
        ]
        pendentes = collect_events(events, regions)
        self.assertTrue(all(p.claimed_regions == 2 for p in pendentes.values()))
        codes = {f.code for f in portao(regions, pendentes, {"src/mod.py::f"}, GateConfig(), 0).falhas}
        self.assertNotIn("ANCORA_AMBIGUA", codes)

    def test_files_atravessa_arquivos(self):
        from tau_intent.gate import GateConfig, portao

        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n+++ b/src/a.py\n"
            "@@ -1,1 +1,2 @@\n x\n+a\n"
            "diff --git a/src/b.py b/src/b.py\n"
            "--- a/src/b.py\n+++ b/src/b.py\n"
            "@@ -1,1 +1,2 @@\n y\n+b\n"
        )
        regions = regions_from_diff(diff)
        self.assertEqual({r.path for r in regions}, {"src/a.py", "src/b.py"})
        events = [{"tool_name": "record_intent", "args": {
            "files": ["src/a.py", "src/b.py"],
            "why": "uma decisão, dois arquivos",
            "property": "ambos expõem o recorte",
            "domain": "demo",
            "symbol": "f",
        }}]
        pendentes = collect_events(events, regions)
        self.assertEqual({p.region.path for p in pendentes.values()}, {"src/a.py", "src/b.py"})
        codes = {f.code for f in portao(
            regions, pendentes, {"src/a.py::f", "src/b.py::f"}, GateConfig(), 0
        ).falhas}
        self.assertNotIn("ANCORA_AMBIGUA", codes)
        self.assertNotIn("AUSENTE", codes)

    def test_dominio_ausente_e_dado_do_coletor(self):
        from tau_intent.gate import GateConfig, portao

        regions = regions_from_diff(TestCollect.DIFF)
        events = [
            {"tool_name": "write", "args": {"path": "src/mod.py", "content": "x"}},
            {"tool_name": "record_intent", "args": {
                "file": "src/mod.py", "why": "expõe f", "property": "f retorna int"}},
        ]
        pendentes = collect_events(events, regions)
        self.assertEqual(next(iter(pendentes.values())).domain, "")
        codes = [f.code for f in portao(regions, pendentes, set(), GateConfig(), 0).falhas]
        self.assertIn("DOMINIO_AUSENTE", codes)

    def test_edited_lines_conta_linhas_e_nao_o_hunk(self):
        regions = regions_from_diff(self.MULTI_HUNK)
        primeiro, segundo = regions
        self.assertEqual(primeiro.size, 3)
        self.assertEqual(primeiro.edited_lines, 2)
        self.assertEqual(segundo.edited_lines, 2)

    def test_symbol_declarado_nao_e_preenchido_pelo_coletor(self):
        """SIMBOLO_NAO_RESOLVIDO has to be falsifiable (D2)."""
        regions = regions_from_diff(TestCollect.DIFF)
        events = [{"tool_name": "record_intent", "args": {
            "file": "src/mod.py", "why": "expõe f", "domain": "demo"}}]
        pendentes = collect_events(events, regions)
        self.assertEqual(next(iter(pendentes.values())).symbol, "")

    def test_latencia_de_captura_tem_os_ordinais(self):
        regions = regions_from_diff(TestCollect.DIFF)
        events = [
            {"tool_name": "write", "args": {"path": "src/mod.py", "content": "x"}},
            {"tool_name": "read", "args": {"path": "src/mod.py"}},
            {"tool_name": "record_intent", "args": {
                "file": "src/mod.py", "why": "w", "domain": "d"}},
        ]
        pending = next(iter(collect_events(events, regions).values()))
        self.assertEqual(pending.write_turn, 0)
        self.assertEqual(pending.intent_turn, 2)


class TestAncoraSobreviveAoReformat(unittest.TestCase):
    """G-3: the anchor is (file, symbol); the line range is evidence only."""

    ANTES = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
    DEPOIS = "\n\n\n\ndef f():\n\n    return 1\n\n\n\n\ndef g():\n    return 2\n"

    def _symbol(self, source, start, end, tmp):
        from tau_intent.collect import Region, resolver_simbolos

        (tmp / "m.py").write_text(source, encoding="utf-8")
        region = Region(path="m.py", line_start=start, line_end=end)
        resolver_simbolos([region], tmp)
        return region.symbol

    def test_reformatar_nao_muda_o_symbol(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            antes = self._symbol(self.ANTES, 2, 2, root)
            depois = self._symbol(self.DEPOIS, 7, 7, root)
            self.assertEqual(antes, "f")
            self.assertEqual(depois, antes)

    def test_node_id_da_regiao_usa_o_symbol(self):
        import tempfile
        from pathlib import Path

        from tau_intent.collect import Region, resolver_simbolos, simbolos_do_ast

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text(self.ANTES, encoding="utf-8")
            region = Region(path="m.py", line_start=5, line_end=6)
            resolver_simbolos([region], root)
            self.assertEqual(region.node_id(), "m.py::g")
            self.assertEqual(simbolos_do_ast([region], root), {"m.py::f", "m.py::g"})

    def test_tabela_de_simbolos_nao_vem_do_texto_de_property(self):
        """The known set is the AST's, so the gate can actually fail (D2)."""
        import tempfile
        from pathlib import Path

        from tau_intent.collect import Region, simbolos_do_ast

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text(self.ANTES, encoding="utf-8")
            conhecidos = simbolos_do_ast([Region(path="m.py", line_start=1, line_end=1)], root)
            self.assertNotIn("m.py::NaoExiste", conhecidos)



if __name__ == "__main__":
    unittest.main()
