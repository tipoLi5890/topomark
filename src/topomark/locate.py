"""From an error message or a stack trace to the code that produced it, for ``topomark locate``.

**Messages.** A message as printed rarely appears verbatim in the source: values were
interpolated (``f"stamps.json is format {v}; ..."``) and long strings are split across lines.
So the message is cut into overlapping word runs (three words, and two with half the weight),
each run is looked up as a literal in every parsed file, and a run found in only a few files
weighs more than one found everywhere (weight / number of files that contain it; for production
code only production files count, so a test quoting the message can't hide its source). Hits are
summed per enclosing symbol; a place that only a common two-word run reaches is dropped.
Production code ranks first, then tests, then docs and data files,
whatever the score: the goal is the code that printed the message, not the page that quotes it.
``--regex`` matches one pattern per line instead.

**Traces.** Frames are read from Python, Node/V8, Firefox/Safari, Java/Kotlin, C#, Dart, Go and
Rust traces, plus generic ``path:line`` (compiler errors, test failures). A frame's path maps to
a repo file by the longest path suffix shared with a git file (``/home/ci/x/src/app.py`` →
``src/app.py``); a bare file name matches by name and every candidate is listed. Paths outside
the repo (site-packages, node_modules, the runtime) are reported as skipped. Frames come back
innermost first, the order in which to read them.

Every file is read through ``Context.read``, so secret-looking paths are never opened.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .navigate import Nav

MAX_GRAMS = 80  # word runs looked up per message; a pasted log beyond that adds noise, not signal
RARE = 3        # a place matched only by a two-word run is kept when that run is in at most this many files


# ---------------------------------------------------------------- messages
def grams(message: str) -> list[tuple[str, float]]:
    """(literal, weight) to look up: three-word runs (1.0) and two-word runs (0.5); a message of
    three words or fewer is looked up whole."""
    words = message.split()
    if not words:
        return []
    if len(words) <= 3:
        return [(" ".join(words), 1.0)]
    out: list[tuple[str, float]] = []
    seen = set()
    for n, w in ((3, 1.0), (2, 0.5)):
        for i in range(len(words) - n + 1):
            g = " ".join(words[i:i + n])
            if g not in seen and len(g) >= 6:
                seen.add(g)
                out.append((g, w))
    return out[:MAX_GRAMS]


@dataclass
class Place:
    path: str
    line: int                 # the first matching line
    qualname: str = ""
    kind: str = ""
    start: int = 0
    end: int = 0
    score: float = 0.0
    matched: int = 0          # distinct word runs (or regex lines) found here
    text: str = ""
    group: str = "code"       # code | test | doc

    def to_json(self) -> dict:
        return {"path": self.path, "line": self.line, "qualname": self.qualname, "kind": self.kind,
                "start": self.start, "end": self.end, "score": round(self.score, 3), "matched": self.matched,
                "text": self.text, "group": self.group}


_TIER = {"code": 0, "test": 1, "doc": 2}


def _group(nav: Nav, path: str) -> str:
    from .masking import NON_CODE_LANGS

    info = nav.infos.get(path)
    if info is None or info.lang in NON_CODE_LANGS:
        return "doc"
    return "test" if nav.is_test(path) else "code"


def _starts(text: str) -> list[int]:
    out = [0]
    k = text.find("\n")
    while k >= 0:
        out.append(k + 1)
        k = text.find("\n", k + 1)
    return out


def find_message(nav: Nav, message: str, regex: bool = False) -> list[Place]:
    """Places whose source contains the message (or matches ``regex``), best first."""
    from .errors import TopomarkError
    from .navigate import clip, enclosing_symbol

    message = " ".join(message.split())
    rx = None
    looked: list[tuple[str, float]] = []
    if regex:
        try:
            rx = re.compile(message)
        except re.error as e:
            raise TopomarkError("USAGE", f"--regex: {e}") from e
    else:
        looked = grams(message)
    hits: dict[str, list[tuple[int, int]]] = {}   # path → [(line, gram index or -1)]
    df: dict[int, int] = defaultdict(int)        # files containing each run
    df_code: dict[int, int] = defaultdict(int)   # production code files containing each run
    groups: dict[str, str] = {}
    for path in sorted(nav.infos):
        try:
            text = nav.ctx.read(path)
        except (OSError, TopomarkError):
            continue
        found: list[tuple[int, int]] = []
        if rx is not None:
            for i, ln in enumerate(text.split("\n")):
                if rx.search(ln):
                    found.append((i + 1, -1))
        else:
            starts = None
            for gi, (g, _) in enumerate(looked):
                k = text.find(g)
                if k < 0:
                    continue
                df[gi] += 1
                if path not in groups:
                    groups[path] = _group(nav, path)
                if groups[path] == "code":
                    df_code[gi] += 1
                starts = starts or _starts(text)
                while k >= 0:
                    found.append((bisect_right(starts, k), gi))
                    k = text.find(g, k + 1)
        if found:
            hits[path] = found
    places: dict[tuple[str, str, int], Place] = {}
    seen: dict[tuple[str, str, int], set[int]] = defaultdict(set)
    strong: set[tuple[str, str, int]] = set()   # places with a three-word run, a whole message or a regex hit
    for path, found in hits.items():
        info = nav.infos[path]
        lines = None
        for line, gi in sorted(found):
            sym = enclosing_symbol(info, line)
            key = (path, sym.qualname if sym else "", sym.start if sym else 0)
            p = places.get(key)
            if p is None:
                lines = lines or nav.lines(path)
                p = places[key] = Place(path, line, sym.qualname if sym else "", sym.kind if sym else "",
                                        sym.start if sym else line, sym.end if sym else line,
                                        text=clip(lines[line - 1] if line <= len(lines) else "", 140),
                                        group=groups.get(path) or _group(nav, path))
            mark = gi if gi >= 0 else line
            if mark in seen[key]:
                continue
            seen[key].add(mark)
            p.matched += 1
            # rarity among the files of the place's own kind: tests and docs that quote a message
            # verbatim must not make the run look common to the code that printed it
            n = df_code[gi] if gi >= 0 and p.group == "code" else df.get(gi, 0)
            p.score += 1.0 if gi < 0 else looked[gi][1] / max(1, n)
            if gi < 0 or looked[gi][1] == 1.0 or n <= RARE:
                strong.add(key)
    # a lone two-word run found all over the repo ("this file") is no evidence
    out = [p for k, p in places.items() if k in strong or p.matched > 1]
    out.sort(key=lambda p: (_TIER[p.group], -round(p.score, 9), p.path, p.line))
    return out


# ---------------------------------------------------------------- traces
@dataclass
class Frame:
    raw: str                  # the trace line
    path: str                 # as written in the trace
    line: int
    func: str = ""
    fmt: str = ""
    hint: str = ""            # a relative path derived from a Java/Kotlin class name


_PY = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?')
_V8 = re.compile(r"^\s*at (?:(?:async )?(?P<func>[^\s(][^(]*?) \()?(?P<path>[^\s()]+?):(?P<line>\d+)(?::\d+)?\)?\s*$")
_GECKO = re.compile(r"^\s*(?P<func>[^@\s]*)@(?P<path>[^\s@]+?):(?P<line>\d+)(?::\d+)?\s*$")
_JVM = re.compile(r"^\s*at (?P<func>[\w$.<>/]+)\((?P<file>[^():]+\.(?:java|kt|kts|scala|groovy)):(?P<line>\d+)\)")
_CS = re.compile(r"^\s*at (?P<func>.+?) in (?P<path>.+?):line (?P<line>\d+)\s*$")
_DART = re.compile(r"^#\d+\s+(?P<func>.+?)\s+\((?P<path>(?:file|package|dart):[^\s)]+?):(?P<line>\d+)(?::\d+)?\)")
_GO = re.compile(r"^\s+(?P<path>(?:[A-Za-z]:)?[^\s:]+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-fA-F]+)?\s*$")
_RUST = re.compile(r"^\s*(?:at |panicked at )(?P<path>(?:[A-Za-z]:)?[^\s:]+\.rs):(?P<line>\d+)(?::\d+)?")
_RUST_PANIC = re.compile(r"panicked at (?P<path>(?:[A-Za-z]:)?[^\s:']+\.rs):(?P<line>\d+)")
# generic `path:line` / `path(line,col)`: a whole path token (it starts at a token boundary and
# is matched possessively, so a long line costs linear time), checked for an extension afterwards
_GENERIC = re.compile(r"(?<![\w.~@+/\\-])(?P<path>(?:[A-Za-z]:)?[\w.~@+/\\-]++)"
                      r"(?::(?P<line>\d+)|\((?P<pline>\d+)(?:,\d+)?\))")
_GENERIC_EXT = re.compile(r"\.[A-Za-z]\w{0,7}$")  # the token must end in a file extension
_LINE_REF = re.compile(r"[:(]\d")   # what any generic frame needs; most log lines have none
GENERIC_SCAN = 500                    # characters of a line searched for a generic frame


def parse_trace(text: str) -> list[Frame]:
    """Frames in trace order; Python frames are reversed afterwards so the innermost comes first."""
    frames: list[Frame] = []
    prev = ""
    for raw in text.split("\n"):
        line = raw.rstrip()
        m = _PY.match(line)
        if m:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), m["func"] or "", "python"))
        elif (m := _JVM.match(line)) is not None:
            func = m["func"]
            cls = func.rsplit(".", 1)[0] if "." in func else ""
            pkg = cls.rsplit(".", 1)[0].replace(".", "/") if "." in cls else ""
            hint = f"{pkg}/{m['file']}" if pkg else ""
            frames.append(Frame(line.strip(), m["file"], int(m["line"]), func.rsplit(".", 1)[-1], "jvm", hint))
        elif (m := _CS.match(line)) is not None:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), m["func"].split("(", 1)[0], "csharp"))
        elif (m := _DART.match(line)) is not None:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), m["func"], "dart"))
        elif (m := _V8.match(line)) is not None:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), (m["func"] or "").strip(), "v8"))
        elif (m := _GO.match(raw)) is not None:
            func = prev.strip().split("(", 1)[0] if prev.strip() and not prev.startswith(("\t", " ")) else ""
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), func.rsplit(".", 1)[-1], "go"))
        elif (m := _RUST.match(line) or _RUST_PANIC.search(line)) is not None:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), "", "rust"))
        elif (m := _GECKO.match(line)) is not None:
            frames.append(Frame(line.strip(), m["path"], int(m["line"]), m["func"], "gecko"))
        elif _LINE_REF.search(head := line[:GENERIC_SCAN]):
            for g in _GENERIC.finditer(head):
                n = g["line"] or g["pline"]
                if n and _GENERIC_EXT.search(g["path"]):
                    path = "/" + g["path"].lstrip("/") if g["path"].startswith("//") else g["path"]  # file:///x
                    frames.append(Frame(line.strip(), path, int(n), "", "path:line"))
                    break
        prev = raw
    py = [f for f in frames if f.fmt == "python"]
    if py:
        rest = [f for f in frames if f.fmt != "python"]
        frames = list(reversed(py)) + rest
    return frames


def _clean(path: str) -> str:
    p = path.strip().strip("'\"").replace("\\", "/")
    for prefix in ("file://", "webpack:///", "webpack://"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    if p.startswith("package:"):  # Dart: package:name/rest.dart lives in <package>/lib/rest.dart
        rest = p[len("package:"):].split("/", 1)
        p = "lib/" + rest[1] if len(rest) == 2 else rest[0]
    p = p.split("?", 1)[0]
    if re.match(r"^/[A-Za-z]:/", p):
        p = p[1:]
    return p


class PathMap:
    """Trace paths → repo files by the longest shared path suffix."""

    def __init__(self, files: list[str], root: str) -> None:
        self.files = set(files)
        self.root = root.replace("\\", "/").rstrip("/") + "/"
        self.suffix: dict[str, list[str]] = defaultdict(list)
        for f in sorted(files):
            segs = f.split("/")
            for k in range(len(segs)):
                self.suffix["/".join(segs[k:])].append(f)

    def lookup(self, raw: str, hint: str = "") -> list[str]:
        p = _clean(raw)
        if p.startswith(self.root) and p[len(self.root):] in self.files:
            return [p[len(self.root):]]
        for cand in ([hint] if hint else []) + [p]:
            segs = [s for s in cand.split("/") if s not in ("", ".", "..")]
            for k in range(len(segs), 0, -1):
                found = self.suffix.get("/".join(segs[-k:]))
                if not found:
                    continue
                if k == 1 and len(segs) > 1:  # only the file name matched a path that has directories
                    found = [f for f in found if "/" not in f]
                    if not found:
                        break
                return found
        return []


@dataclass
class TraceResult:
    frames: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)


def locate_trace(nav: Nav, text: str) -> TraceResult:
    from .errors import TopomarkError
    from .navigate import clip, enclosing_symbol

    res = TraceResult()
    frames = parse_trace(text)
    res.formats = sorted({f.fmt for f in frames})
    pm = PathMap(nav.ctx.files, str(nav.ctx.root))
    seen = set()
    for f in frames:
        cands = pm.lookup(f.path, f.hint)
        if not cands:
            res.skipped.append({"path": f.path, "line": f.line, "func": f.func, "reason": "not in the repo"})
            continue
        ranked = []
        for c in cands:
            try:
                info = nav.info(c)
                lines = nav.lines(c)
            except (OSError, TopomarkError):
                continue
            sym = enclosing_symbol(info, f.line) if f.line <= len(lines) else None
            name_ok = bool(sym and f.func and f.func.rsplit(".", 1)[-1] in (sym.name, sym.qualname))
            ranked.append((not name_ok, f.line > len(lines), len(c), c, sym, lines))
        if not ranked:
            res.skipped.append({"path": f.path, "line": f.line, "func": f.func, "reason": "unreadable"})
            continue
        ranked.sort(key=lambda r: r[:4])
        _, _, _, path, sym, lines = ranked[0]
        key = (path, f.line)
        if key in seen:
            continue
        seen.add(key)
        item = {"path": path, "line": f.line, "qualname": sym.qualname if sym else "", "kind": sym.kind if sym else "",
                "start": sym.start if sym else f.line, "end": sym.end if sym else f.line, "func": f.func,
                "format": f.fmt, "text": clip(lines[f.line - 1], 140) if 0 < f.line <= len(lines) else "",
                "group": _group(nav, path), "trace": clip(f.raw, 200)}
        if len(ranked) > 1:
            item["candidates"] = [r[3] for r in ranked]
        res.frames.append(item)
    return res

