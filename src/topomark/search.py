"""BM25 search over what code says about itself: symbol names, signatures, doc
summaries and paths, for ``topomark search``.

Three kinds of documents, all from the analysis cache (nothing is read twice):

* **Symbols.** Fields, each with a weight: the name split into words
  (``unit_surface_hash`` → unit, surface, hash, plus the whole name), the
  container (``Workspace`` for ``Workspace.problems``), the signature, the doc
  summary, the file name and its directories; a type also gets its members'
  names, weakly.
* **Files.** The path, the header comment or module docstring, and the row the
  code map writes about the file (or its directory unit). A file's score is added,
  scaled down, to its symbols that match on their own, and a file can be a result
  by itself.
* **Test methods** are symbols too, but a hit also counts as evidence for the
  production symbols the test's body uses (by distinctive name): an issue's words
  often match a test's name better than the code's.

Scoring is BM25F-lite (field weights fold into the term frequency), scaled by
the share of the query's words a symbol matches (a coordination factor), then
per-kind weights: production code over tests, code over Markdown and data files.
The weights were set on ``tools/eval_nav.py``'s search tasks and checked on
queries outside that set.
No PageRank and no randomness: ties break on path and line, so the same query on
the same tree gives the same list.

The index is plain lists and dicts, cached by ``Workspace.derived`` under a
digest of every parsed file and the config, so a warm search loads it and scores.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import re
from array import array
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

INDEX_VERSION = 3

# BM25
K1 = 1.2
B = 0.75

# Field weights (symbol documents)
W_NAME = 3.0
W_CONTAINER = 1.0
W_SIGNATURE = 0.6
W_DOC = 1.5
W_FILE_STEM = 0.5
W_DIRS = 0.2
W_MEMBERS = 0.3
# Field weights (file documents)
W_F_STEM = 1.5
W_F_DIRS = 0.5
W_F_HEADER = 1.0
W_F_ROW = 1.5

FILE_CONTEXT = 0.3     # share of a file's score added to its symbols that match by themselves
FILE_RESULT = 0.5      # a file listed as a result of its own
TEST_EVIDENCE = 0.5    # share of a test method's score given to the code its body uses
EVIDENCE_MAX_DECLS = 3  # a name declared by more symbols than this is too vague to follow
COVERAGE = 0.5        # a symbol's own score × (share of the query words it matches) ** COVERAGE

# "test" stays under TEST_EVIDENCE: the code a test method leads to ranks above the test itself
KIND_WEIGHT = {"code": 1.0, "test": 0.4, "doc": 0.35, "data": 0.3}
DOC_LANGS = frozenset({"markdown", "text"})
DATA_LANGS = frozenset({"data", "json", "toml", "yaml"})

STOP = frozenset("""
a an and are as at be by can do does for from has have how i if in into is it its of on or that the
their then there these this to was what when where which who why will with within without not no
def class self cls return function const let var public private protected static void async await
export import new fn func pub mut val fun override readonly internal
""".split())

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_ROW = re.compile(r"^\|\s*`([^`]+)`[^|]*\|([^|]*)\|")


def stem(w: str) -> str:
    """A light, deterministic suffix stripper: stamps → stamp, refusing → refus, directories → directory."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


@lru_cache(maxsize=65536)
def _ident_terms(ident: str) -> tuple[str, ...]:
    parts = [p.lower() for p in _PARTS.findall(ident)]
    out = [stem(p) for p in parts if p not in STOP and len(p) > 1]
    if len(parts) > 1:
        whole = ident.lower().strip("_")
        if whole and whole not in STOP:
            out.append(whole)
    return tuple(out)


def words(text: str) -> list[str]:
    """Search terms of a text: identifiers split at case changes and underscores, lowercased,
    stemmed, stop words dropped; a compound identifier also counts whole."""
    out: list[str] = []
    for ident in _IDENT.findall(text):
        out.extend(_ident_terms(ident))
    return out


def _one_line(text: str) -> str:
    """Whitespace runs as one space: symbol details are packed tab- and newline-separated, and a
    Markdown heading or a signature may hold a tab."""
    return " ".join(text.split())


