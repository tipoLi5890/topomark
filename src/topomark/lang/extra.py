"""Brace-language adapters beyond C#/Java/JS: Dart, Kotlin, Swift, Go, Rust and
the C family (C, C++, Objective-C).

Each adapter is a ``BraceLanguage`` with its own masking ``Syntax`` and two
pragmatic classifiers: an outline for navigation, not a compiler. Shared rules:

* signatures stop at the body (``{``) or an expression body (``=>`` / ``=``)
  and are capped at 200 characters;
* "exported" follows the language's visibility convention (Dart/Go: the name;
  Kotlin/Swift: no ``private``; Rust: ``pub``; C: not ``static``, C++ members:
  ``public``/``protected``);
* enum members go into the surface (``enum_members``), function bodies never
  get classified.
"""

from __future__ import annotations

import re

from .base import FileInfo, Symbol, norm
from .brace import BraceLanguage, Decl, _Scope, preprocessor_branches
from .scan import Masked, Syntax, mask

_IDENT = r"[A-Za-z_]\w*"
_TYPE_SCOPES = {"class", "struct", "interface", "enum", "record", "object", "trait", "protocol", "extension",
                "impl", "mixin"}


# ---------------------------------------------------------------- shared helpers
def _sig(raw: str, cuts: tuple[str, ...] = (), limit: int = 200) -> str:
    """Normalized declaration text cut before the first of ``cuts`` (expression body).

    Block headers already stop before the body brace, so they pass no cuts: a
    ``{`` inside the parameters (Dart named parameters) must survive."""
    s = raw.strip()
    for cut in cuts:
        k = s.find(cut)
        if k > 0:
            s = s[:k]
    s = norm(s)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _skip_balanced(s: str, k: int, open_: str = "(", close: str = ")") -> int:
    """Index just past the bracket group opening at ``s[k]`` (or len(s))."""
    depth = 0
    for j in range(k, len(s)):
        if s[j] == open_:
            depth += 1
        elif s[j] == close:
            depth -= 1
            if depth == 0:
                return j + 1
    return len(s)


def split_top(s: str, sep: str) -> list[tuple[int, str]]:
    """Split ``s`` at ``sep`` outside brackets; returns ``(offset, part)`` pairs."""
    out: list[tuple[int, str]] = []
    depth = 0
    start = 0
    for k, ch in enumerate(s):
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>" and depth > 0:
            if not (ch == ">" and k > 0 and s[k - 1] in "-="):  # `->` / `=>` are not brackets
                depth -= 1
        elif ch == sep and depth == 0:
            out.append((start, s[start:k]))
            start = k + 1
    out.append((start, s[start:]))
    return out


def first_paren(h: str) -> int:
    """Offset of the first ``(`` outside ``<...>`` generics, or -1."""
    depth = 0
    for k, ch in enumerate(h):
        if ch == "<":
            depth += 1
        elif ch == ">" and depth > 0 and h[k - 1:k] not in ("-", "="):
            depth -= 1
        elif ch == "(" and depth == 0:
            return k
    return -1


_ANNOT = re.compile(r"@[\w.:]+")


def strip_annotations(h: str) -> tuple[list[str], str]:
    """Leading ``@Foo`` / ``@Foo(args)`` / ``@field:Foo`` annotations → (attrs, rest)."""
    attrs: list[str] = []
    s = h.strip()
    while s.startswith("@"):
        m = _ANNOT.match(s)
        if not m:
            break
        end = m.end()
        rest = s[end:].lstrip()
        if rest.startswith("("):
            end = len(s) - len(rest)
            end = _skip_balanced(s, end)
        attrs.append(norm(s[1:end]))
        s = s[end:].lstrip()
    return attrs, s


def top_level_only(body: str) -> str:
    """``body`` with the contents of nested ``{...}`` blanked (offsets kept)."""
    out = list(body)
    depth = 0
    for k, ch in enumerate(body):
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            continue
        if depth and ch != "\n":
            out[k] = " "
    return "".join(out)


def _enum_entries(body: str, stop_at_semicolon: bool = True) -> list[str]:
    """Leading identifiers of comma-separated entries (Kotlin/Dart/Rust enums)."""
    flat = top_level_only(body)
    if stop_at_semicolon:
        semi = flat.find(";")
        flat = flat if semi < 0 else flat[:semi]
    out = []
    for _, part in split_top(flat, ","):
        part = re.sub(r"^\s*(?:#\[[^\]]*\]\s*|@[\w.]+(?:\([^)]*\))?\s*)*", "", part)
        m = re.match(rf"\s*({_IDENT})", part)
        if m:
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------- Kotlin
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

    def _exported(self, mods: str) -> bool:
        return not re.search(r"\b(private|internal)\b", mods)

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        attrs, h = strip_annotations(header)
        if not h:
            return Decl("block")
        word = re.match(r"\w*", h).group(0)
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


