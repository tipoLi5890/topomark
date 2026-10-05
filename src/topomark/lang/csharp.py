"""C# and Java (same declaration grammar for what an outline needs).

Exported = declared ``public``/``protected``/``internal`` (Java: ``public``/
``protected``), or any member of an interface, or an enum member. The surface
keeps constant values (``public const float ReactionFloor = 0.75f``) because
code maps routinely quote them, and enum members because they are contracts.
"""

from __future__ import annotations

import re

from .base import norm
from .brace import BraceLanguage, Decl, _Scope, leading_attrs, preprocessor_branches
from .scan import Masked, Syntax

_MODS = r"(?:public|private|protected|internal|static|sealed|abstract|partial|readonly|unsafe|new|file|ref|virtual|" \
        r"override|extern|async|volatile|const|required|final|synchronized|native|transient|strictfp|default)"
_TYPE_RX = re.compile(rf"^(?:{_MODS}\s+)*(class|struct|interface|enum|record(?:\s+(?:class|struct))?|@interface)\s+"
                      r"([A-Za-z_]\w*)")
_NS_RX = re.compile(r"^(?:namespace|package)\s+([\w.]+)")
_CONTROL = {"if", "else", "for", "foreach", "while", "do", "switch", "try", "catch", "finally", "using", "lock",
            "fixed", "unsafe", "checked", "unchecked", "return", "yield", "case", "default", "static", "synchronized"}
_ACCESSORS = {"get", "set", "init", "add", "remove"}
_IDENT_BEFORE_PAREN = re.compile(r"(~?[A-Za-z_]\w*)\s*(?:<(?:[^<>()]|<(?:[^<>()]|<[^<>()]*>)*>)*>)?\s*\($")


def _strip_attrs(h: str) -> str:
    h = h.strip()
    while h.startswith("["):
        depth = 0
        for k, ch in enumerate(h):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    h = h[k + 1:].strip()
                    break
        else:
            break
    while h.startswith("@") and not h.startswith("@interface"):  # Java annotations
        m = re.match(r"@[\w.]+(?:\s*\([^)]*\))?\s*", h)
        if not m:
            break
        h = h[m.end():]
    return h


def _has_assign(h: str) -> bool:
    return re.search(r"(?<![=!<>+\-*/%&|^])=(?![=>])", h) is not None


def _first_paren(h: str) -> int:
    depth = 0
    for k, ch in enumerate(h):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "(" and depth == 0:
            return k
    return -1