def _add(tf: dict[str, float], text: str, weight: float) -> None:
    for w in words(text):
        tf[w] = tf.get(w, 0.0) + weight


@dataclass
class Hit:
    path: str
    qualname: str
    kind: str
    start: int
    end: int
    signature: str
    score: float
    group: str           # code | test | doc | data
    matched: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)   # test methods that lent this symbol their score

    def to_json(self) -> dict:
        d = {"path": self.path, "qualname": self.qualname, "kind": self.kind, "start": self.start,
             "end": self.end, "signature": self.signature, "score": round(self.score, 3), "group": self.group,
             "matched": self.matched}
        if self.via:
            d["via"] = self.via
        return d


# ---------------------------------------------------------------- building
def _group(nav, path: str, lang: str) -> str:
    if lang in DOC_LANGS:
        return "doc"
    if lang in DATA_LANGS:
        return "data"
    return "test" if nav.is_test(path) else "code"


def _tuples(info) -> list[tuple]:
    """(kind, name, qualname, start, end, signature, exported, container, attrs, doc, line) per symbol."""
    raw = getattr(info, "symbol_tuples", None)
    if raw is not None:
        return raw
    return [(s.kind, s.name, s.qualname, s.start, s.end, s.signature, s.exported, s.container, s.attrs, s.doc,
             s.line) for s in info.symbols]


def _area_rows(nav) -> dict[str, str]:
    """unit (file or ``dir/``) → the summary cell of its row in the code map."""
    rows: dict[str, str] = {}
    for a in nav.ws.areas:
        for line in a.text.split("\n"):
            m = _ROW.match(line.strip())
            if m:
                rows.setdefault(m.group(1).strip(), m.group(2).strip())
    return rows


def inputs_key(nav) -> str:
    """What the index depends on besides the parsed files: config and the area files' text."""
    from .graph import tables_key

    h = hashlib.sha256(f"{INDEX_VERSION}\n{tables_key(nav.cfg)}\n{nav.cfg.docs_dir}".encode("utf-8"))
    for a in nav.ws.areas:
        h.update(a.file.encode("utf-8") + b"\0" + a.text.encode("utf-8"))
    return h.hexdigest()[:24]


_GROUP_CODE = {"code": "c", "test": "t", "doc": "d", "data": "a"}
_CODE_GROUP = {v: k for k, v in _GROUP_CODE.items()}


