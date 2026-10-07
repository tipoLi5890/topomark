"""Shared data model for language adapters.

An adapter turns ``(path, text)`` into a ``FileInfo``:

* ``symbols``: declarations with 1-based inclusive line ranges, nested by
  ``container`` (``Outer.Inner.member`` in ``qualname``). Only declarations a
  reader navigates to are listed: types, members, top-level functions and
  constants; statements inside function bodies are not.
* ``header``: the file's first comment block (or module docstring), which in
  most repos states the file's responsibility.
* ``surface``: the text whose SHA-256 is the review stamp. It changes when the
  file's responsibility or public interface changes (header, exported
  signatures, constant values, enum members) and not when a body changes.
* ``idents``: identifiers in code (comments and strings masked out), used for
  references and fan-in.
* ``types``: top-level type names this file declares, the unit of fan-in.
* ``imports``: module specifiers exactly as written (Python ``a.b``, ``.x``,
  ``..``; JS/TS ``./x``, ``react``), ``DYNAMIC`` when a module is loaded by a
  computed name. Resolved to files by ``navigate``; never part of the surface,
  so adding an import does not ask for a review.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DYNAMIC = "<dynamic>"  # an import whose module name is computed at run time
_WS = re.compile(r"\s+")


@dataclass
class Symbol:
    kind: str
    name: str
    qualname: str
    start: int
    end: int
    signature: str
    exported: bool = True
    container: str = ""
    attrs: list[str] = field(default_factory=list)
    doc: str = ""
    line: int = 0  # line of the declaration itself (start may include doc comment and attributes)

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("attrs", "container", "doc"):
            if not d[k]:
                d.pop(k)
        return d


@dataclass
class FileInfo:
    path: str
    lang: str
    header: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    surface: str = ""
    idents: set[str] = field(default_factory=set)
    types: list[str] = field(default_factory=list)
    line_count: int = 0
    imports: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "lang": self.lang,
            "line_count": self.line_count,
            "header": self.header,
            "symbols": [s.to_json() for s in self.symbols],
            "types": self.types,
            "imports": self.imports,
        }

    @classmethod
    def from_json(cls, d: dict, idents: list[str], surface: str) -> "FileInfo":
        syms = [Symbol(**{**{"container": "", "attrs": [], "doc": ""}, **s}) for s in d["symbols"]]
        return cls(path=d["path"], lang=d["lang"], header=d["header"], symbols=syms, surface=surface,
                   idents=set(idents), types=d["types"], line_count=d["line_count"], imports=d.get("imports", []))


def norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def norm_lines(lines: list[str]) -> list[str]:
    return [x for x in (norm(ln) for ln in lines) if x]


COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|#(?!!)|--|<!--)")
HEAD_SKIP = ("using ", "namespace ", "'use strict'", '"use strict"', "#!", "import ", "package ", "from ",
             "{", "[", "set -", "library ", "part ", "@file", "<?", "export {}")


def head_comment(text: str) -> list[str]:
    """The first contiguous comment block, skipping imports/usings/shebang before it."""
    out: list[str] = []
    started = False
    for ln in text.split("\n"):
        st = ln.strip()
        if COMMENT_LINE.match(ln):
            started = True
            out.append(st)
            continue
        if started:
            break
        if not st or st.startswith(HEAD_SKIP):
            continue
        break
    return out


_DOC_MARKERS = re.compile(r"^\s*(?:///?|/\*\*?|\*/|\*|#|--)\s?")
_XML_TAGS = re.compile(r"</?(?:summary|remarks|para|returns|param[^>]*|typeparam[^>]*|value|example|code|c|b|i|"
                       r"inheritdoc[^>]*|list[^>]*|item|description|term|see(?:also)?)\s*/?>")
# <see cref="T:Foo.Bar"/>, <paramref name="x"/>, <see langword="null"/>: keep the referenced name
_XML_REF = re.compile(r"<(?:see|seealso|paramref|typeparamref)\s+(?:cref|name|langword|href)\s*=\s*\"(?:[A-Z]:)?"
                      r"([^\"]*)\"\s*/?>(?:[^<]*</(?:see|seealso)>)?")
_BACKTICKS = re.compile(r"`+([^`\n]+?)`+")


def doc_summary(raw_comment: str, limit: int = 140) -> str:
    """First sentence of a comment block, markers and XML doc tags stripped."""
    lines = []
    for ln in raw_comment.split("\n"):
        ln = _DOC_MARKERS.sub("", ln).replace("*/", "")
        ln = _XML_REF.sub(lambda m: m.group(1).replace("{", "<").replace("}", ">"), ln)
        ln = _XML_TAGS.sub("", ln)
        ln = _BACKTICKS.sub(r"\1", ln).strip()
        if ln:
            lines.append(ln)
    text = norm(" ".join(lines))
    if not text:
        return ""
    for stop in ("。", ". ", "；"):
        k = text.find(stop)
        if 0 < k < limit:
            return text[:k + len(stop)].strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def surface_text(header: list[str], decls: list[str]) -> str:
    return "\n".join(norm_lines(header) + ["--"] + norm_lines(decls))


def idents_of(masked: str) -> set[str]:
    return set(IDENT.findall(masked))
