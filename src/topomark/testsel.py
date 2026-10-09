"""Test selection: which tests cover a set of changed files.

``select_tests`` first looks for tests that mention a changed file's names, then walks
import edges and name references to the file's callers (``--depth`` hops) and takes the
tests that reach those. ``pick_tests`` narrows a test file to the methods whose bodies
mention a name. Everything is a text match, like the reference graph.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .lang.base import FileInfo, Symbol
from .masking import word_rx

if TYPE_CHECKING:
    from .navigate import Nav

TEST_ATTRS = frozenset({"test", "unitytest", "testcase", "testcasesource", "theory", "fact", "testmethod",
                        "parameterizedtest", "valuesource", "testfixturesource", "pytest.mark.parametrize"})


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
