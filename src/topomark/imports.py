"""Import statements resolved to repo files, approximately: Python, JS/TS, C-family includes, Dart,
Go, Rust, Java and Kotlin. C# and Swift name namespaces and modules, never files: no edges.

Import edges answer "who imports this file" for ``impact`` and let ``tests-for`` walk
from a changed file to the tests that load it. They are kept apart from the name-based
reference graph (``graph.py``), whose fan-in numbers they never change.
"""

from __future__ import annotations

import posixpath
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable

from .lang.base import DYNAMIC, FileInfo

PY_EXT = (".py", ".pyi")
JS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
C_EXT = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".m", ".mm")
DART_EXT = (".dart",)
GO_EXT = (".go",)
RUST_EXT = (".rs",)
JVM_EXT = (".java", ".kt", ".kts")
PACKAGE_MAX = 40  # files one Go package or one `import a.b.*` may stand for
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
        for a, b in zip(here, c.split("/")[:-1], strict=False):
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
    suffix. Bare package names (``react``) and computed names stay unresolved.
    C, C++, Objective-C: ``#include "x.h"`` from the includer's folder, else by path suffix
    (an include path such as ``-Iinclude``), nearest to the includer.
    Dart: relative URIs; ``package:app/x.dart`` as ``lib/x.dart`` by path suffix.
    Go: an import path is a folder, every non-test file of which is imported. Which folder is
    learned from the repository's own imports (``learn_go``): the module prefix is the part
    of the path in front of a folder that exists, and it counts when two imports agree on it
    or the folder is matched by two or more path segments, so ``github.com/x/y/util`` is not
    this repository's ``util/``.
    Rust: ``mod name;`` as ``name.rs`` or ``name/mod.rs`` beside the module; ``crate::``,
    ``super::`` and ``self::`` paths to the longest module file they name.
    Java and Kotlin: ``a.b.C`` as ``a/b/C.java`` or ``.kt`` by path suffix (a static member or
    nested class by its outer class); ``a.b.*`` as the files of that folder."""

    def __init__(self, files: Iterable[str]) -> None:
        self.files = set(files)
        self.py: dict[str, list[str]] = defaultdict(list)
        self.js: dict[str, list[str]] = defaultdict(list)
        self.whole: dict[str, list[str]] = defaultdict(list)    # C and Dart: path suffix, extension kept
        self.jvm: dict[str, list[str]] = defaultdict(list)      # Java and Kotlin: path suffix without extension
        self.folders: dict[str, list[str]] = defaultdict(list)  # Go and JVM folder → its files
        self.folder_suffix: dict[str, list[str]] = defaultdict(list)  # folder suffix → folders
        self._go: dict[str, tuple[str, str, str, int]] | None = None
        self._go_ok: set[tuple[str, str]] = set()
        for f in sorted(self.files):
            low = f.lower()
            if low.endswith(PY_EXT):
                table, stem = self.py, _module_stem(f, "__init__")
            elif low.endswith(JS_EXT):
                table, stem = self.js, _module_stem(f, "index")
            elif low.endswith(C_EXT + DART_EXT):
                table, stem = self.whole, f
            elif low.endswith(JVM_EXT):
                table, stem = self.jvm, f.rsplit(".", 1)[0]
                self.folders[posixpath.dirname(f)].append(f)
            elif low.endswith(GO_EXT):
                if not low.endswith("_test.go"):
                    self.folders[posixpath.dirname(f)].append(f)
                continue
            else:
                continue
            parts = stem.split("/") if stem else []
            for k in range(len(parts)):
                table["/".join(parts[k:])].append(f)
        for folder in sorted(self.folders):
            parts = folder.split("/") if folder else []
            for k in range(len(parts)):
                self.folder_suffix["/".join(parts[k:])].append(folder)

    def resolve(self, importer: str, spec: str) -> str | None:
        """The one file ``spec`` names for ``importer`` (the first, for a Go package or ``a.b.*``)."""
        found = self.resolve_all(importer, spec)
        return found[0] if found else None

    def resolve_all(self, importer: str, spec: str) -> list[str]:
        if not spec or spec == DYNAMIC:
            return []
        low = importer.lower()
        one: str | None = None
        if low.endswith(PY_EXT):
            one = self._python(importer, spec)
        elif low.endswith(JS_EXT):
            one = self._js(importer, spec)
        elif low.endswith(C_EXT):
            one = self._c(importer, spec)
        elif low.endswith(DART_EXT):
            one = self._dart(importer, spec)
        elif low.endswith(RUST_EXT):
            one = self._rust(importer, spec)
        elif low.endswith(GO_EXT):
            return self._go_package(spec)
        elif low.endswith(JVM_EXT):
            return self._jvm(importer, spec)
        return [one] if one else []

    # ---- C family, Dart
    def _c(self, importer: str, spec: str) -> str | None:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
        if target in self.files and target.lower().endswith(C_EXT):
            return target
        if spec.startswith(("/", "../")) or "/../" in spec:
            return None
        return _nearest(importer, [c for c in self.whole.get(posixpath.normpath(spec), []) if c.lower().endswith(C_EXT)])

    def _dart(self, importer: str, spec: str) -> str | None:
        if spec.startswith("package:"):
            rest = spec[len("package:"):].split("/", 1)
            return _nearest(importer, self.whole.get("lib/" + rest[1], [])) if len(rest) == 2 else None
        if ":" in spec:  # dart:io and other schemes
            return None
        target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
        return target if target in self.files and target.lower().endswith(DART_EXT) else None

    # ---- Go
    def _go_match(self, spec: str) -> tuple[str, str, str, int] | None:
        """(module prefix, module root folder, package folder, segments matched) for the longest
        tail of ``spec`` that is a folder of Go files; None for the standard library (no dot in
        the first segment) and for a path no folder ends with."""
        parts = spec.split("/")
        if "." not in parts[0]:
            return None
        for k in range(1, len(parts)):
            tail = "/".join(parts[k:])
            folders = [d for d in self.folder_suffix.get(tail, []) if any(f.endswith(".go") for f in self.folders[d])]
            if folders:
                folder = min(folders, key=lambda d: (len(d), d))
                return "/".join(parts[:k]), folder[: len(folder) - len(tail)].rstrip("/"), folder, len(parts) - k
        return None

    def learn_go(self, specs: Iterable[str]) -> None:
        """Decide from every Go import in the repository which module prefixes are its own."""
        self._go = {}
        votes: Counter[tuple[str, str]] = Counter()
        for spec in set(specs):
            hit = self._go_match(spec)
            if hit:
                self._go[spec] = hit
                votes[(hit[0], hit[1])] += 1
        self._go_ok = {pm for pm, n in votes.items() if n >= 2} | {(h[0], h[1]) for h in self._go.values() if h[3] >= 2}

    def _go_package(self, spec: str) -> list[str]:
        if self._go is None:
            self.learn_go([spec])
        assert self._go is not None
        hit = self._go.get(spec) or self._go_match(spec)
        if hit is None or ((hit[0], hit[1]) not in self._go_ok and hit[3] < 2):
            return []
        return self.folders[hit[2]][:PACKAGE_MAX]

    # ---- Rust
    def _rs(self, target: str) -> str | None:
        for cand in (target + ".rs", target + "/mod.rs"):
            if cand in self.files:
                return cand
        return None

    def _rust(self, importer: str, spec: str) -> str | None:
        folder = posixpath.dirname(importer)
        stem = posixpath.basename(importer)[: -len(".rs")]
        # where this module's children live: beside lib.rs, main.rs and mod.rs, else in a folder of its name
        here = folder if stem in ("mod", "lib", "main") else posixpath.join(folder, stem)
        if spec.startswith("mod:"):
            return self._rs(posixpath.join(here, spec[len("mod:"):]))
        parts = spec.split("::")
        if parts[0] == "crate":
            dirs = folder.split("/")
            if "src" not in dirs:
                return None
            root = "/".join(dirs[: len(dirs) - dirs[::-1].index("src")])
            segs = parts[1:]
        else:
            root, segs = here, parts[1:]
            if parts[0] == "super":
                root = posixpath.dirname(root)
                while segs and segs[0] == "super":
                    root, segs = posixpath.dirname(root), segs[1:]
        for n in range(len(segs), 0, -1):
            found = self._rs(posixpath.join(root, *segs[:n]))
            if found:
                return found if found != importer else None
        return None

    # ---- Java, Kotlin
    def _jvm(self, importer: str, spec: str) -> list[str]:
        if spec.endswith(".*"):
            key = spec[:-2].replace(".", "/")
            folders = [d for d in self.folder_suffix.get(key, [])
                       if any(f.lower().endswith(JVM_EXT) for f in self.folders[d])]
            near = _nearest(importer, [d + "/_" for d in folders])  # compared as files inside each folder
            return [f for f in self.folders[near[:-2]] if f.lower().endswith(JVM_EXT)][:PACKAGE_MAX] if near else []
        parts = spec.split(".")
        for n in (len(parts), len(parts) - 1):  # a.b.C, then a.b.C.member or a.b.Outer.Inner
            if n >= 2:
                one = _nearest(importer, self.jvm.get("/".join(parts[:n]), []))
                if one:
                    return [one]
        return []

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
    resolver.learn_go(spec for path, info in infos.items() if path.lower().endswith(GO_EXT) for spec in info.imports)
    out: dict[str, list[str]] = {}
    for path, info in infos.items():
        found: list[str] = []
        for spec in info.imports:
            for f in resolver.resolve_all(path, spec):
                if f != path and f not in found:
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
