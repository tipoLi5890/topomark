"""Shared logic for the navigation commands (outline, symbol, find, refs, impact,
tests-for, map).

Everything here is approximate by design, like the reference graph: a reference
is a word-boundary match of an identifier in *masked* text (comments and string
literals blanked), not a resolved binding. That is fast, language-agnostic and
right often enough for an agent deciding what to read next.

* ``Nav`` wraps a ``Workspace`` and caches masked text per file. Single-file
  commands go through ``Nav.info`` (one parse, no repo scan); only commands that
  need the whole repo touch ``Nav.infos``.
* ``resolve`` turns ``file#Qual.Name`` or a bare ``Name`` into symbols;
  ``enclosing_symbol`` maps a line back to the declaration around it.
* ``Nav.importers`` answers "who imports this file" from Python and JS/TS import
  statements (``ImportResolver``), separately from the name-based reference graph.
* ``impact_file`` / ``impact_symbol`` build the ``impact`` summaries as dicts.
* ``changed_files`` asks git what changed (working tree, index, or since a rev).
* ``test_methods`` / ``render_runner`` pick test functions and print commands.
* ``estimate_tokens`` is the one token estimate (``contract.estimate_tokens``).
"""

from __future__ import annotations

import math
import posixpath
import re
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property

from . import repo
from .config import TestRunner
from .contract import estimate_tokens as estimate_tokens
from .docs import is_test, owner_of, unit_of
from .errors import TopomarkError
from .lang.base import DYNAMIC, FileInfo, Symbol
from .lang.scan import Masked, mask
from .workspace import Workspace

# Languages whose text is prose or data: never masked, never a reference site, ranked after code.
# The data adapter is named "data"; the files it parses report json, toml or yaml.
NON_CODE_LANGS = frozenset({"markdown", "data", "json", "toml", "yaml", "text", "large"})
MENTION_EXT = (".md", ".markdown", ".txt", ".rst", ".adoc", ".html", ".json", ".jsonc", ".yaml", ".yml", ".toml")
TEST_ATTRS = frozenset({"test", "unitytest", "testcase", "testcasesource", "theory", "fact", "testmethod",
                        "parameterizedtest", "valuesource", "testfixturesource", "pytest.mark.parametrize"})
LINE_MAX = 160


def clip(s: str, n: int = LINE_MAX) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def word_rx(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(name) + r"(?![A-Za-z0-9_$])")


def depth_of(sym: Symbol) -> int:
    return sym.container.count(".") + 1 if sym.container else 0


def is_type_kind(kind: str) -> bool:
    return kind in {"class", "struct", "interface", "enum", "record", "trait", "protocol", "type", "object",
                    "@interface", "module", "impl", "extension", "mixin", "union"}


@dataclass
class Site:
    path: str
    line: int
    text: str
    test: bool
    group: str

    def to_json(self) -> dict:
        return {"path": self.path, "line": self.line, "text": self.text, "test": self.test, "group": self.group}


@dataclass
class TestPick:
    """One test file chosen by ``tests-for``: which classes/methods, or the whole file."""

    path: str
    methods: list[tuple[str, str]] = field(default_factory=list)  # (class qualname, method name)
    classes: list[str] = field(default_factory=list)
    whole_file: bool = False
    reason: str = ""
    names: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)  # callers between the changed file and this test

    def to_json(self) -> dict:
        return {"path": self.path, "whole_file": self.whole_file, "reason": self.reason, "names": self.names,
                "classes": self.classes,
                "methods": [f"{c}.{m}" if c else m for c, m in self.methods], "via": self.via}


@dataclass
class TestSelection:
    """What ``select_tests`` found for a set of changed files."""

    depth: int
    picks: dict[str, TestPick] = field(default_factory=dict)        # test file → pick
    names_of: dict[str, list[str]] = field(default_factory=dict)    # changed production file → its names
    uncovered: list[str] = field(default_factory=list)             # changed files no test reaches
    limited: list[str] = field(default_factory=list)               # caller search stopped at MAX_CALLERS
    dynamic_loaders: list[str] = field(default_factory=list)       # set when files stay uncovered

    def ordered(self) -> list[TestPick]:
        return [self.picks[k] for k in sorted(self.picks)]