# ---------------------------------------------------------------- Swift
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


def _is_kind(info: FileInfo, name: str, kind: str) -> bool:
    """True when every top-level symbol called ``name`` is of ``kind`` (an extension/impl, not a declaration)."""
    kinds = {s.kind for s in info.symbols if not s.container and s.name == name}
    return kinds == {kind}


# ---------------------------------------------------------------- Dart
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
        if re.search(r"(?<![=!<>])=(?![=>])", before) or re.match(r"\w*", before).group(0) in _DART_CONTROL:
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


# ---------------------------------------------------------------- Go
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


def _short(raw: str, limit: int = 160) -> str:
    s = norm(raw)
    if len(s) <= limit:
        return s
    return (s.split("=")[0].strip() + " = …") if "=" in s else s[:limit - 1] + "…"


# ---------------------------------------------------------------- Rust
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


# ---------------------------------------------------------------- C / C++ / Objective-C
_C_CONTROL = {"if", "else", "for", "while", "do", "switch", "try", "catch", "return", "sizeof", "alignof", "decltype",
              "static_assert", "case", "default", "goto", "throw", "new", "delete", "__attribute__", "__declspec",
              "alignas", "noexcept", "requires", "defined", "_Static_assert", "__pragma", "typeof", "__typeof__"}
_C_ATTR = re.compile(r"\[\[.*?\]\]|__attribute__\s*\(\((?:[^()]|\([^()]*\))*\)\)|__declspec\s*\([^)]*\)|"
                     r"alignas\s*\([^)]*\)")
