"""Go: functions, methods (by receiver), struct and interface types, const and var groups.

Exported: the name starts with a capital letter.
"""

from __future__ import annotations

import re

from ._decl import _IDENT, _short, _sig, _skip_balanced
from .brace import BraceLanguage, Decl, _Scope
from .scan import Syntax, mask

_GO_FUNC = re.compile(rf"^func\s*(?:\(\s*(?:{_IDENT}\s+)?\*?\s*({_IDENT})[^)]*\)\s*)?({_IDENT})\s*[\[(]")
_GO_TYPE = re.compile(rf"^type\s+({_IDENT})\s*(?:\[[^\]]*\])?\s*(struct|interface)\b")


def _go_exported(name: str) -> bool:
    return name[:1].isupper()


class Go(BraceLanguage):
    name = "go"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), quotes=('"', "'"), backtick="raw",
                    char_literals_only=True)
    terminators = ";\n"
    functions_are_types = True

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        h = header.strip()
        if parent.kind in ("struct", "interface"):
            names = re.findall(_IDENT, h)
            return Decl("field", names[0], _go_exported(names[0]), signature=_sig(raw)) if names else Decl("block")
        m = _GO_FUNC.match(h)
        if m:
            recv, name = m.group(1), m.group(2)
            if recv:
                return Decl("method", name, _go_exported(name), signature=_sig(raw), container=recv)
            return Decl("function", name, _go_exported(name), signature=_sig(raw))
        m = _GO_TYPE.match(h)
        if m:
            return Decl(m.group(2), m.group(1), _go_exported(m.group(1)), signature=_sig(raw))
        return Decl("init") if re.search(r"(?<![=!<>:])(?::?=)(?!=)", h) else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope,
                           enclosing_type: str) -> Decl | list[Decl] | None:
        h = stmt.strip()
        if parent.kind == "struct":
            names = re.findall(_IDENT, h.lstrip("*"))
            if not names:
                return None
            # `Name Type` → Name; embedded `pkg.Type` / `*Type` → Type
            embedded = len(h.split()) == 1
            name = names[-1] if embedded else names[0]
            return Decl("field", name, _go_exported(name), signature=_sig(raw, ()))
        if parent.kind == "interface":
            m = re.match(rf"({_IDENT})\s*\(", h)
            if m:
                return Decl("method", m.group(1), _go_exported(m.group(1)), signature=_sig(raw, ()))
            return None
        if parent.kind != "file":
            return None
        m = re.match(r"(const|var|type)\s*\(", h)
        if m:
            return self._group(m.group(1), raw)
        m = re.match(rf"(const|var|type)\s+({_IDENT})", h)
        if m:
            kw, name = m.group(1), m.group(2)
            kind = {"const": "const", "var": "var", "type": "type"}[kw]
            return Decl(kind, name, _go_exported(name), signature=_short(raw))
        m = _GO_FUNC.match(h)
        if m:  # assembly-backed declaration without a body
            return Decl("function", m.group(2), _go_exported(m.group(2)), signature=_sig(raw, ()))
        return None

    def _group(self, kw: str, raw: str) -> list[Decl]:
        """``const ( A = iota; B )``: one symbol per item, located on its own line."""
        masked = mask(raw, self.syntax).text
        open_ = masked.find("(")
        close = _skip_balanced(masked, open_) - 1
        out: list[Decl] = []
        depth = 0
        k = open_ + 1
        for line in masked[open_ + 1:close].split("\n"):
            if depth == 0:
                m = re.match(rf"\s*({_IDENT})", line)
                if m:
                    names_end = re.match(rf"\s*{_IDENT}(?:\s*,\s*{_IDENT})*", line).end()
                    for nm in re.finditer(_IDENT, line[:names_end]):
                        at = k + nm.start()
                        out.append(Decl(kw if kw != "type" else "type", nm.group(0), _go_exported(nm.group(0)),
                                        signature=_short(kw + " " + raw[k:k + len(line)].strip()), at=at,
                                        span=len(line) - nm.start()))
            depth += sum(line.count(c) for c in "([{") - sum(line.count(c) for c in ")]}")
            depth = max(0, depth)
            k += len(line) + 1
        return out
