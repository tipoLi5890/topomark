"""JavaScript / TypeScript / JSX / TSX (ES modules and CommonJS).

Exported = has ``export`` (ESM), or is named in ``module.exports = {...}`` /
``exports.x =`` (CommonJS). The surface is the header comment, every exported
declaration's signature, and the CommonJS export lists verbatim. Top-level
functions and exported functions/consts count as the file's "types" for fan-in,
since JS modules are referenced by function names, not classes. Imports =
specifiers of ``import … from``, ``import "x"``, ``export … from``, ``require()``
and ``import()``; a computed ``require(x)`` / ``import(`./${x}`)`` records ``DYNAMIC``.
"""

from __future__ import annotations

import re

from .base import DYNAMIC, norm
from .brace import BraceLanguage, Decl, _Scope
from .scan import Masked, Syntax

_CONTROL = {"if", "else", "for", "while", "do", "switch", "try", "catch", "finally", "with", "return", "case",
            "default", "new", "await", "yield", "throw", "typeof", "void", "delete", "in", "of"}
_FUNC = re.compile(r"^(export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)?")
_CLASS = re.compile(r"^(export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
_IFACE = re.compile(r"^(export\s+)?(?:declare\s+)?interface\s+([A-Za-z_$][\w$]*)")
_ENUM = re.compile(r"^(export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)")
_NS = re.compile(r"^(export\s+)?(?:declare\s+)?(?:namespace|module)\s+([\w$.\"']+)")
_TYPE = re.compile(r"^(export\s+)?(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)")
_VAR = re.compile(r"^(export\s+)?(?:default\s+)?(?:declare\s+)?(const|let|var)\s+([A-Za-z_$][\w$]*)")
_ARROWISH = re.compile(r"=\s*(?:async\s+)?(?:function\b|(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>)")
_METHOD = re.compile(r"^(?:(?:public|private|protected|static|readonly|abstract|override|async|declare|get|set|accessor)\s+)*"
                     r"\*?\s*(#?[A-Za-z_$][\w$]*)\s*(?:<[^()]*>)?\s*\(")
_CLASS_FIELD = re.compile(r"^(?:(?:public|private|protected|static|readonly|abstract|override|declare|accessor)\s+)*"
                          r"(#?[A-Za-z_$][\w$]*)\s*[?!]?\s*(?::[^=]+)?=")
# On masked text (string literals blanked): where a module specifier string may start.
_SPECIFIER_AT = re.compile(r"(?<![.\w$])(?:(import|require)\s*\(|(?:from|import)(?![\w$]))")
_STRING_AT = re.compile(r"\s*(?:(['\"])([^'\"\n]*)\1|`([^`$]*)`)")  # on the original text


class JsTs(BraceLanguage):
    name = "js"
    syntax = Syntax(line_comments=("//",), block_comments=(("/*", "*/"),), quotes=('"', "'"), backtick="template",
                    regex_literals=True)
    terminators = ";\n"
    functions_are_types = True

    def analyze(self, path: str, text: str):  # type: ignore[override]
        self._cjs = _commonjs_exports(text)
        info = super().analyze(path, text)
        info.lang = "ts" if path.endswith((".ts", ".tsx", ".mts", ".cts")) else "js"
        for s in info.symbols:
            if not s.container and s.name in self._cjs:
                s.exported = True
        info.types = list(dict.fromkeys(
            s.name for s in info.symbols
            if not s.container and s.kind in ("class", "interface", "enum", "function", "type", "const")
            and (s.exported or s.kind in ("class", "function"))))
        return info

    def imports_of(self, masked: Masked) -> list[str]:
        out: list[str] = []
        for hit in _SPECIFIER_AT.finditer(masked.text):
            lit = _STRING_AT.match(masked.original, hit.end())
            if lit:
                spec = lit.group(2) if lit.group(2) is not None else lit.group(3)
            elif hit.group(1):  # require(name) / import(`./pages/${name}`)
                spec = DYNAMIC
            else:
                continue
            if spec and spec not in out:
                out.append(spec)
        return out

    def _exp(self, export_kw: str | None, name: str) -> bool:
        return bool(export_kw) or name in getattr(self, "_cjs", set())

    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        h = header.strip()
        if not h:
            return Decl("block")
        if h.startswith("@"):  # decorators on their own line
            h = re.sub(r"^(?:@[\w.$]+(?:\([^)]*\))?\s*)+", "", h)
        word = re.match(r"[A-Za-z_$][\w$]*", h)
        w = word.group(0) if word else ""
        if parent.kind in ("class", "interface"):
            if w in _CONTROL:
                return Decl("block")
            if w == "constructor":
                return Decl("constructor", "constructor", True, signature=_sig(raw))
            m = _CLASS_FIELD.match(h)
            if m and "=>" in h:
                return Decl("method", m.group(1), not m.group(1).startswith("#") and "private" not in h.split(m.group(1))[0],
                            signature=_sig(raw, "=>"))
            m = _METHOD.match(h)
            if m:
                name = m.group(1)
                kind = "getter" if re.match(r"(?:static\s+)?get\s", h) else "setter" if re.match(r"(?:static\s+)?set\s", h) \
                    else "method"
                private = name.startswith("#") or bool(re.match(r"(?:\w+\s+)*private\b", h))
                return Decl(kind, name, not private, signature=_sig(raw))
            return Decl("init") if "=" in h else Decl("block")
        if _open_angle(h):  # `class A<T extends { id: Id }>`: the brace belongs to the generics
            return Decl("init")
        if h in ("export default", "export default async"):  # `export default { fetch() {…}, … }`
            return Decl("exports", "default", True, signature="export default {", surface="")
        dm = re.match(r"^(export\s+)?declare\s+(module|global)\b", h)
        if dm:  # `declare module 'foo' {`: the name is a (masked) string, read it from the raw header
            rm = re.search(r"\b(?:module|global)\s*(['\"]?)([^'\"\s{]*)\1", raw)
            name = (rm.group(2) if rm else "") or dm.group(2)
            return Decl("namespace", name, True, signature=_sig(raw))
        for rx, kind in ((_CLASS, "class"), (_IFACE, "interface"), (_ENUM, "enum"), (_NS, "namespace")):
            m = rx.match(h)
            if m:
                name = m.group(2).strip("\"'")
                return Decl(kind, name, self._exp(m.group(1), name), signature=_sig(raw))
        m = _FUNC.match(h)
        if m and "function" in h.split("(")[0]:
            name = m.group(2) or "default"
            return Decl("function", name, self._exp(m.group(1), name) or "export default" in h, signature=_sig(raw))
        m = _VAR.match(h)
        if m and _ARROWISH.search(h):
            name = m.group(3)
            return Decl("function", name, self._exp(m.group(1), name), signature=_sig(raw, "=>"))
        m = _TYPE.match(h)
        if m:
            return Decl("init")
        return Decl("init") if "=" in h else Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        h = stmt.strip()
        if not h or h.startswith(("import ", "import{", "'use", '"use')):
            return None
        if parent.kind in ("class", "interface"):
            m = _CLASS_FIELD.match(h) or re.match(r"^(?:(?:public|private|protected|static|readonly|declare)\s+)*"
                                                   r"(#?[A-Za-z_$][\w$]*)\s*[?!]?\s*:", h)
            if m and m.group(1) not in _CONTROL:
                name = m.group(1)
                private = name.startswith("#") or "private" in h.split(name)[0]
                return Decl("field", name, not private, signature=_short(raw))
            m = _METHOD.match(h)  # interface method signatures / abstract methods
            if m:
                return Decl("method", m.group(1), True, signature=_short(raw))
            return None
        if parent.kind not in ("file", "namespace", "module"):
            return None
        if h.startswith(("module.exports", "exports.")):
            name = "module.exports" if h.startswith("module.exports") else h.split("=")[0].strip()
            return Decl("exports", name, True, signature=_short(raw, 400), surface=norm(raw))
        if h.startswith("export {") or h.startswith("export *") or h.startswith("export default") and "(" not in h:
            return Decl("exports", "export", True, signature=_short(raw, 400), surface=norm(raw))
        if h.startswith("export default") and not re.match(r"export default (?:async\s+)?(?:function|class)\b", h):
            # `export default [ route(...), ... ] satisfies RouteConfig;` / `export default defineConfig({...})`:
            # the expression is the module's interface (a route table, a config), so it goes into the surface.
            return Decl("exports", "default", True, signature=_short(raw, 200), surface=norm(raw)[:4000])
        m = _TYPE.match(h)
        if m:
            return Decl("type", m.group(2), self._exp(m.group(1), m.group(2)), signature=_short(raw))
        m = _FUNC.match(h)
        if m and m.group(2) and "function" in h.split("(")[0]:  # `declare function f(): T;` / overloads
            return Decl("function", m.group(2), self._exp(m.group(1), m.group(2)), signature=_short(raw))
        m = _VAR.match(h)
        if m:
            name = m.group(3)
            if re.search(r"=\s*require\(", h):
                return None
            kind = "function" if _ARROWISH.search(h) else "const"
            exported = self._exp(m.group(1), name)
            if kind == "const" and not exported and not name.isupper():
                return None  # module-private variables are not navigation targets
            return Decl(kind, name, exported, signature=_short(raw))
        return None


    def _close(self, scope: _Scope, i: int, m, text: str, surface: list[str]) -> None:
        super()._close(scope, i, m, text, surface)
        sym = scope.sym
        if sym is not None and sym.kind == "exports" and sym.name == "default":
            keys = _object_keys(text[scope.open_at + 1:i])
            sym.signature = "export default { " + ", ".join(keys) + " }"
            surface.append(sym.signature)


_OBJ_KEY = re.compile(r"\s*(?:\.\.\.\s*)?(?:(?:async|static)\s+)*\*?\s*(?:(?:get|set)\s+(?=[\w$#]))?([A-Za-z_$#][\w$]*)\s*"
                      r"(\(|:\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|[\w$]+\s*=>))?")


def _object_keys(body: str) -> list[str]:
    """Top-level keys of a (masked) object literal body; methods get ``()``."""
    flat = []
    depth = 0
    for ch in body:  # blank nested braces so only depth-1 keys remain
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        flat.append(ch if depth == 0 and ch not in "{}" else " ")
    out = []
    pdepth = 0
    start = 0
    text = "".join(flat)
    parts = []
    for k, ch in enumerate(text):
        if ch in "([":
            pdepth += 1
        elif ch in ")]":
            pdepth = max(0, pdepth - 1)
        elif ch == "," and pdepth == 0:
            parts.append(text[start:k])
            start = k + 1
    parts.append(text[start:])
    for part in parts:
        km = _OBJ_KEY.match(part)
        if km and part.strip():
            out.append(km.group(1) + ("()" if km.group(2) else ""))
    return out


_CJS_OBJ = re.compile(r"module\.exports\s*=\s*\{([^}]*)\}", re.S)
_CJS_PROP = re.compile(r"(?:^|\n)\s*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=")
_CJS_SINGLE = re.compile(r"module\.exports\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$", re.M)


def _commonjs_exports(text: str) -> set[str]:
    names: set[str] = set()
    for m in _CJS_OBJ.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            key = re.match(r"([A-Za-z_$][\w$]*)", part)
            val = re.search(r":\s*([A-Za-z_$][\w$]*)\s*$", part)
            if key:
                names.add(key.group(1))
            if val:
                names.add(val.group(1))
    names.update(_CJS_PROP.findall(text))
    names.update(_CJS_SINGLE.findall(text))
    return names


def _open_angle(h: str) -> bool:
    """True when the header ends inside ``<...>`` generics (arrows and comparisons ignored)."""
    if "<" not in h:
        return False
    s = h.replace("=>", "  ").replace(">=", "  ").replace("<=", "  ")
    depth = 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">" and depth:
            depth -= 1
    return depth > 0 and bool(re.match(r"(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?"
                                       r"(?:class|interface|type|function|async|const|let|var)\b|[\w$#]+\s*<", s.strip()))


def _sig(raw: str, cut: str = "") -> str:
    """Block headers already stop at the body brace; only arrow functions cut at ``=>``."""
    s = raw.strip()
    if cut and cut in s:
        s = s.split(cut)[0] + cut
    s = norm(s)
    return s if len(s) <= 200 else s[:199] + "…"


def _short(raw: str, limit: int = 160) -> str:
    s = norm(raw)
    if len(s) <= limit:
        return s
    head = s.split("=")[0].strip() if "=" in s else s[:limit]
    return head + " = …" if "=" in s else head + "…"