class Nav:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.cfg = ctx.config
        self.ws = Workspace(ctx)
        self._masked: dict[str, Masked] = {}
        self._lines: dict[str, list[str]] = {}

    # ---------------------------------------------------------------- files
    @property
    def infos(self) -> dict[str, FileInfo]:
        return self.ws.infos

    @property
    def graph(self):
        return self.ws.graph

    def exists(self, path: str) -> bool:
        """A file inside the repository: a path that climbs out, or a symbolic link that leads
        out of it, does not exist here (a secret-looking file does, and reading it is refused)."""
        return repo.inside(self.ctx.root, path) and (self.ctx.root / path).is_file()

    def info(self, path: str) -> FileInfo:
        if not self.exists(path):
            raise TopomarkError("NOT_FOUND", f"no such file: {path}")
        if "infos" in self.ws.__dict__ and path in self.ws.infos:
            return self.ws.infos[path]
        info = self.ws.index.info(path)
        self.ws.index.save()
        return info

    def is_test(self, path: str) -> bool:
        return is_test(path, self.cfg)

    def is_code(self, path: str, info: FileInfo | None = None) -> bool:
        info = info or self.infos.get(path)
        return info is not None and info.lang not in NON_CODE_LANGS

    def lines(self, path: str) -> list[str]:
        if path not in self._lines:
            self._lines[path] = self.ctx.read(path).split("\n")
        return self._lines[path]

    def masked(self, path: str) -> Masked:
        """Comments and strings blanked with the file's own adapter syntax (offsets kept)."""
        if path in self._masked:
            return self._masked[path]
        text = self.ctx.read(path)
        m = mask_file(path, text)
        self._masked[path] = m
        self._lines.setdefault(path, text.split("\n"))
        return m

    def masked_lines(self, path: str) -> list[str]:
        return self.masked(path).text.split("\n")

    def group_of(self, path: str) -> str:
        """Area name when the repo has a code map, else the top-level directory."""
        if self.ws.areas:
            a, _ = owner_of(path, self.ws.areas)
            if a:
                return a.name
        return path.split("/", 1)[0] + "/" if "/" in path else "."

    def in_area(self, path: str, area: str) -> bool:
        if self.ws.areas and area in {a.name for a in self.ws.areas}:
            a, _ = owner_of(path, self.ws.areas)
            return bool(a and a.name == area)
        prefix = area.rstrip("/") + "/"
        return path.startswith(prefix) or self.group_of(path) == area

    def check_area(self, area: str | None) -> None:
        if not area:
            return
        if self.ws.areas and area in {a.name for a in self.ws.areas}:
            return
        prefix = area.rstrip("/") + "/"
        if not any(f.startswith(prefix) for f in self.ctx.files):
            have = ", ".join(a.name for a in self.ws.areas) or "(no code map; pass a top-level directory)"
            raise TopomarkError("NOT_FOUND", f"no area or directory named {area!r} (have: {have})")

    # ---------------------------------------------------------------- symbols
    @staticmethod
    def match_symbols(info: FileInfo, spec: str) -> list[Symbol]:
        """Symbols in one file matching ``Name`` or ``Qual.Name`` (exact qualname wins)."""
        syms = [s for s in info.symbols if s.kind != "namespace"] or info.symbols
        exact = [s for s in syms if s.qualname == spec]
        if exact:
            return exact
        if "." in spec:
            return [s for s in syms if s.qualname.endswith("." + spec)]
        return [s for s in syms if s.name == spec]

    def find_symbols(self, spec: str) -> list[tuple[str, Symbol]]:
        """Repo-wide exact lookup of ``Name`` / ``Qual.Name``."""
        last = spec.rsplit(".", 1)[-1]
        out = []
        for path, info in self.infos.items():
            if last not in info.idents and not declares(info, last):
                continue
            for s in self.match_symbols(info, spec):
                out.append((path, s))
        return out

    def resolve(self, spec: str) -> tuple[list[tuple[str, Symbol]], list[tuple[str, Symbol]]]:
        """``file#Name`` or ``Name`` → (matches, candidates). ``matches`` is empty and
        ``candidates`` set when a bare name is declared in more than one file."""
        if "#" in spec:
            path, name = spec.split("#", 1)
            from .commands._common import rel

            path = rel(self.ctx, path)
            info = self.info(path)
            found = self.match_symbols(info, name)
            if not found:
                have = ", ".join(sorted({s.name for s in info.symbols if s.kind != "namespace"})[:30])
                raise TopomarkError("NOT_FOUND", f"no symbol {name!r} in {path} (has: {have or 'none'})")
            return [(path, s) for s in found], []
        found = self.find_symbols(spec)
        if not found:
            raise TopomarkError("NOT_FOUND", f"no definition named {spec!r} (try `topomark find {spec}`)")
        files = {p for p, _ in found}
        if len(files) > 1:
            prod = [(p, s) for p, s in found if not self.is_test(p)]
            if prod and len({p for p, _ in prod}) == 1:
                return prod, []
            return [], found
        return found, []

    # ---------------------------------------------------------------- references
    def ref_sites(self, spec: str, area: str | None = None, include_tests: bool = True) -> list[Site]:
        """Word-boundary hits of a name in masked code, declarations excluded.

        ``Type.Member``: lines with ``Member`` in files that also mention ``Type``
        or declare it."""
        parts = spec.split(".")
        member = parts[-1]
        owner = parts[-2] if len(parts) > 1 else ""
        rx = word_rx(member)
        decl_lines: dict[str, set[int]] = defaultdict(set)
        declaring_owner: set[str] = set()
        for path, info in self.infos.items():
            if member not in info.idents and not owner:
                continue
            if not declares(info, member) and not (owner and declares(info, owner)):
                continue
            for s in info.symbols:
                if s.name == member and (not owner or s.container.rsplit(".", 1)[-1] == owner):
                    decl_lines[path].add(s.line or s.start)
                if owner and s.name == owner and s.kind != "namespace":
                    declaring_owner.add(path)
        out: list[Site] = []
        for path, info in self.infos.items():
            if info.lang in NON_CODE_LANGS or member not in info.idents:
                continue
            if owner and path not in declaring_owner and owner not in info.idents:
                continue
            test = self.is_test(path)
            if test and not include_tests:
                continue
            if area and not self.in_area(path, area):
                continue
            try:
                mlines = self.masked_lines(path)
            except (OSError, TopomarkError):
                continue
            raw = self.lines(path)
            for i, ml in enumerate(mlines):
                if member not in ml or not rx.search(ml):
                    continue
                if (i + 1) in decl_lines.get(path, ()):
                    continue
                out.append(Site(path, i + 1, clip(raw[i] if i < len(raw) else ml), test, self.group_of(path)))
        out.sort(key=lambda s: (s.test, s.group, s.path, s.line))
        return out

    # ---------------------------------------------------------------- mentions in docs
    def mention_files(self) -> list[str]:
        roots = list(self.cfg.mention_roots) + [self.cfg.docs_prefix] + list(self.cfg.every_file_roots)
        seen = []
        for f in self.ctx.files:
            if any(f.startswith(r) for r in roots) and f.lower().endswith(MENTION_EXT):
                seen.append(f)
        return seen

    def mentions(self, needle: str, limit_bytes: int = 1_000_000) -> list[Site]:
        """Backtick or word matches of ``needle`` in docs and contract files (raw text)."""
        rx = word_rx(needle) if re.fullmatch(r"[A-Za-z0-9_.]+", needle) else re.compile(re.escape(needle))
        out = []
        for f in self.mention_files():
            try:
                if (self.ctx.root / f).stat().st_size > limit_bytes:
                    continue
                text = self.ctx.read(f)
            except (OSError, TopomarkError):
                continue
            if needle not in text:
                continue
            for i, ln in enumerate(text.split("\n")):
                if needle in ln and rx.search(ln):
                    out.append(Site(f, i + 1, clip(ln), False, self.group_of(f)))
        return out

    # ---------------------------------------------------------------- ranking helpers
    @cached_property
    def ident_counts(self) -> Counter:
        """identifier → number of files mentioning it (in-degree proxy for a name)."""
        def build() -> dict[str, int]:
            c: Counter = Counter()
            for info in self.infos.values():
                c.update(info.idents)
            return dict(c)

        return Counter(self.ws.derived("ident_counts", "", build))

    # ---------------------------------------------------------------- import edges
    @cached_property
    def import_edges(self) -> dict[str, list[str]]:
        """importer → the repo files its imports resolve to (Python and JS/TS)."""
        return self.ws.derived("imports", "", lambda: resolve_imports(self.infos))

    @cached_property
    def _importers(self) -> dict[str, list[str]]:
        return reverse_edges(self.import_edges)

    def importers(self, path: str) -> list[str]:
        """Files whose import statements resolve to ``path``, sorted."""
        return self._importers.get(path, [])

    def dynamic_loaders(self) -> list[str]:
        """Files that import a module by a computed name (``importlib.import_module(f"…")``,
        ``import(`./${x}`)``): what static import edges cannot see."""
        return sorted(p for p, i in self.infos.items() if DYNAMIC in i.imports)

    def decl_names(self, path: str) -> list[str]:
        """Top-level names a file declares that are long enough to search for."""
        info = self.infos.get(path) or self.info(path)
        keep = self.cfg.keep_short_names
        names = []
        for s in info.symbols:
            if s.container or s.kind == "namespace":
                continue
            if len(s.name) < self.cfg.min_name and s.name not in keep:
                continue
            if s.name not in names:
                names.append(s.name)
        for n in info.types:
            if n not in names and (len(n) >= self.cfg.min_name or n in keep):
                names.append(n)
        return names