_C_TYPE = re.compile(r"^(?:typedef\s+)?(class|struct|union|enum(?:\s+(?:class|struct))?)\b(.*)$")
_C_ACCESS = re.compile(r"^(public|private|protected|signals|(?:public|private|protected)?\s*(?:Q_)?slots)\s*:(?!:)\s*")
_C_MACRO_LEAD = re.compile(r"^[A-Z][A-Z0-9_]{2,}\s+(?=[A-Za-z_~])")
_C_TEMPLATE = re.compile(r"^template\s*")
_C_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)(\()?", re.M)
_OBJC_CONTAINER = re.compile(r"^@(interface|implementation|protocol)\s+([A-Za-z_]\w*)[^\n]*", re.M)
_OBJC_DIRECTIVE = re.compile(r"^[ \t]*@(?:interface|implementation|protocol|end|synthesize|dynamic|class|"
                             r"compatibility_alias)\b[^\n{]*", re.M)
_OBJC_METHOD = re.compile(r"^\s*([-+])\s*\(")
_C_HEADERS = (".h", ".hh", ".hpp", ".hxx", ".h++", ".inl")


def _strip_template(h: str) -> str:
    while True:
        m = _C_TEMPLATE.match(h)
        if not m or not h[m.end():].startswith("<"):
            return h
        h = h[_skip_balanced(h, m.end(), "<", ">"):].lstrip()


def _still_declaration(rest: str) -> bool:
    """After stripping a leading ALL-CAPS token, is the rest still a declaration?

    ``EXPORT_API int api(void)`` yes; ``FILE *fp`` / ``BOOL flag = TRUE`` no: there
    the capitalized word is the type itself."""
    if _C_ACCESS.match(rest):
        return True
    head = re.split(r"[=(;{\[]", rest, maxsplit=1)[0]
    return len(re.findall(_IDENT, head)) >= 2


def _macro_like(name: str) -> bool:
    return len(name) > 2 and name.isupper()


def _assign_at(h: str) -> int:
    """Offset of the top-level ``=`` of an initializer (not ``==``, ``<=``, ``+=``…), or -1."""
    depth = 0
    for k, ch in enumerate(h):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0 and h[k + 1:k + 2] != "=" and (k == 0 or h[k - 1] not in "=!<>+-*/%&|^"):
            return k
    return -1


def _objc_selector(h: str) -> str:
    """``- (void)foo:(int)a bar:(id)b`` → ``foo:bar:``; ``- (id)init`` → ``init``."""
    s = re.sub(r"\([^()]*(?:\([^()]*\)[^()]*)*\)", " ", h[1:])
    parts = re.findall(rf"({_IDENT})\s*:", s)
    if parts:
        return "".join(p + ":" for p in parts)
    m = re.search(_IDENT, s)
    return m.group(0) if m else "?"


class CFamily(BraceLanguage):
    """C, C++ and Objective-C; ``name`` is set per file from the extension."""

    name = "c"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), quotes=('"', "'"),
                    char_literals_only=True, cpp_raw=True)

    def analyze(self, path: str, text: str) -> FileInfo:
        low = path.lower()
        self.name = "objc" if low.endswith((".m", ".mm")) else "c" if low.endswith(".c") else "cpp"
        self._header_file = low.endswith(_C_HEADERS)
        self._access: dict[int, str] = {}
        self._objc = "@interface" in text or "@implementation" in text or "@protocol" in text
        self._inactive: list[tuple[str, str]] = []
        self._renamed: list[Symbol] = []
        info = super().analyze(path, text)
        for owner in self._renamed:  # members were created before `} Name;` named their struct
            for s in info.symbols:
                if s is not owner and not s.container and owner.start < s.line <= owner.end:
                    s.container, s.qualname = owner.name, owner.name + "." + s.name
            if owner.name != "(anonymous)" and owner.name not in info.types and not owner.container:
                info.types.append(owner.name)
        if self._objc:
            self._objc_containers(info, text)
        if "#" in text and "define" in text:
            self._macros(info, text)
        return info

    def premask(self, text: str) -> str:
        pre, self._inactive = preprocessor_branches(text)
        if getattr(self, "_objc", False):
            # `@interface Foo : NSObject` lines would glue onto the first member's header
            pre = _OBJC_DIRECTIVE.sub(lambda mm: " " * len(mm.group(0)), pre)
        return pre

    def extra_surface(self, masked: Masked) -> list[str]:
        """Function declarations at column 0 in inactive ``#else``/``#elif`` branches."""
        out = []
        for label, line in self._inactive:
            st = line.strip()
            if line[:1] in " \t" or st.startswith(("static ", "return ", "}", "//", "/*", "*", "#")):
                continue
            if re.match(r"^[A-Za-z_][\w\s*&:<>,~]*\(", st):
                out.append(f"{label} {_sig(st, ('{',))}")
        return out

    def decl_offset(self, masked_head: str) -> int:
        k = 0
        while True:
            m = _C_ACCESS.match(masked_head, k)
            if not m:
                m = _C_MACRO_LEAD.match(masked_head, k)
                if m and not _still_declaration(masked_head[m.end():]):
                    m = None
            if not m or m.end() == k:
                return k
            k = m.end()
            while k < len(masked_head) and masked_head[k].isspace():
                k += 1

    # ---- access tracking (C++ classes) ----------------------------------
    def _take_access(self, h: str, parent: _Scope) -> str:
        while True:
            m = _C_ACCESS.match(h)
            if not m:
                break
            self._access[parent.open_at] = m.group(1).split()[0]
            h = h[m.end():]
        while True:  # Q_OBJECT, EXPORT_API and similar bare macros before a declaration
            m = _C_MACRO_LEAD.match(h)
            if not m or not _still_declaration(h[m.end():]):
                break
            h = h[m.end():]
            mm = _C_ACCESS.match(h)
            if mm:
                self._access[parent.open_at] = mm.group(1).split()[0]
                h = h[mm.end():]
        return h

    def _exported(self, h: str, parent: _Scope) -> bool:
        if parent.kind in ("class", "struct", "union"):
            default = "private" if parent.kind == "class" else "public"
            return self._access.get(parent.open_at, default) in ("public", "protected", "signals")
        return not re.match(r"^(?:\w+\s+)*?static\b", h) and parent.kind != "body"

    # ---- classifiers ----------------------------------------------------
    def _clean(self, header: str, parent: _Scope) -> str:
        h = _C_ATTR.sub(" ", header)
        h = self._take_access(h.strip(), parent)
        return norm(_strip_template(h))

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        h = self._clean(header, parent)
        if not h:
            return Decl("block")
        if parent.kind == "enum":
            return Decl("block")
        if _OBJC_METHOD.match(h):
            return Decl("method", _objc_selector(h), True, signature=_sig(raw))
        m = re.match(r"^(?:inline\s+)?namespace\b\s*([\w:]*)", h)
        if m:
            return Decl("namespace", m.group(1).replace("::", "."), False) if m.group(1) else Decl("transparent")
        if re.match(r"^extern\s*$", h):
            return Decl("transparent")  # extern "C" { … }
        if re.search(r"(?<![=!<>+\-*/%&|^])=(?![=])", h.split("(")[0]):
            return Decl("init")  # `int a[] = {…}`, `auto f = [](…) {…}`
        if re.search(r"\)\s*(?:const\s*)?(?:noexcept\s*)?:\s*[^:]", h) and re.search(r"[\w>]\s*$", h):
            return Decl("init")  # constructor initializer `: a{1}`: the real body comes later
        m = _C_TYPE.match(h)
        if m and "(" not in m.group(2):
            kind = m.group(1).split()[0]
            names = [x for x in re.findall(_IDENT, m.group(2).split(":")[0]) if x not in ("final", "sealed")]
            name = names[-1] if names else ""
            return Decl("struct" if kind == "union" else kind, name, self._exported(h, parent),
                        signature=_sig(raw))
        return self._function(h, raw, parent, enclosing_type) or Decl("block")

    def _function(self, h: str, raw: str, parent: _Scope, enclosing: str) -> Decl | None:
        """Definitions and prototypes: the name before the last meaningful ``(``."""
        cut = re.search(r"\)\s*(?:const\s*)?(?:noexcept\s*)?:\s*[^:]", h)
        if cut:
            h = h[:cut.start() + 1]
        op = re.search(r"((?:[\w]+\s*::\s*)*)operator\s*(\(\)|[^\s(]+|\s+[\w:<>*&\s]+?)\s*\(", h)
        if op:
            qual = op.group(1).replace(" ", "").rstrip(":")
            name = "operator" + norm(op.group(2)).replace(" ", "") if op.group(2) != "()" else "operator()"
            return Decl("operator", name, self._exported(h, parent), signature=_sig(raw),
                        container=qual.replace("::", ".") or None)
        pointer = re.match(rf"^[^(]*\((?:\s*{_IDENT})*\s*\*\s*({_IDENT})\s*(?:\[[^\]]*\])?\)\s*\(", h)
        if pointer:  # `void (*cb)(int)` / `void (API *cb)(int)`: a function-pointer field or variable
            kind = "field" if parent.kind in _TYPE_SCOPES else "var"
            return Decl(kind, pointer.group(1), self._exported(h, parent), signature=_sig(raw))
        cands: list[str] = []
        depth = 0
        for k, ch in enumerate(h):
            if ch == "<":
                depth += 1
            elif ch == ">" and depth > 0:
                depth -= 1
            elif ch == "(" and depth == 0:
                mm = re.search(r"((?:~?[A-Za-z_]\w*\s*::\s*)*~?[A-Za-z_]\w*)\s*(?:<[^()]*>)?\s*$", h[:k])
                if mm and mm.group(1).replace(" ", "").split("::")[-1] not in _C_CONTROL:
                    cands.append(mm.group(1).replace(" ", ""))
        # the first non-macro name wins (`EXPORT_API(int) foo(void)`); a lone macro call keeps its name
        best = next((c for c in cands if not _macro_like(c.split("::")[-1])), cands[0] if cands else None)
        if not best:
            return None
        parts = best.split("::")
        name = parts[-1]
        qual = ".".join(parts[:-1])
        owner = parts[-2] if len(parts) > 1 else enclosing
        kind = "destructor" if name.startswith("~") else "constructor" if owner and name == owner else \
            "method" if (qual or parent.kind in _TYPE_SCOPES) else "function"
        exported = True if qual else self._exported(h, parent)
        return Decl(kind, name, exported, signature=_sig(raw), container=qual or None)

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        h = self._clean(stmt, parent)
        if not h or parent.kind == "enum":
            return None
        if _OBJC_METHOD.match(h):
            return Decl("method", _objc_selector(h), True, signature=_sig(raw))
        m = re.match(r"^@property\s*(?:\([^)]*\))?\s*(.*)$", h)
        if m:
            names = re.findall(_IDENT, m.group(1))
            return Decl("property", names[-1], True, signature=_sig(raw)) if names else None
        word = re.match(r"\w*", h).group(0)
        if word in ("friend", "static_assert", "_Static_assert", "return", "goto") or h.startswith(("using namespace",
                                                                                                    "@")):
            return None
        if re.match(r"^(?:class|struct|union|enum(?:\s+class)?)\s+[\w:]+\s*(?::\s*[\w:\s]+)?$", h):
            return None  # forward declaration
        m = re.match(rf"^using\s+({_IDENT})\s*=", h)
        if m:
            return Decl("type", m.group(1), self._exported(h, parent), signature=_short(raw))
        if word == "using":
            return None
        if word == "typedef":
            ptr = re.search(rf"\((?:\s*{_IDENT})*\s*[*^&]\s*({_IDENT})\s*\)\s*\(", h)
            names = re.findall(_IDENT, re.sub(r"\[[^\]]*\]", "", h))
            name = ptr.group(1) if ptr else (names[-1] if names else "")
            return Decl("type", name, True, signature=_short(raw)) if name else None
        eq = _assign_at(h)
        lhs = h if eq < 0 else h[:eq]
        if first_paren(lhs) >= 0:
            if eq >= 0 and not re.match(r"\s*(?:0|default|delete)\s*$", h[eq + 1:]):
                return None  # `T (*f)(int) = g;` and other initialized declarators
            d = self._function(lhs, raw, parent, enclosing_type)
            if d:
                d.signature = _short(raw)
            return d
        lhs = re.sub(r"\[[^\]]*\]|:\s*\d+\s*$", "", split_top(lhs, ",")[0][1])
        names = re.findall(_IDENT, lhs)
        if len(names) < 2 or names[-1] in _C_CONTROL:
            return None  # a bare word or a macro call is not a declaration
        name = names[-1]
        is_const = re.search(r"\b(?:const|constexpr|constinit)\b", lhs) and "*" not in lhs.split(name)[0][-3:]
        kind = "const" if is_const else "field" if parent.kind in _TYPE_SCOPES else "var"
        return Decl(kind, name, self._exported(h, parent), signature=_short(raw))

    def _close(self, scope: _Scope, i: int, m: Masked, text: str, surface: list[str]) -> None:
        super()._close(scope, i, m, text, surface)
        if scope.sym is not None and not scope.sym.name:  # `typedef struct { … } Name;`
            mm = re.match(rf"\s*({_IDENT})\s*[;,\[]", text[i + 1:i + 200])
            name = mm.group(1) if mm else "(anonymous)"
            scope.sym.name = name
            scope.sym.qualname = (scope.sym.container + "." if scope.sym.container else "") + name
            self._renamed.append(scope.sym)

    # ---- post passes ----------------------------------------------------
    def _objc_containers(self, info: FileInfo, text: str) -> None:
        """``@interface``/``@implementation``/``@protocol`` … ``@end`` as containers of their methods."""
        masked = mask(text, self.syntax)
        lines = masked.text.split("\n")
        rlines = text.split("\n")
        added: list[Symbol] = []
        for cm in _OBJC_CONTAINER.finditer(masked.text):
            start = masked.line_of(cm.start())
            end = start
            for k in range(start, len(lines)):
                if lines[k].lstrip().startswith("@end"):
                    end = k + 1
                    break
            kind = {"interface": "class", "implementation": "class", "protocol": "protocol"}[cm.group(1)]
            name = cm.group(2)
            added.append(Symbol(kind=kind, name=name, qualname=name, start=start, end=end,
                                signature=norm(rlines[start - 1]), exported=True, line=start))
            for s in info.symbols:
                if not s.container and s.kind in ("method", "property") and start <= s.line <= end:
                    s.container, s.qualname = name, name + "." + s.name
        info.symbols = sorted(info.symbols + added, key=lambda s: (s.start, s.container != ""))
        for s in added:
            if s.name not in info.types:
                info.types.append(s.name)

    def _macros(self, info: FileInfo, text: str) -> None:
        masked = mask(text, self.syntax)  # without premask: every branch's #define counts
        rlines = text.split("\n")
        for dm in _C_DEFINE.finditer(masked.text):
            name = dm.group(1)
            if name.startswith("_") and name.endswith(("_H", "_H_", "_HPP", "_INCLUDED")) or name.endswith("_H"):
                continue  # include guards
            line = masked.line_of(dm.start())
            end = line
            while end < len(rlines) and masked.line_text(end).rstrip().endswith("\\"):
                end += 1
            sig = norm(masked.line_text(line).rstrip("\\"))
            info.symbols.append(Symbol(kind="macro", name=name, qualname=name, start=line, end=end,
                                       signature=sig[:200], exported=self._header_file, line=line))
            if self._header_file:
                info.surface += "\n" + norm(rlines[line - 1])[:200]
        info.symbols.sort(key=lambda s: s.start)


# ---------------------------------------------------------------- registration
def register(_register) -> None:
    _register((".dart",), Dart)
    _register((".kt", ".kts"), Kotlin)
    _register((".swift",), Swift)
    _register((".go",), Go)
    _register((".rs",), Rust)
    _register((".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".m", ".mm"), CFamily)


__all__ = ["CFamily", "Dart", "Go", "Kotlin", "Rust", "Swift", "register"]
