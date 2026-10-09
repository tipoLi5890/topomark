"""Import statements resolved to repo files (Python and JS/TS), approximately.

Import edges answer "who imports this file" for ``impact`` and let ``tests-for`` walk
from a changed file to the tests that load it. They are kept apart from the name-based
reference graph (``graph.py``), whose fan-in numbers they never change.
"""

from __future__ import annotations

import posixpath
import sys
from collections import defaultdict
from collections.abc import Iterable

from .lang.base import DYNAMIC, FileInfo

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