def mask_file(path: str, text: str) -> Masked:
    """``text`` with comments and strings blanked by the adapter for ``path`` (offsets kept);
    prose and data files come back unmasked. ``original`` is ``text``."""
    from .lang import registry
    from .lang.python import SYNTAX as PY_SYNTAX

    adapter = registry.adapter_for(path)
    if getattr(adapter, "name", "") in NON_CODE_LANGS:
        return Masked(text, text)
    syntax = getattr(adapter, "syntax", None) or PY_SYNTAX
    premask = getattr(adapter, "premask", None)
    m = mask(premask(text) if callable(premask) else text, syntax)
    m.original = text
    return m


def enclosing_symbol(info: FileInfo, line: int) -> Symbol | None:
    """The innermost declaration whose line range holds ``line`` (namespaces skipped), or None."""
    best: Symbol | None = None
    for s in info.symbols:
        if s.kind == "namespace" or not s.start <= line <= s.end:
            continue
        if best is None or (s.end - s.start, -depth_of(s)) < (best.end - best.start, -depth_of(best)):
            best = s
    return best


# ---------------------------------------------------------------- skeletons
# Symbols whose body a skeleton replaces with "…": code bodies, and the value of a multi-line constant.
BODY_KINDS = frozenset({"function", "method", "constructor", "destructor", "operator", "getter", "setter",
                        "indexer", "property", "delegate"})
VALUE_KINDS = frozenset({"const", "field", "var", "event", "macro"})
_DOCSTRING_START = re.compile(r"""^[rRuUbB]{0,2}["']""")


def _header_end(mlines: list[str], sym: Symbol, python: bool) -> int | None:
    """The line (1-based) where ``sym``'s declaration ends and its body begins, or None when
    there is no separate body to leave out (one-liners, abstract members, declarations only)."""
    first = sym.line or sym.start
    if sym.kind in VALUE_KINDS:
        return first if sym.end > first else None
    depth = 0
    for k in range(first - 1, min(sym.end, len(mlines))):
        ml = mlines[k]
        for j, ch in enumerate(ml):
            if ch in "([" or (python and ch == "{"):
                depth += 1
            elif ch in ")]" or (python and ch == "}"):
                depth -= 1
            elif depth <= 0:
                if python and ch == ":" and ml[j + 1:j + 2] != "=":
                    return k + 1
                if not python and ch == "{":
                    return k + 1
                if not python and ch == ";":
                    return None
    return None


def skeleton_gaps(nav: Nav, path: str, sym: Symbol) -> list[tuple[int, int]]:
    """Line ranges (inclusive) a skeleton of ``sym`` leaves out: the bodies of its innermost
    members (or its own body when it has none), keeping each declaration, a Python docstring's
    first line and a closing brace."""
    info = nav.info(path)
    lines, mlines = nav.lines(path), nav.masked_lines(path)
    python = info.lang == "python"
    prefix = sym.qualname + "."
    inside = [s for s in info.symbols if s.qualname.startswith(prefix) and sym.start <= s.start and s.end <= sym.end
              and s.kind != "namespace"]
    containers = {s.container for s in inside}
    leaves = [s for s in inside if s.qualname not in containers] if inside else [sym]
    gaps: list[tuple[int, int]] = []
    for s in sorted(leaves, key=lambda x: x.start):
        if s.kind not in BODY_KINDS and s.kind not in VALUE_KINDS:
            continue
        head = _header_end(mlines, s, python)
        if head is None or head >= s.end:
            continue
        lo, hi = head + 1, s.end
        if python and s.kind not in VALUE_KINDS:
            k = lo
            while k <= hi and not lines[k - 1].strip():
                k += 1
            if k <= hi and _DOCSTRING_START.match(lines[k - 1].strip()):
                lo = k + 1  # keep the docstring's first line
        elif not python and s.kind not in VALUE_KINDS and lines[hi - 1].strip().startswith("}"):
            hi -= 1
        if hi > lo and (not gaps or lo > gaps[-1][1]):  # a one-line body costs what its marker would
            gaps.append((lo, hi))
    return gaps


# ---------------------------------------------------------------- import edges
PY_EXT = (".py", ".pyi")
JS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_JS_SWAP = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
_JS_ALIAS = ("@/", "~/", "#/")
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))


