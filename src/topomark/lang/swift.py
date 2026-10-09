"""Swift: types, extensions, functions, initialisers, properties, type aliases.

Exported: no ``private`` / ``fileprivate``.
"""

from __future__ import annotations

import re

from ._decl import _IDENT, _TYPE_SCOPES, _is_kind, _sig, split_top, strip_annotations, top_level_only
from .base import FileInfo
from .brace import BraceLanguage, Decl, _Scope, preprocessor_branches
from .scan import Syntax

_SW_MODS = (r"(?:public|private|fileprivate|internal|open|package|final|static|class|override|mutating|nonmutating|"
            r"lazy|weak|unowned|required|convenience|dynamic|indirect|nonisolated|isolated|optional|prefix|postfix|"
            r"infix|distributed|consuming|borrowing|async)")
_SW_TYPE = re.compile(rf"^((?:{_SW_MODS}\s+)*)(class|struct|enum|protocol|extension|actor)\s+({_IDENT}(?:\.{_IDENT})*)")
_SW_FUNC = re.compile(rf"^((?:{_SW_MODS}\s+)*)func\s+([^\s(<]+)")
_SW_INIT = re.compile(rf"^((?:{_SW_MODS}\s+)*)(init|deinit|subscript)\b")
_SW_VAR = re.compile(rf"^((?:{_SW_MODS}\s+)*)(var|let)\s+({_IDENT}|`[^`]+`)")
_SW_ALIAS = re.compile(rf"^((?:{_SW_MODS}\s+)*)(typealias|associatedtype)\s+({_IDENT})")
_SW_SETTER_ACL = re.compile(r"\b(?:private|fileprivate|internal|public|open|package)\s*\(set\)")
_SW_KEYWORDS = {"func", "var", "let", "init", "subscript", "typealias", "case"}


class Swift(BraceLanguage):
    name = "swift"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), nested_block_comments=True,
                    quotes=('"',), triple_quotes=('"""',), dq_interp="\\(", swift_raw=True)
    terminators = ";\n"

    def premask(self, text: str) -> str:
        return preprocessor_branches(text)[0]  # `#if os(iOS)` … `#else` … `#endif`

    def _exported(self, mods: str) -> bool:
        return not re.search(r"\b(private|fileprivate)\b", _SW_SETTER_ACL.sub("", mods))

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(header)
        if not h:
            return Decl("block")
        d = self._decl(h, raw, parent, attrs)
        if d:
            return d
        return Decl("init") if "=" in h.split("(")[0] else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(stmt)
        if not h or h.startswith("import ") or parent.kind == "enum" and re.match(r"(?:indirect\s+)?case\b", h):
            return None
        m = _SW_ALIAS.match(h)
        if m:
            return Decl("type", m.group(3), self._exported(m.group(1)), attrs, signature=_sig(raw, ()))
        return self._decl(h, raw, parent, attrs)

    def _decl(self, h: str, raw: str, parent: _Scope, attrs: list[str]) -> Decl | None:
        h = _SW_SETTER_ACL.sub("", h).strip()  # `public private(set) var x`: the getter's access counts
        m = _SW_TYPE.match(h)
        if m and m.group(3) not in _SW_KEYWORDS:
            return Decl(m.group(2), m.group(3), self._exported(m.group(1)), attrs, signature=_sig(raw))
        m = _SW_FUNC.match(h)
        if m:
            kind = "method" if parent.kind in _TYPE_SCOPES else "function"
            return Decl(kind, m.group(2), self._exported(m.group(1)), attrs, signature=_sig(raw))
        m = _SW_INIT.match(h)
        if m:
            kind = {"init": "constructor", "deinit": "destructor", "subscript": "indexer"}[m.group(2)]
            return Decl(kind, m.group(2), self._exported(m.group(1)), attrs, signature=_sig(raw))
        m = _SW_VAR.match(h)
        if m:
            in_type = parent.kind in _TYPE_SCOPES
            kind = "property" if in_type else ("const" if m.group(2) == "let" else "var")
            return Decl(kind, m.group(3).strip("`"), self._exported(m.group(1)), attrs, signature=_sig(raw))
        return None

    def enum_members(self, body: str) -> list[str]:
        out = []
        for line in top_level_only(body).split("\n"):
            m = re.match(r"\s*(?:@\w+\s+)*(?:indirect\s+)?case\s+(.*)", line)
            if m:
                for _, part in split_top(m.group(1), ","):
                    mm = re.match(rf"\s*({_IDENT}|`[^`]+`)", part)
                    if mm:
                        out.append(mm.group(1).strip("`"))
        return out

    def analyze(self, path: str, text: str) -> FileInfo:
        info = super().analyze(path, text)
        info.types = [t for t in info.types if not _is_kind(info, t, "extension")]
        return info
