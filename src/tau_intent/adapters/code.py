"""Code witness. Resolver/diff/blob routines moved unchanged after Wave 1."""
from __future__ import annotations
import ast
import os
import re
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from tau_intent.collect import Region, collect_events
from tau_intent.model import Anchor

_HUNK = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_GIT = re.compile(r"^diff --git a/.+ b/(.+)$")
_PLUS_PLUS = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: Stamped on every region this resolver named. v2 (2026-10-09): one name per
#: changed line, dotted, decorators inside the def; hunks split where it changes.
RESOLVER = "stdlib-identities-v2"


def regions_from_diff(diff: str | Iterable[Region]) -> list[Region]:
    """Parse a unified git diff, or pass through an already-built region list.

    Records both the hunk length (``size``) and the number of added/changed
    lines (``edited_lines``). The second is what ``limiar_edicao`` was always
    supposed to mean (D7): a 44-line hunk with 3 lines of context each side is
    a 38-line edit, and only the exact count says so.

    Each hunk also keeps its changed lines in ``Region.mudancas``: an added
    line by its line in the new file, a removed line by its line in the old
    file and the new-file line it sat before. ``resolver_simbolos`` names each
    one and splits the hunk where the name changes. A hunk is read by its
    header counts, so a removed line that starts with ``-- `` is a line, not a
    file header.
    """
    if not isinstance(diff, str):
        return list(diff)
    regions: list[Region] = []
    path = ""
    current: Region | None = None
    old_no = new_no = old_left = new_left = bloco = 0
    for line in diff.splitlines():
        git = _DIFF_GIT.match(line)
        hunk = None if git else _HUNK.match(line)
        dentro = current is not None and (old_left > 0 or new_left > 0)
        if git:
            path = git.group(1)
            current = None
            continue
        if hunk and path:
            old_no, new_no = int(hunk.group(1)), int(hunk.group(3))
            old_left = int(hunk.group(2) or "1")
            count = new_left = int(hunk.group(4) or "1")
            end = new_no + max(count, 1) - 1
            current = Region(
                path=path, line_start=new_no, line_end=end, size=count, edited_lines=0
            )
            bloco = 0
            regions.append(current)
            continue
        if not dentro and (line.startswith("--- ") or line.startswith("+++ ")):
            plus = _PLUS_PLUS.match(line)
            if plus and plus.group(1) != "/dev/null":
                path = plus.group(1)
            current = None
            continue
        if current is None:
            continue
        tag = line[:1]
        if tag == "+":
            current.mudancas.append(("+", new_no, new_no, bloco, line[1:]))
            new_no += 1
            new_left -= 1
        elif tag == "-":
            current.mudancas.append(("-", old_no, new_no, bloco, line[1:]))
            old_no += 1
            old_left -= 1
        elif tag == " " or (line == "" and dentro):
            old_no += 1
            new_no += 1
            old_left -= 1
            new_left -= 1
            bloco += 1
        if tag in {"+", "-"}:
            current.edited_lines = (current.edited_lines or 0) + 1
    return regions


def definicoes(source: str | None) -> list[tuple[int, int, str]] | None:
    """(first line, last line, dotted name) of every def/class; ``None`` if unparseable.

    The first line is the first decorator's: ``@validate_params(...)`` belongs to
    the function it decorates, not to the class or module around it. The name
    is the path through the enclosing defs and classes (``Pipeline.predict``).
    Read-only use of the AST, same parser ``code_graph.py`` builds its nodes
    with. No user code is executed and no file is written.
    """
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    out: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _DEFS):
                name = f"{prefix}.{child.name}" if prefix else child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                out.append((start, getattr(child, "end_lineno", None) or child.lineno, name))
                visit(child, name)
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _mais_interna(defs: Iterable[tuple[int, int, str]], start: int, end: int) -> str | None:
    best: tuple[int, str] | None = None
    for first, last, name in defs:
        if first <= start and end <= last and (best is None or last - first < best[0]):
            best = (last - first, name)
    return best[1] if best else None


def resolver_simbolo(source: str, line_start: int, line_end: int) -> str | None:
    """Innermost def/class of ``source`` that contains the whole line range, dotted."""
    defs = definicoes(source)
    return _mais_interna(defs, line_start, line_end) if defs is not None else None