def _module_stem(path: str, index: str) -> str:
    """Path without extension; a package's ``__init__`` or a folder's ``index`` → the folder."""
    stem = path.rsplit(".", 1)[0]
    if stem.endswith(".d"):  # x.d.ts
        stem = stem[:-2]
    if stem.rsplit("/", 1)[-1] == index:
        stem = stem[: -len(index)].rstrip("/")
    return stem


def _nearest(importer: str, cands: list[str]) -> str | None:
    """The candidate sharing the longest directory prefix with the importer, then the shortest path."""
    if len(cands) <= 1:
        return cands[0] if cands else None
    here = importer.split("/")[:-1]

    def key(c: str) -> tuple[int, int, str]:
        common = 0
        for a, b in zip(here, c.split("/")[:-1]):
            if a != b:
                break
            common += 1
        return -common, len(c), c

    return min(cands, key=key)


class ImportResolver:
    """Import specifiers → repo files, the way the language looks them up, approximately.

    Python: ``.x`` / ``..x`` from the importer's package; ``a.b`` by module-path
    suffix (``topomark.cli`` → ``src/topomark/cli.py``), nearest to the importer when
    several files match. A name the standard library also has (``calendar.slots``) resolves
    only to a repo module the importer could reach before the standard library: one at the
    repo root (``calendar/slots.py``), or under a folder that is not a package and holds the
    importer (``src/calendar/slots.py`` from ``src/app/main.py``, a script's own folder).
    ``import json`` in ``src/app.py`` is not ``tools/json.py`` nor ``utils/json.py``.
    JS/TS: ``./x`` and ``../x`` with the usual extensions, ``.js`` written for a
    ``.ts`` file, and ``x/index.*``; ``@/x``, ``~/x`` and ``#/x`` aliases by path
    suffix. Bare package names (``react``) and computed names stay unresolved."""

    def __init__(self, files: Iterable[str]) -> None:
        self.files = set(files)
        self.py: dict[str, list[str]] = defaultdict(list)
        self.js: dict[str, list[str]] = defaultdict(list)
        for f in sorted(self.files):
            low = f.lower()
            if low.endswith(PY_EXT):
                table, stem = self.py, _module_stem(f, "__init__")
            elif low.endswith(JS_EXT):
                table, stem = self.js, _module_stem(f, "index")
            else:
                continue
            parts = stem.split("/") if stem else []
            for k in range(len(parts)):
                table["/".join(parts[k:])].append(f)

    def resolve(self, importer: str, spec: str) -> str | None:
        if not spec or spec == DYNAMIC:
            return None
        low = importer.lower()
        if low.endswith(PY_EXT):
            return self._python(importer, spec)
        if low.endswith(JS_EXT):
            return self._js(importer, spec)
        return None

    def _python(self, importer: str, spec: str) -> str | None:
        if spec.startswith("."):
            level = len(spec) - len(spec.lstrip("."))
            base = posixpath.dirname(importer)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            rest = spec[level:].replace(".", "/")
            target = posixpath.join(base, rest) if rest else base
            for cand in (target + ".py", target + ".pyi", posixpath.join(target, "__init__.py")):
                if cand in self.files:
                    return cand
            return None
        key = spec.replace(".", "/")
        cands = self.py.get(key, [])
        if spec.split(".", 1)[0] in _STDLIB:
            cands = [c for c in cands if self._shadows_stdlib(importer, c, key)]
        return _nearest(importer, cands)

    def _shadows_stdlib(self, importer: str, path: str, key: str) -> bool:
        """``path`` is the top-level module ``key`` as ``importer`` sees it: its source root is
        the repo root, or a folder that is not a package and holds the importer."""
        stem = _module_stem(path, "__init__")
        base = stem[: len(stem) - len(key)].rstrip("/")
        if not base:
            return True
        return posixpath.join(base, "__init__.py") not in self.files and importer.startswith(base + "/")

    def _js(self, importer: str, spec: str) -> str | None:
        if spec.startswith(("./", "../")) or spec in (".", ".."):
            return self._js_file(posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec)))
        if spec.startswith(_JS_ALIAS):
            tail = spec[2:].strip("/")
            return _nearest(importer, self.js.get(_module_stem(tail, "index") if tail.lower().endswith(JS_EXT)
                                                  else tail, []))
        return None

    def _js_file(self, target: str) -> str | None:
        if target in self.files and target.lower().endswith(JS_EXT):
            return target
        root, ext = posixpath.splitext(target)
        for alt in _JS_SWAP.get(ext.lower(), ()):
            if root + alt in self.files:
                return root + alt
        for e in JS_EXT + (".d.ts",):
            if target + e in self.files:
                return target + e
        for e in JS_EXT:
            if f"{target}/index{e}" in self.files:
                return f"{target}/index{e}"
        return None


def resolve_imports(infos: dict[str, FileInfo]) -> dict[str, list[str]]:
    """importer → the repo files its imports resolve to, in import order (self-imports dropped)."""
    resolver = ImportResolver(infos)
    out: dict[str, list[str]] = {}
    for path, info in infos.items():
        found: list[str] = []
        for spec in info.imports:
            f = resolver.resolve(path, spec)
            if f and f != path and f not in found:
                found.append(f)
        if found:
            out[path] = found
    return out


