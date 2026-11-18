"""Kotlin: classes, objects, interfaces, functions (extension receivers too), properties.

Exported: no ``private``.
"""

from __future__ import annotations

import re

from ._decl import _IDENT, _TYPE_SCOPES, _enum_entries, _sig, strip_annotations
from .brace import BraceLanguage, Decl, _Scope
from .scan import Masked, Syntax

_KT_MODS = (r"(?:public|private|protected|internal|open|abstract|final|sealed|data|enum|annotation|inner|value|"
            r"inline|override|suspend|operator|infix|tailrec|external|lateinit|const|companion|expect|actual)")
_KT_TYPE = re.compile(rf"^((?:{_KT_MODS}\s+)*)(class|interface|object|fun\s+interface)\b\s*({_IDENT}|`[^`]+`)?")
_KT_FUN = re.compile(rf"^((?:{_KT_MODS}\s+)*)fun\s+(?:<(?:[^<>]|<[^<>]*>)*>\s*)?(?:([\w.<>?, *]+?)\.)?"
                     rf"({_IDENT}|`[^`]+`)\s*\(")
_KT_PROP = re.compile(rf"^((?:{_KT_MODS}\s+)*)(val|var)\s+(?:<(?:[^<>]|<[^<>]*>)*>\s*)?(?:([\w.<>?]+?)\.)?({_IDENT})")
_KT_CONTROL = {"if", "else", "when", "for", "while", "do", "try", "catch", "finally", "init", "get", "set", "return",
               "throw", "constructor"}


class Kotlin(BraceLanguage):
    name = "kotlin"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), nested_block_comments=True,
                    quotes=('"', "'"), triple_quotes=('"""',), dq_interp="${", char_literals_only=True)
    terminators = ";\n"

    def imports_of(self, masked: Masked) -> list[str]:
        from ._imports import jvm_imports

        return jvm_imports(masked.text, masked.original)

    def _exported(self, mods: str) -> bool:
        return not re.search(r"\b(private|internal)\b", mods)

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(header)
        if not h:
            return Decl("block")
        wm = re.match(r"\w*", h)
        assert wm is not None  # `\w*` matches the empty string
        word = wm.group(0)
        if word == "constructor" or re.match(rf"^(?:{_KT_MODS}\s+)*constructor\s*\(", h):
            return Decl("constructor", "constructor", self._exported(h.split("constructor")[0]), attrs,
                        signature=_sig(raw))
        d = self._decl(h, raw, parent, attrs)
        if d:
            return d
        if word in _KT_CONTROL:
            return Decl("block")
        return Decl("init") if "=" in h else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(stmt)
        if not h or h.startswith(("package ", "import ")):
            return None
        m = re.match(rf"^((?:{_KT_MODS}\s+)*)typealias\s+({_IDENT})", h)
        if m:
            return Decl("type", m.group(2), self._exported(m.group(1)), attrs, signature=_sig(raw, ()))
        return self._decl(h, raw, parent, attrs)

    def _decl(self, h: str, raw: str, parent: _Scope, attrs: list[str]) -> Decl | None:
        m = _KT_TYPE.match(h)
        if m:
            mods, kw = m.group(1), m.group(2)
            kind = "interface" if "interface" in kw else "object" if kw == "object" else \
                "enum" if re.search(r"\benum\b", mods) else "class"
            name = (m.group(3) or ("Companion" if "companion" in mods else "object")).strip("`")
            return Decl(kind, name, self._exported(mods), attrs, signature=_sig(raw))
        m = _KT_FUN.match(h)
        if m:
            kind = "method" if parent.kind in _TYPE_SCOPES else "function"
            return Decl(kind, m.group(3).strip("`"), self._exported(m.group(1)), attrs, signature=_sig(raw, (" = ",)))
        m = _KT_PROP.match(h)
        if m:
            kind = "const" if re.search(r"\bconst\b", m.group(1)) else "property"
            return Decl(kind, m.group(4), self._exported(m.group(1)), attrs, signature=_sig(raw))
        return None

    def enum_members(self, body: str) -> list[str]:
        return [x for x in _enum_entries(body) if x not in _KT_CONTROL and x not in ("fun", "val", "var")]