def build(nav) -> dict:
    """The search index as marshal-able plain data. Posting lists, lengths and per-document
    numbers are packed ``array`` bytes and symbol details one string, so loading a 3,000-file
    index is a handful of big objects, not millions of small ones."""
    from .lang.base import IDENT
    from .masking import mask_file
    from .testsel import test_methods

    infos = nav.infos
    rows = _area_rows(nav)
    dir_rows = sorted((u, s) for u, s in rows.items() if u.endswith("/"))
    meta: list[str] = []           # "qualname\tkind\tstart\tend\tsignature" per symbol document
    doc_group: list[str] = []
    doc_file = array("i")
    tfs: list[dict[str, float]] = []
    files: list[str] = []
    file_group: list[str] = []
    file_tfs: list[dict[str, float]] = []
    by_name: dict[str, list[int]] = defaultdict(list)   # production symbol name → doc ids
    test_files: list[tuple[str, int]] = []               # (path, first doc id of the file)
    min_name, keep = nav.cfg.min_name, nav.cfg.keep_short_names
    for path in sorted(infos):
        info = infos[path]
        group = _group(nav, path, info.lang)
        stem_ = path.rpartition("/")[2].partition(".")[0]
        dirs = path.rpartition("/")[0].replace("/", " ")
        fid = len(files)
        files.append(path)
        file_group.append(_GROUP_CODE[group])
        ftf: dict[str, float] = {}
        _add(ftf, stem_, W_F_STEM)
        _add(ftf, dirs, W_F_DIRS)
        _add(ftf, " ".join(info.header[:12]), W_F_HEADER)
        row = rows.get(path) or next((s for u, s in dir_rows if path.startswith(u)), "")
        if row:
            _add(ftf, row, W_F_ROW if path in rows else W_F_ROW / 2)
        file_tfs.append(ftf)
        tuples = _tuples(info)
        members: dict[str, list[str]] = defaultdict(list)
        for tup in tuples:
            if tup[7]:
                members[tup[7]].append(tup[1])
        path_tf: dict[str, float] = {}
        _add(path_tf, stem_, W_FILE_STEM)
        _add(path_tf, dirs, W_DIRS)
        first = len(meta)
        for tup in tuples:
            kind, name, qual, start, end, sig, _exported, container, _attrs, doc = tup[:10]
            if kind == "namespace":
                continue
            tf = dict(path_tf)
            _add(tf, name, W_NAME)
            _add(tf, container, W_CONTAINER)
            _add(tf, sig, W_SIGNATURE)
            _add(tf, doc, W_DOC)
            if qual in members:
                _add(tf, " ".join(members[qual][:40]), W_MEMBERS)
            if group == "code" and (len(name) >= min_name or name in keep):
                by_name[name].append(len(meta))
            meta.append("\t".join((_one_line(qual), _one_line(kind), str(start), str(end), _one_line(sig))))
            doc_group.append(_GROUP_CODE[group])
            doc_file.append(fid)
            tfs.append(tf)
        if group == "test" and len(meta) > first:
            test_files.append((path, first))
    # test methods → the production symbols their bodies use (distinctive names only)
    usable = {n for n, ids in by_name.items() if len(ids) <= EVIDENCE_MAX_DECLS}
    evidence: dict[int, bytes] = {}
    for path, first in test_files:
        info = infos[path]
        methods = test_methods(info)
        if not methods:
            continue
        try:
            mlines = mask_file(path, nav.ctx.read(path)).text.split("\n")
        except (OSError, ValueError):
            continue
        ids: dict[tuple[str, int], int] = {}
        for i in range(first, len(meta)):
            if doc_file[i] != doc_file[first]:
                break
            q, _, rest = meta[i].partition("\t")
            ids[(q, int(rest.split("\t", 2)[1]))] = i
        for s in methods:
            doc_id = ids.get((_one_line(s.qualname), s.start))
            if doc_id is None:
                continue
            used = set(IDENT.findall("\n".join(mlines[s.start - 1:s.end]))) & usable
            targets = sorted({j for n in used for j in by_name[n]})
            if targets:
                evidence[doc_id] = array("i", targets).tobytes()
    offsets = array("i", [0])
    for m in meta:
        offsets.append(offsets[-1] + len(m) + 1)
    return {"version": INDEX_VERSION, "files": files, "file_group": "".join(file_group),
            "doc_file": doc_file.tobytes(), "doc_group": "".join(doc_group), "meta": "\n".join(meta) + "\n",
            "meta_off": offsets.tobytes(), **_postings("", tfs), **_postings("f_", file_tfs), "evidence": evidence}


def _postings(prefix: str, tfs: list[dict[str, float]]) -> dict:
    ids: dict[str, array] = defaultdict(lambda: array("i"))
    freqs: dict[str, array] = defaultdict(lambda: array("f"))
    lengths = array("f")
    for i, tf in enumerate(tfs):
        lengths.append(sum(tf.values()))
        for term, f in tf.items():
            ids[term].append(i)
            freqs[term].append(f)
    post = {term: ids[term].tobytes() + freqs[term].tobytes() for term in ids}
    return {prefix + "post": post, prefix + "len": lengths.tobytes()}


def load(nav) -> dict:
    return nav.ws.derived("search", inputs_key(nav), lambda: build(nav))


def _ints(blob: bytes) -> array:
    a = array("i")
    a.frombytes(blob)
    return a