def reverse_edges(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for src, dsts in edges.items():
        for d in dsts:
            rev[d].append(src)
    return {k: sorted(v) for k, v in rev.items()}


# ---------------------------------------------------------------- impact
def impact_file(nav: Nav, path: str, top: int = 10) -> dict:
    """What changing a file reaches: the names it declares, fan-in (production and test files
    that mention them), importers, cross-area callers, owning area and stamp, docs that
    mention its path. Lists are cut to ``top``; counts are whole."""
    ws = nav.ws
    info = nav.info(path)
    names = nav.decl_names(path)
    indexed = path in nav.infos
    usable = sorted(nav.graph.names_of(path)) if indexed else []
    fi = nav.graph.fanin(path) if indexed else None
    prod = sorted(fi.prod) if fi else []
    tests = sorted(fi.test) if fi else []
    if not tests and names:  # graph ignores short/ambiguous names; fall back to a direct scan
        tests = sorted(p for p, i in nav.infos.items() if nav.is_test(p) and p != path and set(names) & i.idents)
    importers = sorted(nav.importers(path), key=lambda p: (nav.is_test(p), p)) if indexed else []
    cross = nav.graph.cross_areas(path) if fi and ws.areas else []
    a, _ = owner_of(path, ws.areas)
    unit = unit_of(path, a) if a else None
    stamp = None
    if unit and unit in ws.units:
        rec = ws.stamps.units.get(unit)
        stamp = "none" if not rec else ("current" if rec.get("surface") == ws.unit_hash(unit) else "changed")
    base = path.rsplit("/", 1)[-1]
    mentions = [m for m in nav.mentions(base) if m.path != path]
    mention_files = sorted({m.path for m in mentions})
    return {"kind": "file", "path": path, "lang": info.lang, "line_count": info.line_count,
            "declares": names, "fanin_names": usable, "test": nav.is_test(path),
            "fanin": {"prod": len(prod), "test": len(tests), "prod_files": prod[:top], "test_files": tests[:top]},
            "importers": {"count": len(importers), "files": importers[:top]},
            "cross_areas": cross, "area": a.name if a else None, "area_file": a.file if a else None,
            "unit": unit, "stamp": stamp,
            "mentions": {"count": len(mentions), "file_count": len(mention_files), "files": mention_files[:top]}}


def impact_symbol(nav: Nav, spec: str, top: int = 10, sites: list[Site] | None = None) -> dict:
    """What changing a name reaches: its definitions, reference sites by area, the production
    and test files that use it, and docs or contracts that mention it. ``sites`` passes
    ``nav.ref_sites(spec)`` when the caller already has them."""
    defs = nav.find_symbols(spec)
    if sites is None:
        sites = nav.ref_sites(spec)
    last = spec.rsplit(".", 1)[-1]
    if not defs and not sites:
        raise TopomarkError("NOT_FOUND", f"{spec!r} is neither a file nor a declared name (try `topomark find {last}`)")
    by_area: Counter = Counter()
    files_by_area: dict[str, set[str]] = {}
    for s in sites:
        if not s.test:
            by_area[s.group] += 1
            files_by_area.setdefault(s.group, set()).add(s.path)
    test_files = sorted({s.path for s in sites if s.test})
    prod_files = sorted({s.path for s in sites if not s.test})
    mentions = nav.mentions(spec) if "." in spec else []
    if not mentions:
        mentions = nav.mentions(last)
    def_files = {p for p, _ in defs}
    mentions = [m for m in mentions if m.path not in def_files]
    return {"kind": "symbol", "name": spec,
            "definitions": [{"path": p, "qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end,
                             "signature": s.signature} for p, s in defs],
            "refs": {"sites": len(sites), "prod_files": len(prod_files), "test_files": len(test_files),
                     "by_area": [{"group": g, "sites": n, "files": len(files_by_area[g])}
                                 for g, n in by_area.most_common()]},
            "callers": prod_files[:top], "tests": test_files[:top],
            "mentions": {"count": len(mentions), "files": sorted({m.path for m in mentions})[:top],
                         "lines": [m.to_json() for m in mentions[:top]]}}


def code_map_row(nav: Nav, path: str) -> dict:
    """Where the code map documents ``path``: area name and file, unit, review-stamp state
    (``current``, ``changed``, ``none``) and the unit's row as written (or None)."""
    ws = nav.ws
    empty = {"name": None, "file": None, "unit": None, "stamp": None, "row": None, "code_map": bool(ws.areas)}
    if not ws.areas:
        return empty
    a, _ = owner_of(path, ws.areas)
    if a is None:
        return empty
    unit = unit_of(path, a)
    stamp = None
    if unit in ws.units:
        rec = ws.stamps.units.get(unit)
        stamp = "none" if not rec else ("current" if rec.get("surface") == ws.unit_hash(unit) else "changed")
    row = next((ln.strip() for ln in a.text.split("\n") if ln.lstrip().startswith("|") and f"`{unit}`" in ln), None)
    return {"name": a.name, "file": a.file, "unit": unit, "stamp": stamp, "row": row, "code_map": True}


# ---------------------------------------------------------------- git
def changed_files(ctx, staged: bool = False, since: str | None = None) -> list[str]:
    """Repo paths that differ from HEAD (or the index, or ``since``), untracked files included
    unless ``staged``. NUL-separated git output, so unusual names come back as they are.
    An unknown ``since`` is NOT_FOUND."""
    root = ctx.root

    def names(cmd: str, *args: str) -> list[str]:
        return repo.git(root, cmd, "-z", *args, check=False).split("\0")

    if since:
        if not repo.git(root, "rev-parse", "--verify", "-q", f"{since}^{{commit}}", check=False).strip():
            raise TopomarkError("NOT_FOUND", f"unknown revision: {since}")
        out = names("diff", "--name-only", since)
    elif staged:
        out = names("diff", "--name-only", "--cached")
    else:
        head_ok = repo.git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        out = names("diff", "--name-only", "HEAD") if head_ok else names("ls-files")
    if not staged:
        out += names("ls-files", "--others", "--exclude-standard")
    return list(dict.fromkeys(f for f in out if f))


# ---------------------------------------------------------------- tests
def _attr_name(attr: str) -> str:
    a = attr.strip().lstrip("[@").rstrip("]")
    a = a.split("(", 1)[0].strip()
    return a.rsplit(".", 1)[-1].lower() if not a.startswith("pytest") else a.lower()


def is_test_symbol(sym: Symbol) -> bool:
    if sym.kind not in ("method", "function"):
        return False
    attrs = {_attr_name(a) for a in sym.attrs}
    if attrs & TEST_ATTRS or any(a.startswith("pytest.mark") for a in attrs):
        return True
    n = sym.name
    return n.startswith("test_") or n.startswith("test") and n[4:5].isupper() or \
        (n.startswith("Test") and (n[4:5].isupper() or n[4:5] == "_"))


def test_methods(info: FileInfo) -> list[Symbol]:
    found = [s for s in info.symbols if is_test_symbol(s)]
    classes_with = {s.container for s in found}
    for s in info.symbols:
        cls = s.container.rsplit(".", 1)[-1]
        if (s.kind == "method" and s.exported and s.container not in classes_with
                and re.search(r"Tests?$|Spec$", cls) and not s.name.startswith(("setUp", "tearDown", "SetUp", "TearDown"))):
            found.append(s)
    return sorted(found, key=lambda s: s.start)


def test_classes(info: FileInfo) -> list[str]:
    return sorted({s.container for s in test_methods(info) if s.container})


def pick_tests(nav: Nav, path: str, names: list[str]) -> TestPick | None:
    """Test methods in ``path`` whose body mentions any of ``names``."""
    info = nav.infos.get(path) or nav.info(path)
    hit = [n for n in names if n in info.idents]
    if not hit:
        return None
    mlines = nav.masked_lines(path)
    rxs = [word_rx(n) for n in hit]
    pick = TestPick(path, names=hit)
    methods = test_methods(info)
    for s in methods:
        body = "\n".join(mlines[s.start - 1:s.end])
        if any(rx.search(body) for rx in rxs):
            pick.methods.append((s.container, s.name))
    if not pick.methods:
        classes = test_classes(info)
        if classes:
            pick.classes = classes
            pick.reason = "names used outside test bodies (fields, setup)"
        else:
            pick.whole_file = True
            pick.reason = "no test methods detected"
    else:
        pick.classes = sorted({c for c, _ in pick.methods if c})
    return pick


def whole_test_file(nav: Nav, path: str, reason: str) -> TestPick:
    info = nav.infos.get(path) or nav.info(path)
    classes = test_classes(info)
    if classes:
        return TestPick(path, classes=classes, reason=reason)
    return TestPick(path, whole_file=True, reason=reason)


MAX_CALLERS = 30  # more callers than this: the change is too central to pick tests by name; run the suite
_TEST_FILE_NAME = re.compile(r"(?:test_.*|.*_test|.*[._-](?:test|spec)|.*Tests?|.*Spec)\.\w+")


def runnable_test(nav: Nav, path: str) -> bool:
    """A test file a runner can run: it declares test functions, or is named like a test
    (``test_x.py``, ``x.test.ts``, ``XTests.cs``). Other files under test patterns (harnesses,
    conftest, fixtures) are support code."""
    info = nav.infos.get(path)
    return info is not None and (bool(test_methods(info)) or bool(_TEST_FILE_NAME.fullmatch(path.rsplit("/", 1)[-1])))


def _merge_pick(picks: dict[str, TestPick], pk: TestPick) -> None:
    """Merge a second pick of the same test file; the broader selection wins
    (whole file > whole classes > methods)."""
    old = picks.get(pk.path)
    if old is None:
        picks[pk.path] = pk
        return
    if old.whole_file or old.reason == "changed test file":
        return
    names = sorted(set(old.names) | set(pk.names))
    if pk.whole_file:
        picks[pk.path] = pk
        pk.names = names
        return
    if not pk.methods and old.methods:  # the new pick runs whole classes: widen
        old.methods, old.reason, old.via = [], pk.reason, pk.via
    elif old.methods:
        for m in pk.methods:
            if m not in old.methods:
                old.methods.append(m)
    old.classes = sorted(set(old.classes) | set(pk.classes))
    old.names = names


def _pick_direct(nav: Nav, path: str, names: list[str], tests: list[str], picks: dict[str, TestPick],
                 via: list[str]) -> bool:
    """Pick the tests that mention ``names`` (declared by ``path``); True if any was found.
    Only runnable test files count: a shared harness or fixture module that mentions the names
    is support code, and the tests that use it are found through it."""
    if not names:
        return False
    wanted = set(names)
    found = False
    for t in tests:
        if t == path or not (wanted & nav.infos[t].idents) or not runnable_test(nav, t):
            continue
        pk = pick_tests(nav, t, names)
        if pk is None:
            continue
        found = True
        if via:
            pk.via = list(via)
            pk.reason = "via " + " → ".join(via) + (f"; {pk.reason}" if pk.reason else "")
        _merge_pick(picks, pk)
    return found


def name_callers(nav: Nav, path: str) -> list[str]:
    """Production files that use a name ``path`` declares (one hop on the reference graph):
    distinctive names only (``Graph.usable``), files that declare the same name left out."""
    g = nav.graph
    out: set[str] = set()
    for n in nav.decl_names(path):
        if n not in g.usable:
            continue
        out |= {f for f in g.ident_files.get(n, ()) if f != path and f not in g.tests and f not in g.declared[n]}
    return sorted(out)


def passthrough(nav: Nav, path: str) -> bool:
    """A module that declares nothing of its own and only imports or re-exports: an
    ``index.ts`` barrel, an ``__init__.py`` that gathers names."""
    info = nav.infos.get(path)
    return info is not None and bool(info.imports) and all(s.kind == "exports" for s in info.symbols)


def _callers(nav: Nav, path: str, depth: int) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]], bool]:
    """Callers of ``path`` up to ``depth`` hops: import edges, plus name edges from ``path`` itself.

    Returns the production callers and the test files that import ``path`` or a caller, each
    with the chain of files from ``path`` to it, and whether the search stopped at
    MAX_CALLERS. Barrels and test support code (a shared harness) are walked through without
    using up a hop; test support is never selected itself."""
    seen = {path}
    callers: list[tuple[str, list[str]]] = []
    importing: list[tuple[str, list[str]]] = []
    queue: deque[tuple[str, list[str], int]] = deque([(path, [], 0)])
    while queue:
        f, chain, hops = queue.popleft()
        step = list(nav.importers(f)) + (name_callers(nav, path) if f == path else [])
        for c in step:
            if c in seen:
                continue
            test = nav.is_test(c)
            if test and runnable_test(nav, c):
                seen.add(c)
                importing.append((c, chain))
                continue
            free = test or passthrough(nav, c)
            if hops + (0 if free else 1) > depth:
                continue
            seen.add(c)
            if not test:
                callers.append((c, chain + [c]))
                if len(callers) > MAX_CALLERS:
                    return callers, importing, True
            if free:
                queue.appendleft((c, chain + [c], hops))
            else:
                queue.append((c, chain + [c], hops + 1))
    return callers, importing, False


