"""Shared logic for the navigation commands (outline, symbol, find, refs, impact,
tests-for, map).

Everything here is approximate by design, like the reference graph: a reference
is a word-boundary match of an identifier in *masked* text (comments and string
literals blanked), not a resolved binding. That is fast, language-agnostic and
right often enough for an agent deciding what to read next.

* ``Nav`` wraps a ``Workspace`` and caches masked text per file. Single-file
  commands go through ``Nav.info`` (one parse, no repo scan); only commands that
  need the whole repo touch ``Nav.infos``.
* ``resolve`` turns ``file#Qual.Name`` or a bare ``Name`` into symbols.
* ``changed_files`` asks git what changed (working tree, index, or since a rev).
* ``test_methods`` / ``render_runner`` pick test functions and print commands.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property

from . import repo
from .config import TestRunner
from .docs import is_test, owner_of
from .errors import TopomarkError
from .lang.base import FileInfo, Symbol
from .lang.scan import Masked, mask
from .workspace import Workspace

# Languages whose text is prose or data: never masked, never a reference site.
NON_CODE_LANGS = frozenset({"markdown", "data", "text", "large"})
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

    def to_json(self) -> dict:
        return {"path": self.path, "whole_file": self.whole_file, "reason": self.reason, "names": self.names,
                "classes": self.classes,
                "methods": [f"{c}.{m}" if c else m for c, m in self.methods]}


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
        return (self.ctx.root / path).is_file()

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
        from .lang import registry
        from .lang.python import SYNTAX as PY_SYNTAX

        text = self.ctx.read(path)
        adapter = registry.adapter_for(path)
        lang = getattr(adapter, "name", "")
        if lang in NON_CODE_LANGS:
            m = Masked(text, text)
        else:
            syntax = getattr(adapter, "syntax", None) or PY_SYNTAX
            premask = getattr(adapter, "premask", None)
            pre = premask(text) if callable(premask) else text
            m = mask(pre, syntax)
            m.original = text
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
            if last not in info.idents and not any(s.name == last for s in info.symbols):
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
        c: Counter = Counter()
        for info in self.infos.values():
            c.update(info.idents)
        return c

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


# ---------------------------------------------------------------- git
def changed_files(ctx, staged: bool = False, since: str | None = None) -> list[str]:
    root = ctx.root
    if since:
        out = repo.git(root, "diff", "--name-only", since, check=False).split("\n")
    elif staged:
        out = repo.git(root, "diff", "--name-only", "--cached", check=False).split("\n")
    else:
        head_ok = repo.git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        if head_ok:
            out = repo.git(root, "diff", "--name-only", "HEAD", check=False).split("\n")
        else:
            out = repo.git(root, "ls-files", check=False).split("\n")
    if not staged:
        out += repo.git(root, "ls-files", "--others", "--exclude-standard", check=False).split("\n")
    seen: list[str] = []
    for f in out:
        f = f.strip()
        if f and f not in seen:
            seen.append(f)
    return seen


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


def runner_for(path: str, runners: list[TestRunner]) -> TestRunner | None:
    for r in runners:
        if path.startswith(r.match) or repo.matches(path, r.match):
            return r
    return None


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
            cmd = tmpl.replace("{file}", it["file"]).replace("{class}", it["class"] or "").replace(
                "{method}", it["method"] or "")
            cmd = re.sub(r"(?:::|[.#:])+(?=\s|$|[\"'])", "", cmd)  # `x.py::Cls::` after a fallback
            if cmd not in cmds:
                cmds.append(cmd)
        return cmds, gran
    cmd = (tmpl.replace("{names}", runner.join.join(it["name"] for it in items))
           .replace("{files}", runner.join.join(files))
           .replace("{file}", files[0] if files else "")
           .replace("{class}", "").replace("{method}", ""))
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
    focus_names = focus_names or set()
    nodes = [p for p in nav.infos if p in candidates or p in focus_files]
    if not nodes:
        return {}
    node_set = set(nodes)
    edges: dict[str, dict[str, float]] = defaultdict(dict)
    for d in nodes:
        for n in g.names_of(d):
            refs = g.ident_files.get(n, ())
            w = _name_edge_weight(n, len(refs), focus_names)
            lang = nav.infos[d].lang
            for r in refs:
                if r != d and r in node_set and r not in g.declared[n] and nav.infos[r].lang == lang:
                    edges[r][d] = edges[r].get(d, 0.0) + w
    pers = {f: 1.0 for f in focus_files if f in node_set}
    total = len(pers) or len(nodes)
    teleport = {k: (pers.get(k, 0.0) if pers else 1.0) / total for k in nodes}
    rank = dict(teleport)
    out_weight = {src: sum(dst.values()) for src, dst in edges.items()}
    n = len(nodes)
    for _ in range(iterations):
        dangling = sum(rank[k] for k in nodes if k not in out_weight)
        nxt = {k: (1 - damping + damping * dangling) * teleport[k] for k in nodes}
        for src, dsts in edges.items():
            share = damping * rank[src] / out_weight[src]
            for dst, w in dsts.items():
                nxt[dst] += share * w
        diff = sum(abs(nxt[k] - rank[k]) for k in nodes)
        rank = nxt
        if diff < 1e-9 * n:
            break
    return rank


def name_weight(nav: Nav, sym: Symbol) -> float:
    w = 1.0 + math.log1p(nav.ident_counts.get(sym.name, 0))
    if sym.exported:
        w *= 2.0
    if is_type_kind(sym.kind):
        w *= 3.0
    if sym.name.startswith("_"):
        w *= 0.3
    return w