def _defs_do_arquivo(path: Path) -> list[tuple[int, int, str]] | None:
    if path.suffix != ".py":
        return None
    try:
        return definicoes(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def resolver_simbolos(regions: Iterable[Region], workspace: Path | str | None,
                      fonte_antiga: Callable[[str], str | None] | None = None) -> list[Region]:
    """Name every region from the AST: the innermost def/class, dotted, decorators included.

    A diff hunk (``Region.mudancas``) is named line by line and split where the
    name changes: a hunk over the end of ``A.f`` and the start of ``A.g`` is two
    regions, ``A.f`` and ``A.g``, never ``A``. Context lines name nothing. An
    added line is named in the post-edit tree; a removed line in the pre-edit
    tree (``fonte_antiga(path)``), so a deleted method keeps its own name.
    Without the pre-edit source, a removed line takes the name of the added
    lines it was replaced by, else of the def around the lines before and after it.

    A region without ``mudancas`` (a new file, an opaque effect, a supplied
    range) keeps one name for its whole range. Idempotent: a region this
    resolver already named is returned as it is. Use the returned list: a
    split hunk is new regions.
    """
    if workspace is None:
        return list(regions)
    root = Path(workspace)
    novas: dict[str, list[tuple[int, int, str]] | None] = {}
    antigas: dict[str, list[tuple[int, int, str]] | None] = {}
    out: list[Region] = []
    for region in regions:
        if region.resolver == RESOLVER:
            out.append(region)
            continue
        if region.path not in novas:
            novas[region.path] = _defs_do_arquivo(root / region.path)
        defs = novas[region.path]
        if defs is None:
            region.resolver = None
            out.append(region)
            continue
        if not region.mudancas:
            region.resolver = RESOLVER
            region.symbol = _mais_interna(defs, region.line_start, region.line_end)
            out.append(region)
            continue
        if region.path not in antigas:
            antigas[region.path] = definicoes(fonte_antiga(region.path)) if fonte_antiga else None
        out.extend(_dividir(region, defs, antigas[region.path]))
    return out


def _dividir(region: Region, defs: list[tuple[int, int, str]],
             antigas: list[tuple[int, int, str]] | None) -> list[Region]:
    itens = _sem_pares_iguais(region.mudancas)
    if not itens:
        region.resolver = RESOLVER
        region.symbol = _mais_interna(defs, region.line_start, region.line_end)
        return [region]
    nomes: list[str | None] = []
    for index, (tag, linha, _pos, _bloco, _texto) in enumerate(itens):
        if tag == "+":
            nomes.append(_mais_interna(defs, linha, linha))
        elif antigas is not None:
            nomes.append(_mais_interna(antigas, linha, linha))
        else:
            nomes.append(_nome_sem_fonte_antiga(itens, index, defs))
    nomes = _brancas_seguem_o_vizinho(itens, nomes)
    grupos: dict[str | None, list[tuple]] = {}
    for item, nome in zip(itens, nomes):
        grupos.setdefault(nome, []).append(item)
    regioes: dict[tuple[int, int], Region] = {}
    for nome, grupo in grupos.items():
        # A def's lines are where they are in the post-edit tree. Removed lines
        # count, but only place the region when nothing of the def was added
        # (a deleted def sits where it used to be).
        linhas = [linha for tag, linha, *_ in grupo if tag == "+"]
        if not linhas:
            linhas = [max(pos, 1) for _tag, _linha, pos, *_ in grupo]
        start, end = min(linhas), max(linhas)
        igual = regioes.get((start, end))
        if igual is not None:
            # A line removed from one def and added to another at the same spot
            # (a rename): one region, named as the post-edit tree names it.
            if any(tag == "+" for tag, *_ in grupo):
                igual.symbol = nome
            igual.mudancas.extend(grupo)
            igual.edited_lines = (igual.edited_lines or 0) + len(grupo)
            continue
        regioes[(start, end)] = Region(
            region.path, start, end, size=end - start + 1, edited_lines=len(grupo),
            symbol=nome, resolver=RESOLVER, size_unit=region.size_unit, mudancas=list(grupo))
    return sorted(regioes.values(), key=lambda r: (r.line_start, r.line_end))


def _sem_pares_iguais(itens: list[tuple]) -> list[tuple]:
    """Drop a line removed and added back unchanged in the same block.

    git shows that pair when only the newline at the end of the file changed,
    and sometimes when it aligns a block. The line's text did not change, so
    the def around it did not either.
    """
    restantes = list(itens)
    for item in itens:
        if item[0] != "-" or item not in restantes:
            continue
        par = next((outro for outro in restantes if outro[0] == "+" and outro[3] == item[3]
                    and outro[4] == item[4]), None)
        if par is not None:
            restantes.remove(item)
            restantes.remove(par)
    return restantes


def _brancas_seguem_o_vizinho(itens: list[tuple], nomes: list[str | None]) -> list[str | None]:
    """A blank changed line takes the name of the nearest non-blank change.

    Blank lines between two defs belong to neither, and naming them by the
    module or the class would ask for an intent about whitespace. They join
    the next non-blank change of the hunk, else the previous one.
    """
    cheias = [i for i, item in enumerate(itens) if item[4].strip()]
    if not cheias:
        return nomes
    out = list(nomes)
    for i, item in enumerate(itens):
        if item[4].strip():
            continue
        depois = [j for j in cheias if j > i]
        out[i] = nomes[depois[0] if depois else cheias[-1]]
    return out


def _nome_sem_fonte_antiga(itens: list[tuple], index: int,
                           defs: list[tuple[int, int, str]]) -> str | None:
    _tag, _linha, pos, bloco, _texto = itens[index]
    trocas = [linha for tag, linha, _p, b, _t in itens if tag == "+" and b == bloco]
    if trocas:
        perto = min(trocas, key=lambda linha: abs(linha - pos))
        return _mais_interna(defs, perto, perto)
    antes = pos - 1
    return _mais_interna(defs, antes if antes >= 1 else pos, pos)


def simbolos_do_ast(regions: Iterable[Region], workspace: Path | str | None) -> set[str]:
    """The symbol table the gate validates ``record_intent.symbol`` against.

    Node ids in ``file::symbol`` shape, for every def/class of every file the
    diff touched, by its dotted name and by its bare name (``Pipeline.predict``
    and ``predict``), plus every name the resolver gave a region: a removed
    def keeps its pre-edit name, and the gate must know every name it asks for.
    This is what replaces the supervisor's old ``_symbols_from_pending``, which
    built the known set by scraping the very property texts it was supposed to
    check (D2).
    """
    if workspace is None:
        return set()
    regions = list(regions)
    root = Path(workspace)
    nomes: set[str] = set()
    for path in {region.path for region in regions}:
        for _first, _last, nome in _defs_do_arquivo(root / path) or ():
            nomes.add(f"{path}::{nome}")
            nomes.add(f"{path}::{nome.rsplit('.', 1)[-1]}")
    nomes |= {region.node_id() for region in regions if region.symbol}
    return nomes


def git_diff(workspace: Path) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "diff", "--no-color", "HEAD"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


class EffectObservationError(RuntimeError):
    """git could not tell us what changed.

    This is **not** an empty effect set. Returning ``[]`` on a failed ``git``
    call made a broken witness indistinguishable from an agent that changed
    nothing, and ``AUSENTE`` (an effect with no intent) could then never fire.
    """


#: Bytes read to decide whether an untracked file is text (git's own window).
_BINARY_WINDOW = 8192
#: An untracked file above this size is declared opaque instead of being read.
OPAQUE_ABOVE_BYTES = 2 * 1024 * 1024

_GIT_FLAGS = ("-c", "core.quotepath=off", "-c", "diff.noprefix=false",
              "-c", "diff.mnemonicPrefix=false", "-c", "color.ui=false")


@dataclass
class Observation:
    """What one look at the working tree saw."""

    regions: list[Region] = field(default_factory=list)
    #: Paths the agent created and git does not track yet (text or opaque).
    untracked: list[str] = field(default_factory=list)
    #: Effects whose content is not line-addressable, with the reason. They are
    #: still effects (a coarse Region, no identity) so ``AUSENTE`` can fire and
    #: the agent can satisfy it with a record_intent that names the path.
    opaque: dict[str, str] = field(default_factory=dict)


def _git(workspace: Path, *args: str) -> bytes:
    env = {**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        proc = subprocess.run(["git", *_GIT_FLAGS, *args], cwd=workspace, check=False,
                              capture_output=True, env=env)
    except OSError as exc:
        raise EffectObservationError(f"git could not be run: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise EffectObservationError(
            f"git {' '.join(args)} failed in {workspace} (exit {proc.returncode}): {detail}")
    return proc.stdout


def fonte_na_base(workspace: Path, base: str, path: str) -> str | None:
    """The file as it was at ``base``, for naming removed lines. ``None`` if it was not there."""
    try:
        return _git(workspace, "show", f"{base}:{path}").decode("utf-8")
    except (EffectObservationError, UnicodeDecodeError):
        return None


def _opaque_region(path: str) -> Region:
    return Region(path, 0, 0, size=1, edited_lines=0, resolver=None)


#: Files the mechanism itself writes into the workspace. They are not the
#: agent's effects: the supervisor appends to the intent log, and counting that
#: write as an effect would make every captured intent demand another intent.
MECHANISM_FILES = ("intents.jsonl",)


def observe(workspace: Path, base: str = "HEAD",
            ignore: Iterable[str] = MECHANISM_FILES) -> Observation:
    """Tracked changes against ``base`` **plus** files git does not track yet.

    ``base`` defaults to HEAD; the bench passes the commit its task started
    from, so an agent that runs ``git commit`` itself cannot hide its work.
    Raises ``EffectObservationError`` when git fails. ``ignore`` names workspace
    paths the mechanism writes itself (the intent log); they are never effects.
    """
    workspace = Path(workspace)
    skip = set(ignore)
    diff = _git(workspace, "diff", "--no-color", "--no-ext-diff", "--no-renames",
                "--src-prefix=a/", "--dst-prefix=b/", base).decode("utf-8", "replace")
    obs = Observation(regions=[r for r in regions_from_diff(diff) if r.path not in skip])
    # numstat reports "-\t-\tpath" for content git treats as binary: the diff
    # above has no hunk for it, so without this the effect would vanish.
    numstat = _git(workspace, "diff", "--numstat", "-z", "--no-renames", base)
    for entry in numstat.split(b"\0"):
        parts = entry.split(b"\t", 2)
        if len(parts) == 3 and parts[0] == b"-" and parts[1] == b"-":
            path = parts[2].decode("utf-8", "replace")
            if path in skip:
                continue
            obs.opaque[path] = "binary"
            obs.regions.append(_opaque_region(path))
    listed = _git(workspace, "ls-files", "--others", "--exclude-standard", "-z")
    for raw in sorted(item for item in listed.split(b"\0") if item):
        path = raw.decode("utf-8", "replace")
        if path in skip:
            continue
        obs.untracked.append(path)
        region = _untracked_region(workspace, path, obs.opaque)
        obs.regions.append(region)
    return obs


def _untracked_region(workspace: Path, path: str, opaque: dict[str, str]) -> Region:
    full = workspace / path
    try:
        info = full.lstat()
    except OSError:
        opaque[path] = "unreadable"
        return _opaque_region(path)
    if not full.is_file() or full.is_symlink():
        opaque[path] = "symlink" if full.is_symlink() else "not-a-regular-file"
        return _opaque_region(path)
    if info.st_size > OPAQUE_ABOVE_BYTES:
        opaque[path] = "too-large"
        return _opaque_region(path)
    try:
        data = full.read_bytes()
    except OSError:
        opaque[path] = "unreadable"
        return _opaque_region(path)
    if b"\0" in data[:_BINARY_WINDOW]:
        opaque[path] = "binary"
        return _opaque_region(path)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        opaque[path] = "binary"
        return _opaque_region(path)
    # A new file is one added hunk: the same shape `git diff` gives a file that
    # was intent-to-add, without touching the index to get it.
    n = len(lines)
    return Region(path, 1, max(n, 1), size=max(n, 1), edited_lines=n)


def _blob_sha(path: Path) -> str:
    """git's blob object id of the file as it is on disk. No placeholder.

    While it was ``"0" * 40`` no anchor was verifiable against the tree.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "0" * 40
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - git's own format


class CodeAdapter:
    name = "code"
    version = "code-v1"
    size_unit = "edited_lines"
    edge_types = ("contains", "imports", "invokes", "inherits")

    def __init__(self, base: str = "HEAD", ignore: Iterable[str] = MECHANISM_FILES):
        #: Revision the effects are measured against (the task's starting commit).
        self.base = base
        self.ignore = tuple(ignore)
        #: The last tree observation, for telemetry (untracked / opaque effects).
        self.last_observation: Observation | None = None

    def effects(self, workspace, supplied=None):
        if supplied is not None:
            return resolver_simbolos(regions_from_diff(supplied), workspace)
        self.last_observation = observe(Path(workspace), self.base, self.ignore)
        return resolver_simbolos(list(self.last_observation.regions), workspace,
                                 fonte_antiga=lambda path: fonte_na_base(Path(workspace), self.base, path))

    def collect(self, events, effects, workspace):
        return collect_events(events, effects, workspace)

    def identities(self, effects, workspace):
        return simbolos_do_ast(effects, workspace)

    def anchor(self, pending, workspace):
        r = pending.region
        return Anchor(file=r.path, symbol=r.symbol or None,
                      line_start=r.line_start, line_end=r.line_end,
                      blob_sha=_blob_sha(workspace / r.path))

    def neighbourhood(self, workspace):
        from tau_intent.adapters.code_graph import build_cached
        return build_cached(str(workspace), "worktree")

    def oracle(self, check):
        result = check()
        if type(result) is not bool:
            raise TypeError("oracle must return bool")
        return result

    def classification(self, effect):
        return Path(effect.path).suffix.lstrip(".") or "sem-extensao"


    def anchor_resolves(self, anchor, workspace):
        target = workspace / anchor.file
        if not target.is_file() or _blob_sha(target) != anchor.blob_sha:
            return False
        if anchor.symbol is None:
            return True
        return anchor.node_id() in simbolos_do_ast(
            [Region(anchor.file, anchor.line_start, anchor.line_end)], workspace)

    def validate(self, command, workspace):
        """Run an explicitly supplied local argv; record the actual exit and output."""
        import json
        import subprocess
        from tau_intent.checkpoint import ValidationEvidence
        if not isinstance(command, (list, tuple)) or not command or not all(type(s) is str for s in command):
            raise ValueError("validation command must be a non-empty argv")
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=False)
        return ValidationEvidence(json.dumps(list(command)), json.dumps({
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
