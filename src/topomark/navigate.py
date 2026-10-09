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
* ``Nav.importers`` answers "who imports this file" from the import edges
  ``imports.py`` resolves, separately from the name-based reference graph.
* ``impact_file`` / ``impact_symbol`` build the ``impact`` summaries as dicts.
* ``changed_files`` asks git what changed (working tree, index, or since a rev).
* ``estimate_tokens`` is the one token estimate (``contract.estimate_tokens``).

What used to live here too: masking (``masking.py``), import resolution
(``imports.py``), test selection (``testsel.py``), runner commands
(``runners.py``) and ``map``'s ranking (``ranking.py``).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property

from . import repo
from .contract import estimate_tokens as estimate_tokens
from .docs import is_test, owner_of, unit_of
from .errors import TopomarkError
from .imports import resolve_imports, reverse_edges
from .lang.base import DYNAMIC, FileInfo, Symbol
from .lang.scan import Masked
from .masking import NON_CODE_LANGS, mask_file, word_rx
from .workspace import Workspace

MENTION_EXT = (".md", ".markdown", ".txt", ".rst", ".adoc", ".html", ".json", ".jsonc", ".yaml", ".yml", ".toml")
LINE_MAX = 160


def clip(s: str, n: int = LINE_MAX) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


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
            path = repo.user_path(self.ctx.root, path)
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


def declares(info: FileInfo, name: str) -> bool:
    """Any symbol (nested ones too) named ``name``; a cached file answers without building symbols."""
    raw = getattr(info, "symbol_tuples", None)
    if raw is not None:
        return any(t[1] == name for t in raw)
    return any(s.name == name for s in info.symbols)


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