def select_tests(nav: Nav, paths: list[str], depth: int = 2) -> TestSelection:
    """The tests that cover changed files.

    Changed test files are selected whole; changed test support code (a harness, conftest, a
    fixture module: under test patterns but not runnable) is treated like production code. For a
    production file, the tests whose bodies mention a name it declares; when there are none, its callers up to ``depth`` hops away
    (import statements, transitively; plus one hop of name references), the test files that
    import any of them (whole), and the tests that mention the callers' distinctive names
    (``Graph.usable``), marked ``via``. ``depth=0`` is the name match alone.
    More than MAX_CALLERS callers stops the search: the file goes to ``limited`` and stays
    uncovered (run the whole suite). When files stay uncovered and the repo loads modules
    by computed names, ``dynamic_loaders`` lists the files a static search cannot see through."""
    sel = TestSelection(depth=max(0, depth))
    tests = [p for p in nav.infos if nav.is_test(p)]
    for p in paths:
        if p not in nav.infos:
            continue
        if nav.is_test(p) and runnable_test(nav, p):
            sel.picks[p] = whole_test_file(nav, p, "changed test file")
            continue
        if not nav.is_code(p):
            continue
        names = nav.decl_names(p)
        sel.names_of[p] = names
        if not _pick_direct(nav, p, names, tests, sel.picks, []):
            sel.uncovered.append(p)
    if sel.depth:
        still = []
        for p in sel.uncovered:
            callers, importing, limited = _callers(nav, p, sel.depth)
            if limited:
                sel.limited.append(p)
                still.append(p)
                continue
            found = False
            for t, chain in importing:
                pk = whole_test_file(nav, t, f"imports {chain[-1] if chain else p}"
                                     + (" via " + " → ".join(chain[:-1]) if len(chain) > 1 else ""))
                pk.via = list(chain)
                _merge_pick(sel.picks, pk)
                found = True
            usable = nav.graph.usable
            for c, chain in callers:
                names = [n for n in nav.decl_names(c) if n in usable]
                found = _pick_direct(nav, c, names, tests, sel.picks, chain) or found
            if not found:
                still.append(p)
        sel.uncovered = still
    if sel.uncovered:
        sel.dynamic_loaders = nav.dynamic_loaders()
    return sel