class CSharp(BraceLanguage):
    name = "csharp"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), quotes=('"', "'"),
                    csharp_strings=True, char_literals_only=True)
    java = False

    def premask(self, text: str) -> str:
        if self.java:
            return text
        pre, self._inactive = preprocessor_branches(text)
        return pre

    def extra_surface(self, masked: Masked) -> list[str]:
        """Public declarations in inactive ``#else``/``#elif`` branches: the walker only
        sees the first branch, but the other branch's API is still this file's API."""
        out = []
        for label, line in getattr(self, "_inactive", []):
            st = _strip_attrs(line.strip())
            if re.match(r"(?:public|protected|internal)\b", st):
                for cut in ("{", "=>"):
                    if cut in st:
                        st = st.split(cut)[0]
                out.append(f"{label} {norm(st)}")
        return out

    def _exported(self, h: str, parent: _Scope) -> bool:
        if parent.kind in ("interface", "@interface"):
            return True
        words = set(re.findall(r"\b(public|protected|internal)\b", h))
        if self.java:
            return bool(words & {"public", "protected"})
        return bool(words)

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs = leading_attrs(raw)
        h = _strip_attrs(header)
        if not h:
            return Decl("block")
        first = re.match(r"[A-Za-z_]\w*", h)
        word = first.group(0) if first else ""
        m = _NS_RX.match(h)
        if m:
            return Decl("namespace", m.group(1), exported=False)
        m = _TYPE_RX.match(h)
        if m:
            kind = m.group(1).split()[0].lstrip("@")
            return Decl(kind if kind != "@interface" else "interface", m.group(2), self._exported(h, parent), attrs)
        if word in _CONTROL and (word not in ("static", "default") or h in ("static", "default")):
            return Decl("block")
        if word in _ACCESSORS and len(h.split()) <= 2:
            return Decl("block")
        if "=>" in h or _has_assign(h.split("(")[0] if "(" in h else h):
            return Decl("init")
        p = _first_paren(h)
        if p >= 0:
            before = h[:p + 1]
            op = re.search(r"\boperator\s*([^\s(]+)\s*\($", before)
            if op:
                return Decl("operator", "operator " + op.group(1), self._exported(h, parent), attrs,
                            signature=_sig(raw))
            mm = _IDENT_BEFORE_PAREN.search(before)
            if not mm:
                return Decl("block")
            name = mm.group(1)
            if name in _CONTROL or name in ("new", "base", "this"):
                return Decl("block")
            kind = "method"
            if name == enclosing_type:
                kind = "constructor"
            elif name.startswith("~"):
                kind = "destructor"
            return Decl(kind, name, self._exported(h, parent), attrs, signature=_sig(raw))
        if re.search(r"\bthis\s*\[", h):
            return Decl("indexer", "this[]", self._exported(h, parent), attrs, signature=_sig(raw))
        names = re.findall(r"[A-Za-z_]\w*", h)
        if not names:
            return Decl("block")
        kind = "event" if re.search(r"\bevent\b", h) else "property"
        return Decl(kind, names[-1], self._exported(h, parent), attrs, signature=_sig(raw))

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs = leading_attrs(raw)
        h = _strip_attrs(stmt)
        if not h or parent.kind == "enum":
            return None
        first = re.match(r"[A-Za-z_]\w*", h)
        word = first.group(0) if first else ""
        if word in ("using", "import", "extern", "global"):
            return None
        m = _NS_RX.match(h)
        if m:
            return None  # file-scoped namespace / Java package: not a navigation target
        if parent.kind == "file" and not (_TYPE_RX.match(h) or re.match(r"(?:\w+\s+)*delegate\b", h)):
            return None  # top-level statements (C# 9 scripts) are not declarations
        m = _TYPE_RX.match(h)
        if m:  # `record Point(int X, int Y);`
            kind = m.group(1).split()[0]
            return Decl(kind, m.group(2), self._exported(h, parent), attrs, signature=_sig(raw))
        arrow = h.find("=>")
        p = _first_paren(h)
        if arrow >= 0:
            if re.search(r"\bthis\s*\[", h[:arrow]):
                return Decl("indexer", "this[]", self._exported(h, parent), attrs, signature=_sig(raw, "=>"))
            if 0 <= p < arrow:
                mm = _IDENT_BEFORE_PAREN.search(h[:p + 1])
                if mm:
                    return Decl("method", mm.group(1), self._exported(h, parent), attrs, signature=_sig(raw, "=>"))
            names = re.findall(r"[A-Za-z_]\w*", h[:arrow])
            return Decl("property", names[-1], self._exported(h, parent), attrs, signature=_sig(raw, "=>")) if names else None
        if p >= 0 and not _has_assign(h[:p]):
            op = re.search(r"\boperator\s*([^\s(]+)\s*\($", h[:p + 1])
            if op:
                return Decl("operator", "operator " + op.group(1), self._exported(h, parent), attrs, signature=_sig(raw))
            mm = _IDENT_BEFORE_PAREN.search(h[:p + 1])
            if mm:
                kind = "delegate" if re.search(r"\bdelegate\b", h) else "method"
                return Decl(kind, mm.group(1), self._exported(h, parent), attrs, signature=_sig(raw))
            return None
        lhs = re.split(r"(?<![=!<>])=(?![=>])", h, maxsplit=1)[0]
        names = re.findall(r"[A-Za-z_]\w*", lhs.split(",")[0])
        if not names:
            return None
        name = names[-1]
        kind = "const" if re.search(r"\bconst\b", lhs) or (self.java and re.search(r"\bstatic\s+final\b", lhs)) \
            else "event" if re.search(r"\bevent\b", lhs) else "field"
        exported = self._exported(lhs, parent)
        sig = norm(_strip_attrs(raw))
        if len(sig) > 160:
            sig = norm(_strip_attrs(raw).split("=")[0]) + " = …"
        return Decl(kind, name, exported, attrs, signature=sig)


class Java(CSharp):
    name = "java"
    java = True
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), quotes=('"', "'"),
                    triple_quotes=('"""',), char_literals_only=True)


def _sig(raw: str, cut: str = "{") -> str:
    s = _strip_attrs(raw)
    if cut in s:
        s = s.split(cut)[0]
    return norm(s)
