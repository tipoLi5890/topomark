"""Rust: functions, structs, enums, traits, modules, ``impl`` blocks, macros.

Exported: ``pub``.
"""

from __future__ import annotations

import re

from ._decl import _IDENT, _enum_entries, _is_kind, _short, _sig, _skip_balanced
from .base import FileInfo, norm
from .brace import BraceLanguage, Decl, _Scope
from .scan import Masked, Syntax

_RS_VIS = r"(?:pub(?:\s*\([^)]*\))?\s+)?"
_RS_QUAL = r"(?:(?:default|const|async|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*"
_RS_FN = re.compile(rf"^({_RS_VIS}){_RS_QUAL}fn\s+({_IDENT})")
_RS_ITEM = re.compile(rf"^({_RS_VIS})(?:unsafe\s+|auto\s+)*(struct|enum|union|trait|mod|type|const|static)\s+"
                      rf"(?:mut\s+)?({_IDENT})")
_RS_IMPL = re.compile(r"^(?:unsafe\s+)?impl\b")
_RS_MACRO = re.compile(rf"^(?:#\[macro_export\]\s*)?macro_rules!\s*({_IDENT})")


def _strip_rust_attrs(h: str) -> tuple[list[str], str]:
    attrs: list[str] = []
    s = h.strip()
    while s.startswith("#"):
        k = s.find("[")
        if k < 0 or s[1:k].strip() not in ("", "!"):
            break
        end = _skip_balanced(s, k, "[", "]")
        attrs.append(norm(s[k + 1:end - 1]))
        s = s[end:].lstrip()
    return attrs, s


def _rust_impl_target(h: str) -> tuple[str, str]:
    """``impl<T: X> Trait<T> for Foo<T> where …`` → ("Foo", "Trait")."""
    s = re.sub(r"^(?:unsafe\s+)?impl\s*", "", h)
    if s.startswith("<"):
        s = s[_skip_balanced(s, 0, "<", ">"):]
    s = re.split(r"\bwhere\b", s)[0]
    trait = ""
    if re.search(r"\sfor\s", " " + s + " "):
        trait_part, s = re.split(r"\s+for\s+", s, maxsplit=1)
        trait = re.sub(r"<.*", "", trait_part).strip().lstrip("!")
    s = re.sub(r"<.*", "", s.strip()).strip().lstrip("&").strip()
    s = re.sub(r"^(?:dyn|mut)\s+", "", s)
    return (s.split("::")[-1] or "impl"), trait


class Rust(BraceLanguage):
    name = "rust"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), nested_block_comments=True,
                    quotes=('"', "'"), char_literals_only=True, rust_raw=True)
    functions_are_types = True

    def imports_of(self, masked: Masked) -> list[str]:
        from ._imports import rust_imports

        return rust_imports(masked.text, masked.original)

    def _exported(self, vis: str, parent: _Scope) -> bool:
        if parent.kind == "trait" or (parent.kind == "impl" and parent.sym and any(a.startswith("trait ")
                                                                                   for a in parent.sym.attrs)):
            return True
        return vis.strip().startswith("pub")

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = _strip_rust_attrs(header)
        if not h or parent.kind in ("enum", "struct"):
            return Decl("block")
        if re.match(r"^(?:unsafe\s+)?extern\b[^(]*$", h) and "fn" not in h.split():
            return Decl("transparent")
        m = _RS_MACRO.match(h)
        if m:
            return Decl("macro", m.group(1), "macro_export" in " ".join(attrs), attrs, signature=_sig(_strip_rust_attrs(raw)[1]))
        if _RS_IMPL.match(h):
            target, trait = _rust_impl_target(h)
            return Decl("impl", target, bool(trait), attrs + ([f"trait {trait}"] if trait else []), signature=_sig(_strip_rust_attrs(raw)[1]))
        m = _RS_FN.match(h)
        if m:
            kind = "method" if parent.kind in ("impl", "trait") else "function"
            return Decl(kind, m.group(2), self._exported(m.group(1), parent), attrs, signature=_sig(_strip_rust_attrs(raw)[1]))
        m = _RS_ITEM.match(h)
        if m:
            kw = m.group(2)
            if kw in ("const", "static", "type"):
                return Decl("init")
            kind = {"mod": "module", "union": "struct"}.get(kw, kw)
            return Decl(kind, m.group(3), self._exported(m.group(1), parent), attrs, signature=_sig(_strip_rust_attrs(raw)[1]))
        return Decl("init") if "=" in h else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = _strip_rust_attrs(stmt)
        if not h or parent.kind in ("enum", "struct") or re.match(rf"^{_RS_VIS}(?:use|extern\s+crate)\b", h):
            return None
        m = _RS_FN.match(h)
        if m:
            return Decl("method" if parent.kind in ("impl", "trait") else "function", m.group(2),
                        self._exported(m.group(1), parent), attrs, signature=_sig(_strip_rust_attrs(raw)[1]))
        m = _RS_ITEM.match(h)
        if m:
            kind = {"mod": "module", "union": "struct", "static": "const"}.get(m.group(2), m.group(2))
            return Decl(kind, m.group(3), self._exported(m.group(1), parent), attrs, signature=_short(_strip_rust_attrs(raw)[1]))
        m = _RS_MACRO.match(h)
        if m:
            return Decl("macro", m.group(1), "macro_export" in " ".join(attrs), attrs, signature=_sig(_strip_rust_attrs(raw)[1], ("(",)))
        return None

    def enum_members(self, body: str) -> list[str]:
        return _enum_entries(body, stop_at_semicolon=False)

    def analyze(self, path: str, text: str) -> FileInfo:
        info = super().analyze(path, text)
        info.types = [t for t in info.types if not _is_kind(info, t, "impl")]
        return info