def runner_for(path: str, runners: list[TestRunner]) -> TestRunner | None:
    for r in runners:
        if path.startswith(r.match) or repo.matches(path, r.match):
            return r
    return None


def runner_commands(runners: list[TestRunner], picks: list[TestPick]) -> tuple[list[dict], list[TestPick]]:
    """Commands per ``[[tests.runner]]`` for these picks (first matching runner wins), and the
    picks no runner matches."""
    groups: dict[int, list[TestPick]] = {}
    unmatched = []
    for pk in picks:
        r = runner_for(pk.path, runners)
        if r is None:
            unmatched.append(pk)
        else:
            groups.setdefault(runners.index(r), []).append(pk)
    commands = []
    for idx in sorted(groups):
        r = runners[idx]
        cmds, gran = render_runner(r, groups[idx])
        commands.append({"runner": r.match, "names": gran, "files": [pk.path for pk in groups[idx]], "commands": cmds})
    return commands, unmatched


def _items(picks: list[TestPick], gran: str) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for p in picks:
        if gran == "method" and p.methods and not p.whole_file:
            for c, m in p.methods:
                key = (p.path, c, m)
                if key not in seen:
                    seen.add(key)
                    out.append({"file": p.path, "class": c, "method": m, "name": f"{c}.{m}" if c else m})
            continue
        if gran in ("method", "class") and p.classes and not p.whole_file:
            for c in p.classes:
                key = (p.path, c, "")
                if key not in seen:
                    seen.add(key)
                    out.append({"file": p.path, "class": c, "method": "", "name": c})
            continue
        key = (p.path, "", "")
        if key not in seen:
            seen.add(key)
            out.append({"file": p.path, "class": "", "method": "", "name": p.path})
    return out


_PLACEHOLDER = re.compile(r"\{(file|files|class|method|names)\}")
_SEPARATORS = ("::", ".", "#", ":")   # what an empty {class} or {method} takes with it


def _shell_state(text: str, state: str) -> str:
    """The POSIX shell quote state ("", "'" or '"') after ``text``, starting in ``state``."""
    i = 0
    while i < len(text):
        c = text[i]
        if state == "'":
            if c == "'":
                state = ""
        elif c == "\\":
            i += 1
        elif state == '"':
            if c == '"':
                state = ""
        elif c in "'\"":
            state = c
        i += 1
    return state


def _shell_quote(value: str, state: str) -> str:
    """``value`` made literal for the POSIX shell where it lands: ``shlex.quote`` outside quotes
    (a plain path or name comes back unchanged), escapes inside a template's own quotes."""
    import shlex

    if not value:
        return value
    if state == "'":
        return value.replace("'", "'\\''")
    if state == '"':
        return re.sub(r'([\\"$`])', r"\\\1", value)
    return shlex.quote(value)


