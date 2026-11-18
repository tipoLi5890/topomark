"""Dart: classes, mixins, extensions, enums, getters and setters, top-level functions.

Exported: the name does not start with ``_``.
"""

from __future__ import annotations

import re

from ._decl import _TYPE_SCOPES, _enum_entries, _sig, first_paren, split_top, strip_annotations
from .base import norm
from .brace import BraceLanguage, Decl, _Scope
from .scan import Masked, Syntax

_DART_TYPE = re.compile(r"^((?:(?:abstract|base|final|interface|sealed|mixin|macro|augment)\s+)*)"
                        r"(class|mixin|enum|extension\s+type|extension)\b\s*([A-Za-z_$][\w$]*)?")
_DART_CONTROL = {"if", "else", "for", "while", "do", "switch", "try", "catch", "finally", "on", "return", "await",
                 "assert", "super", "this", "new", "throw", "yield", "case"}
_DART_ENUM_ENTRIES = re.compile(r"^[A-Za-z_$][\w$]*\s*(?:<[^>]*>\s*)?(?:\(.*?\)\s*)?(?:,|$)")
_DART_GETTER = re.compile(r"(?:^|\s)get\s+([A-Za-z_$][\w$]*)\s*(?:=>|$|async\b|sync\b)")
_DART_MEMBER = re.compile(r"(?:^|[\s>?])(?:(set)\s+)?((?:[A-Za-z_$][\w$]*\.)?[A-Za-z_$][\w$]*)\s*(?:<[^()]*>)?\s*$")


class Dart(BraceLanguage):
    name = "dart"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), nested_block_comments=True,
                    quotes=('"', "'"), triple_quotes=('"""', "'''"), dq_interp="${", dart_raw=True)

    def imports_of(self, masked: Masked) -> list[str]:
        from ._imports import dart_imports

        return dart_imports(masked.text, masked.original)

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(header)
        if not h:
            return Decl("block")
        m = _DART_TYPE.match(h)
        if m:
            kw = m.group(2).split()[0]
            name = m.group(3) or ""
            if kw == "extension" and (not name or name == "on"):
                on = re.search(r"\bon\s+([^{]+)$", h)
                name = "on " + norm(on.group(1)) if on else "extension"
                return Decl("extension", name, True, attrs, signature=_sig(raw))
            kind = "class" if "type" in m.group(2) else kw
            return Decl(kind, name, not name.startswith("_"), attrs, signature=_sig(raw))
        d = self._member(h, raw, parent, enclosing_type, attrs)
        if d:
            return d
        return Decl("init") if re.search(r"(?<![=!<>])=(?![=>])", h) else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(stmt)
        if not h or parent.kind == "enum" and _DART_ENUM_ENTRIES.match(h):
            return None
        if re.match(r"(?:import|export|library|part|show|hide)\b", h):
            return None
        m = re.match(r"^typedef\s+([A-Za-z_$][\w$]*)", h)
        if m:
            return Decl("type", m.group(1), not m.group(1).startswith("_"), attrs, signature=_sig(raw, ()))
        m = _DART_TYPE.match(h)
        if m and m.group(3):  # `class A = B with M;`
            return Decl("class", m.group(3), not m.group(3).startswith("_"), attrs, signature=_sig(raw, ()))
        d = self._member(h, raw, parent, enclosing_type, attrs)
        if d:
            return d
        return self._field(h, raw, parent, attrs)

    def _member(self, h: str, raw: str, parent: _Scope, enclosing: str, attrs: list[str]) -> Decl | None:
        arrow = h.find("=>")
        head = h[:arrow] if arrow >= 0 else h
        g = _DART_GETTER.search(head.rstrip())
        if g and first_paren(head) < 0:
            name = g.group(1)
            return Decl("getter", name, not name.startswith("_"), attrs, signature=_sig(raw, ("=>",)))
        p = first_paren(head)
        if p < 0:
            return None
        before = head[:p]
        wm = re.match(r"\w*", before)
        assert wm is not None  # `\w*` matches the empty string
        if re.search(r"(?<![=!<>])=(?![=>])", before) or wm.group(0) in _DART_CONTROL:
            return None
        op = re.search(r"\boperator\s*(\S+)\s*$", before)
        if op:
            return Decl("operator", "operator " + op.group(1), True, attrs, signature=_sig(raw, ("=>",)))
        m = _DART_MEMBER.search(before)
        if not m:
            return None
        name = m.group(2)
        if name in _DART_CONTROL:
            return None
        if m.group(1):
            kind = "setter"
        elif enclosing and (name == enclosing or name.startswith(enclosing + ".")):
            kind = "constructor"
            name = name.split(".", 1)[-1] if "." in name else name  # `Foo.named` → Foo.named, not Foo.Foo.named
        else:
            kind = "method" if parent.kind in _TYPE_SCOPES else "function"
        return Decl(kind, name, not name.rsplit(".", 1)[-1].startswith("_"), attrs, signature=_sig(raw, ("=>",)))

    def _field(self, h: str, raw: str, parent: _Scope, attrs: list[str]) -> Decl | None:
        first = split_top(h, ",")[0][1]
        lhs = re.split(r"(?<![=!<>])=(?![=>])", first, maxsplit=1)[0]
        names = re.findall(r"[A-Za-z_$][\w$]*", lhs)
        if not names or names[-1] in _DART_CONTROL:
            return None
        name = names[-1]
        if parent.kind == "file" and len(names) == 1 and "=" not in first:
            return None  # a bare word at top level is not a declaration
        kind = "const" if re.search(r"\bconst\b", lhs) else "field" if parent.kind in _TYPE_SCOPES else "var"
        sig = norm(raw)
        if len(sig) > 160:
            sig = norm(raw.split("=")[0]) + " = …"
        return Decl(kind, name, not name.startswith("_"), attrs, signature=sig)

    def enum_members(self, body: str) -> list[str]:
        return _enum_entries(body)
