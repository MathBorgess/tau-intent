"""S3: the code observer sees what the agent created, and says when it cannot look.

P-3: ``git diff HEAD`` ignores untracked files, so an agent that creates a new
module produced an effect nobody observed and ``AUSENTE`` could not fire.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tau_intent.adapters.code import CodeAdapter, EffectObservationError, observe
from tau_intent.cli import flags_from_args
from tau_intent.fake_provider import FakeHarness, FakeToolStart, FakeTurnEnd
from tau_intent.supervisor import git_diff, run_task
from tests.test_real_harness import git, repo

NEW_MODULE = "def g():\n    return 2\n"
INTENT = {
    "file": "pkg/new.py", "symbol": "g",
    "why": "g é o novo incremento: um módulo inteiro que o agente criou nesta tarefa",
    "property": "g retorna int", "domain": "demo",
}


def script(*calls):
    """One scripted turn: the tool starts, then a productive and a final TurnEnd."""
    return [[*calls, FakeTurnEnd(tool_results=[{"tool_name": "write"}]), FakeTurnEnd(tool_results=[])]]


def write_start(path, content=NEW_MODULE):
    return FakeToolStart(tool_name="write", args={"path": path, "content": content})


def intent_start(**args):
    return FakeToolStart(tool_call_id="call-2", tool_name="record_intent", args=args)


def run_b(root, harness, **kwargs):
    flags = flags_from_args(["--arm", "B"])
    from tau_intent.rescue import sumarizador_falso

    return asyncio.run(run_task(root, flags, prompt="add a module", harness=harness,
                                adapter=CodeAdapter(), summarizer_fn=sumarizador_falso(), **kwargs))


class TestUntrackedEffects(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, path, content=NEW_MODULE, binary=False):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if binary else content.encode())

    def test_the_legacy_diff_really_misses_a_new_module(self):
        """The defect, kept as a regression anchor: HEAD diff is blind to it."""
        self.create("pkg/new.py")
        self.assertEqual(git_diff(self.root), "")
        self.assertEqual([r.path for r in observe(self.root).regions], ["pkg/new.py"])

    def test_new_module_is_one_added_hunk_with_a_resolved_symbol(self):
        self.create("pkg/new.py")
        adapter = CodeAdapter()
        regions = adapter.effects(self.root)
        self.assertEqual([(r.path, r.line_start, r.line_end, r.edited_lines) for r in regions],
                         [("pkg/new.py", 1, 2, 2)])
        self.assertEqual(regions[0].symbol, "g")
        self.assertEqual(adapter.last_observation.untracked, ["pkg/new.py"])
        self.assertEqual(adapter.last_observation.opaque, {})

    def test_agent_creates_a_new_module_and_AUSENTE_fires_without_an_intent(self):
        self.create("pkg/new.py")
        harness = FakeHarness(script(write_start("pkg/new.py")), max_turns=None)
        result = run_b(self.root, harness)
        self.assertIn(result.verdict, {"BLOQUEIA", "ESCALAR"})
        self.assertTrue(result.telemetry["gate_avaliado"])
        self.assertIn("AUSENTE", result.follow_ups[0])
        self.assertIn("pkg/new.py", result.follow_ups[0])
        self.assertEqual(result.telemetry["efeitos_nao_rastreados"], ["pkg/new.py"])
        self.assertFalse(result.telemetry["captura_publicada"])

    def test_the_same_module_with_its_intent_passes_and_is_published(self):
        self.create("pkg/new.py")
        harness = FakeHarness(script(write_start("pkg/new.py"), intent_start(**INTENT)), max_turns=None)
        result = run_b(self.root, harness)
        self.assertEqual(result.verdict, "PASSA")
        self.assertTrue(result.telemetry["captura_publicada"])
        entries = (self.root / "intents.jsonl").read_text().splitlines()
        self.assertEqual(len(entries), 1)

    def test_binary_untracked_file_is_declared_and_still_an_effect(self):
        self.create("assets/logo.bin", b"\x00\x01\x02binary", binary=True)
        adapter = CodeAdapter()
        regions = adapter.effects(self.root)
        self.assertEqual([r.path for r in regions], ["assets/logo.bin"])
        self.assertIsNone(regions[0].resolver)  # no identity: a declared coarse target
        self.assertEqual(adapter.last_observation.opaque, {"assets/logo.bin": "binary"})
        harness = FakeHarness(script(write_start("assets/logo.bin", "x")), max_turns=None)
        result = run_b(self.root, harness)
        self.assertIn("AUSENTE", result.follow_ups[0])
        self.assertEqual(result.telemetry["efeitos_opacos"], {"assets/logo.bin": "binary"})

    def test_a_binary_effect_can_be_satisfied_by_naming_its_path(self):
        self.create("assets/logo.bin", b"\x00\x01\x02binary", binary=True)
        harness = FakeHarness(script(
            write_start("assets/logo.bin", "x"),
            intent_start(file="assets/logo.bin", why="o agente adicionou um recurso binário da tarefa",
                         property="o arquivo existe", domain="assets")), max_turns=None)
        result = run_b(self.root, harness)
        self.assertEqual(result.verdict, "PASSA")

    def test_modified_tracked_binary_is_declared(self):
        (self.root / "blob.bin").write_bytes(b"\x00one")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "blob")
        (self.root / "blob.bin").write_bytes(b"\x00two-different")
        obs = observe(self.root)
        self.assertEqual(obs.opaque, {"blob.bin": "binary"})
        self.assertEqual([r.path for r in obs.regions], ["blob.bin"])

    def test_symlink_oversized_and_invalid_utf8_are_declared_not_read(self):
        os.symlink("src/mod.py", self.root / "alias.py")
        (self.root / "latin.txt").write_bytes(b"caf\xe9\n")
        from tau_intent.adapters import code as code_mod
        (self.root / "big.txt").write_bytes(b"x" * 64)
        original = code_mod.OPAQUE_ABOVE_BYTES
        code_mod.OPAQUE_ABOVE_BYTES = 32
        try:
            obs = observe(self.root)
        finally:
            code_mod.OPAQUE_ABOVE_BYTES = original
        self.assertEqual(obs.opaque, {"alias.py": "symlink", "big.txt": "too-large", "latin.txt": "binary"})

    def test_names_with_spaces_and_unicode_survive(self):
        self.create("my pkg/módulo novo.py")
        self.assertEqual(observe(self.root).untracked, ["my pkg/módulo novo.py"])

    def test_ignored_files_are_not_effects(self):
        (self.root / ".git" / "info" / "exclude").write_text("__pycache__/\nintents.jsonl\n")
        self.create("__pycache__/mod.cpython-312.pyc", b"\x00\x00", binary=True)
        self.create("intents.jsonl", "{}\n")
        self.assertEqual(observe(self.root).regions, [])

    def test_the_mechanisms_own_intent_log_is_not_an_effect_of_the_agent(self):
        self.create("intents.jsonl", "{}\n")
        self.assertEqual(observe(self.root).regions, [])
        self.assertEqual(CodeAdapter().effects(self.root), [])
        self.assertEqual([r.path for r in observe(self.root, ignore=()).regions], ["intents.jsonl"])

    def test_clean_tree_is_a_truly_empty_effect_set(self):
        obs = observe(self.root)
        self.assertEqual((obs.regions, obs.untracked, obs.opaque), ([], [], {}))

    def test_git_failure_is_an_error_not_an_empty_effect_set(self):
        with tempfile.TemporaryDirectory() as bare:
            with self.assertRaises(EffectObservationError):
                CodeAdapter().effects(Path(bare))
            with self.assertRaises(EffectObservationError):
                asyncio.run(run_task(Path(bare), flags_from_args(["--arm", "A"]),
                                     harness=FakeHarness(max_turns=None), modelo_consumidor="m"))
        with self.assertRaises(EffectObservationError):
            observe(self.root, base="no-such-revision")

    def test_agent_that_commits_its_own_work_cannot_hide_it(self):
        start = git(self.root, "rev-parse", "HEAD").strip()
        self.create("pkg/new.py")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "agent committed")
        self.assertEqual(observe(self.root).regions, [])  # HEAD moved: nothing to see
        self.assertEqual([r.path for r in observe(self.root, base=start).regions], ["pkg/new.py"])
        self.assertEqual([r.path for r in CodeAdapter(base=start).effects(self.root)], ["pkg/new.py"])

    def test_participants_global_git_config_does_not_change_what_is_seen(self):
        (self.root / "src" / "mod.py").write_text("def f():\n    return 5\n")
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "gitconfig"
            config.write_text("[diff]\n\tnoprefix = true\n\tmnemonicPrefix = true\n\texternal = /bin/false\n")
            old = os.environ.get("GIT_CONFIG_GLOBAL")
            os.environ["GIT_CONFIG_GLOBAL"] = str(config)
            try:
                regions = observe(self.root).regions
            finally:
                os.environ.pop("GIT_CONFIG_GLOBAL") if old is None else os.environ.update(GIT_CONFIG_GLOBAL=old)
        self.assertEqual([r.path for r in regions], ["src/mod.py"])

    def test_rename_is_seen_as_delete_plus_add(self):
        git(self.root, "mv", "src/mod.py", "src/renamed.py")
        paths = sorted(r.path for r in observe(self.root).regions)
        self.assertEqual(paths, ["src/mod.py", "src/renamed.py"])


if __name__ == "__main__":
    unittest.main()