def _floats(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    return a


# ---------------------------------------------------------------- scoring
def _bm25(post: dict, lengths: array, terms: list[str]) -> tuple[dict[int, float], dict[int, list[str]]]:
    n = len(lengths)
    if not n:
        return {}, {}
    avg = sum(lengths) / n or 1.0
    norm = [K1 * (1 - B + B * x / avg) for x in lengths]
    scores: dict[int, float] = defaultdict(float)
    matched: dict[int, list[str]] = defaultdict(list)
    for t in terms:
        blob = post.get(t)
        if not blob:
            continue
        half = len(blob) // 2
        ids, fs = _ints(blob[:half]), _floats(blob[half:])
        idf = math.log(1.0 + (n - len(ids) + 0.5) / (len(ids) + 0.5))
        for d, f in zip(ids, fs):
            scores[d] += idf * f * (K1 + 1) / (f + norm[d])
            matched[d].append(t)
    return scores, matched


def query_terms(text: str) -> list[str]:
    seen: list[str] = []
    for w in words(text):
        if w not in seen:
            seen.append(w)
    return seen


@dataclass
class Results:
    terms: list[str]
    total: int          # symbols and files that match
    files: int          # distinct files among them
    hits: list[Hit]     # the best ``limit``, best first


def search(index: dict, text: str, limit: int, keep=None) -> Results:
    """The best ``limit`` hits for ``text``; ``keep(path)`` filters files (``--area``).
    Deterministic: equal scores sort by path, a file before its symbols, then source order."""
    terms = query_terms(text)
    files = index["files"]
    doc_file = _ints(index["doc_file"])
    doc_group = index["doc_group"]
    direct, matched = _bm25(index["post"], _floats(index["len"]), terms)
    fscore, fmatched = _bm25(index["f_post"], _floats(index["f_len"]), terms)
    evidence: dict[int, float] = defaultdict(float)
    via: dict[int, list[int]] = defaultdict(list)
    for t, s in direct.items():
        blob = index["evidence"].get(t)
        if not blob:
            continue
        for j in _ints(blob):
            if s > evidence[j]:
                evidence[j] = s
            via[j].append(t)
    allowed: dict[int, bool] = {}

    def ok(fid: int) -> bool:
        if keep is None:
            return True
        if fid not in allowed:
            allowed[fid] = bool(keep(files[fid]))
        return allowed[fid]

    cands: list[tuple[float, str, int, int]] = []   # (-score, path, 0 file / 1 symbol, id)
    for d in set(direct) | set(evidence):
        fid = doc_file[d]
        if not ok(fid):
            continue
        own = direct.get(d, 0.0)
        if own and COVERAGE and len(terms) > 1:
            own *= (len(set(matched[d])) / len(terms)) ** COVERAGE
        score = own + (FILE_CONTEXT * fscore.get(fid, 0.0) if own else 0.0)
        score = KIND_WEIGHT[_CODE_GROUP[doc_group[d]]] * score + TEST_EVIDENCE * evidence.get(d, 0.0)
        cands.append((-round(score, 9), files[fid], 1, d))
    for f, s in fscore.items():
        if ok(f):
            cands.append((-round(KIND_WEIGHT[_CODE_GROUP[index["file_group"][f]]] * FILE_RESULT * s, 9), files[f], 0, f))
    top = heapq.nsmallest(max(0, limit), cands)
    meta, off = index["meta"], _ints(index["meta_off"])
    hits = []
    for neg, path, is_sym, i in top:
        if not is_sym:
            hits.append(Hit(path, "", "file", 1, 1, "", -neg, _CODE_GROUP[index["file_group"][i]],
                            sorted(set(fmatched[i]))))
            continue
        qual, kind, start, end, sig = meta[off[i]:off[i + 1] - 1].split("\t", 4)
        terms_hit = sorted(set(matched.get(i, [])) | {w for t in via.get(i, []) for w in matched[t]})
        tests = []
        for t in via.get(i, []):
            q = meta[off[t]:off[t + 1] - 1].split("\t", 1)[0]
            tests.append(f"{files[doc_file[t]]}::{q}")
        hits.append(Hit(path, qual, kind, int(start), int(end), sig, -neg, _CODE_GROUP[doc_group[i]], terms_hit,
                        sorted(set(tests))[:3]))
    return Results(terms, len(cands), len({c[1] for c in cands}), hits)