def fill_template(tmpl: str, values: dict[str, str | list[str]], join: str = " ") -> str:
    """A runner command: placeholders replaced by shell-quoted values (list values quoted one by
    one, then joined with ``join``). An empty ``{class}`` or ``{method}`` drops with the separator
    before it (``::``, ``.``, ``#``, ``:``), or after it when none precedes, so
    ``{file}::{class}::{method}`` gives ``x.py::m`` or ``x.py`` and nothing else in the template
    is touched. Quoting is POSIX shell quoting."""
    parts = _PLACEHOLDER.split(tmpl)
    lits, names = parts[0::2], parts[1::2]
    for k, name in enumerate(names):
        if name not in ("class", "method") or values.get(name):
            continue
        sep = next((x for x in _SEPARATORS if lits[k].endswith(x)), None)
        if sep:
            lits[k] = lits[k][: -len(sep)]
            continue
        sep = next((x for x in _SEPARATORS if lits[k + 1].startswith(x)), None)
        if sep:
            lits[k + 1] = lits[k + 1][len(sep):]
    out: list[str] = []
    state = ""
    for k, lit in enumerate(lits):
        out.append(lit)
        state = _shell_state(lit, state)
        if k < len(names):
            v = values.get(names[k], "")
            out.append(join.join(_shell_quote(x, state) for x in v) if isinstance(v, list) else _shell_quote(v, state))
    return "".join(out).rstrip()


def render_runner(runner: TestRunner, picks: list[TestPick]) -> tuple[list[str], str]:
    """Commands for one runner, and the granularity actually used."""
    gran = runner.names
    items = _items(picks, gran)
    if len(items) > runner.max_names and gran != runner.fallback:
        gran = runner.fallback
        items = _items(picks, gran)
        if len(items) > runner.max_names and gran == "class":
            gran = "file"
            items = _items(picks, gran)
    files = sorted({p.path for p in picks})
    tmpl = runner.command
    per_item = any(k in tmpl for k in ("{file}", "{class}", "{method}")) and "{names}" not in tmpl \
        and "{files}" not in tmpl
    if per_item:
        cmds = []
        for it in items:
            cmd = fill_template(tmpl, {"file": it["file"], "class": it["class"] or "", "method": it["method"] or ""})
            if cmd not in cmds:
                cmds.append(cmd)
        return cmds, gran
    cmd = fill_template(tmpl, {"names": [it["name"] for it in items], "files": files,
                               "file": files[0] if files else "", "class": "", "method": ""}, runner.join)
    return [cmd], gran


def _name_edge_weight(name: str, referrers: int, focus_names: set[str]) -> float:
    """Aider-style edge weight: rare, distinctive names count more than common words."""
    w = 1.0 / math.sqrt(max(1, referrers))
    if re.fullmatch(r"[a-z][a-z0-9]*", name):  # `fetch`, `sha256`: plain words match everywhere
        w *= 0.1
    if name.startswith("_"):
        w *= 0.1
    if name in focus_names:
        w *= 10.0
    return w


def pagerank_files(nav: Nav, focus_files: set[str], candidates: set[str], focus_names: set[str] | None = None,
                   iterations: int = 40, damping: float = 0.85) -> dict[str, float]:
    """Personalised PageRank over the reference graph with IDF-weighted edges.

    ``Graph.pagerank`` weights every usable name the same, which lets a file of
    generic helpers (``fetch``, ``report``) outrank the real hubs; here a name used
    by N files contributes 1/sqrt(N) per edge and plain lowercase words 10x less.
    Edges only join files of the same language: a Python ``re.compile`` is not a
    reference to a TypeScript ``compile``."""
    g = nav.graph
    infos = nav.infos
    focus_names = focus_names or set()
    nodes = [p for p in infos if p in candidates or p in focus_files]
    if not nodes:
        return {}
    index = {p: i for i, p in enumerate(nodes)}
    lang = [infos[p].lang for p in nodes]
    edges: dict[int, dict[int, float]] = {}  # referrer → {declaring file: weight}, by node index
    for d, path in enumerate(nodes):
        for n in g.names_of(path):
            refs = g.ident_files.get(n, ())
            w = _name_edge_weight(n, len(refs), focus_names)
            decl = g.declared.get(n, ())
            for r in refs:
                ri = index.get(r)
                if ri is not None and ri != d and r not in decl and lang[ri] == lang[d]:
                    e = edges.setdefault(ri, {})
                    e[d] = e.get(d, 0.0) + w
    pers = {f: 1.0 for f in focus_files if f in index}
    total = len(pers) or len(nodes)
    teleport = [(pers.get(k, 0.0) if pers else 1.0) / total for k in nodes]
    rank = list(teleport)
    adj = [(src, sum(dst.values()), list(dst.items())) for src, dst in edges.items()]
    dangling_nodes = [i for i in range(len(nodes)) if i not in edges]
    n = len(nodes)
    for _ in range(iterations):
        dangling = sum(rank[i] for i in dangling_nodes)
        base = 1 - damping + damping * dangling
        nxt = [base * t for t in teleport]
        for src, out_weight, dsts in adj:
            share = damping * rank[src] / out_weight
            for dst, w in dsts:
                nxt[dst] += share * w
        diff = sum(abs(a - b) for a, b in zip(nxt, rank))
        rank = nxt
        if diff < 1e-9 * n:
            break
    return dict(zip(nodes, rank))


def declares(info: FileInfo, name: str) -> bool:
    """Any symbol (nested ones too) named ``name``; a cached file answers without building symbols."""
    raw = getattr(info, "symbol_tuples", None)
    if raw is not None:
        return any(t[1] == name for t in raw)
    return any(s.name == name for s in info.symbols)


def outline_size(info: FileInfo) -> int:
    """How many declarations an outline lists (namespaces aside), without building symbols
    for a cached file."""
    raw = getattr(info, "symbol_tuples", None)
    if raw is not None:
        return sum(1 for t in raw if t[0] != "namespace")
    return sum(1 for s in info.symbols if s.kind != "namespace")


def name_weight_bound(nav: Nav) -> float:
    """An upper bound of ``name_weight`` over every symbol (same arithmetic, the largest count)."""
    w = 1.0 + math.log1p(max(nav.ident_counts.values(), default=0))
    return w * 2.0 * 3.0


def name_weight(nav: Nav, sym: Symbol) -> float:
    w = 1.0 + math.log1p(nav.ident_counts.get(sym.name, 0))
    if sym.exported:
        w *= 2.0
    if is_type_kind(sym.kind):
        w *= 3.0
    if sym.name.startswith("_"):
        w *= 0.3
    return w
