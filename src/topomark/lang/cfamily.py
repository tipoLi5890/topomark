"""C, C++ and Objective-C: types, functions and prototypes, macros, C++ members by access label,
Objective-C ``@interface`` / ``@implementation`` containers.

Exported: not ``static`` (C); ``public`` / ``protected`` members (C++).
"""

from __future__ import annotations

import re

from ._decl import _IDENT, _TYPE_SCOPES, _short, _sig, _skip_balanced, first_paren, split_top
from .base import FileInfo, Symbol, norm
from .brace import BraceLanguage, Decl, _Scope, preprocessor_branches
from .scan import Masked, Syntax, mask

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

    def imports_of(self, masked: Masked) -> list[str]:
        from ._imports import c_includes

        # the original on both sides: `premask` blanks preprocessor lines before the walker sees them
        return c_includes(masked.original, masked.original)

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
        # each word whole (\b): without it a long identifier can be split in every possible way before
        # the match fails, which took seconds on an ordinary constructor declaration
        pointer = re.match(rf"^[^(]*\((?:\s*\b{_IDENT}\b)*\s*\*\s*({_IDENT})\s*(?:\[[^\]]*\])?\)\s*\(", h)
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
        wm = re.match(r"\w*", h)
        assert wm is not None  # `\w*` matches the empty string
        word = wm.group(0)
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
            ptr = re.search(rf"\((?:\s*\b{_IDENT}\b)*\s*[*^&]\s*({_IDENT})\s*\)\s*\(", h)
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
