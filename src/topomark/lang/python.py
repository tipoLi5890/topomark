"""Python: indentation scopes on masked text.

Listed: classes (nested classes too), functions and methods directly inside a
module or class (functions nested inside functions are bodies, not listed),
UPPER_CASE module constants. Exported = no leading underscore, or named in
``__all__`` when the module defines it. Header = module docstring, else the
leading comment block. Imports = every ``import`` / ``from … import`` statement,
indented ones included (imports inside functions are common in CLIs), plus
``importlib.import_module`` / ``__import__`` with a literal name; a computed name
records ``DYNAMIC``.
"""

from __future__ import annotations

import ast
import re

from .base import DYNAMIC, FileInfo, Symbol, doc_summary, head_comment, idents_of, norm, surface_text
from .scan import Syntax, mask

SYNTAX = Syntax(line_comments=("#",), block_comments=(), quotes=('"', "'"), triple_quotes=('"""', "'''"),
                python_prefixes=True)
_DEF = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_]\w*)")
_CONST = re.compile(r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=(?!=)")
_DOCSTRING = re.compile(r'^(?:#![^\n]*\n)?(?:#[^\n]*\n|\s*\n)*\s*[rRuUbB]?("""|\'\'\')(.*?)\1', re.S)
_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w. \t,]+)", re.M)
_FROM = re.compile(r"^[ \t]*from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]*(\([^)]*\)|[^\n]*(?:\\\n[^\n]*)*)", re.M)
_LOADER = re.compile(r"(?<!def )\b(import_module|__import__|spec_from_file_location)[ \t]*\(")
_LITERAL = re.compile(r"\s*([rRbBuU]{0,2})(['\"])([\w.]+)\2\s*[,)]")


class Python:
    name = "python"

    def analyze(self, path: str, text: str) -> FileInfo:
        m = mask(text, SYNTAX)
        mlines = m.text.split("\n")
        rlines = text.split("\n")
        all_names = _dunder_all(text)
        symbols: list[Symbol] = []
        stack: list[tuple[int, str, Symbol | None]] = []  # (indent, kind, symbol)
        pending_decorators: list[int] = []
        depth = 0  # open brackets carried over from previous lines (multi-line signatures, literals)
        for idx, ml in enumerate(mlines):
            stripped = ml.strip()
            carried = depth
            if stripped:
                depth = max(0, depth + _bracket_delta(ml))
            if not stripped or carried > 0:
                continue
            indent = len(ml) - len(ml.lstrip())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stripped.startswith("@"):
                pending_decorators.append(idx)
                continue
            dm = _DEF.match(ml)
            if dm:
                kw, name = dm.group(2), dm.group(3)
                parent_kinds = [k for _, k, _ in stack]
                inside_function = any(k == "function" for k in parent_kinds)
                kind = "class" if kw == "class" else ("method" if parent_kinds and parent_kinds[-1] == "class" else "function")
                start = pending_decorators[0] if pending_decorators else idx
                attrs = [norm(rlines[k].strip()[1:]) for k in pending_decorators]
                pending_decorators = []
                sym = None
                if not inside_function:
                    container = ".".join(s.name for _, k, s in stack if s is not None and k == "class")
                    sig = _signature(mlines, rlines, idx)
                    exported = not name.startswith("_") or (name.startswith("__") and name.endswith("__"))
                    if not container and all_names is not None:
                        exported = name in all_names
                    sym = Symbol(kind=kind, name=name, qualname=(container + "." if container else "") + name,
                                 start=start + 1, end=idx + 1, signature=sig, exported=exported,
                                 container=container, attrs=attrs, doc=_doc_after(rlines, idx), line=idx + 1)
                    symbols.append(sym)
                stack.append((indent, "class" if kw == "class" else "function", sym))
                continue
            pending_decorators = []
            if indent == 0:
                cm = _CONST.match(ml)
                if cm:
                    name = cm.group(1)
                    sig = norm(rlines[idx])
                    if len(sig) > 160:
                        sig = sig.split("=")[0].strip() + " = …"
                    exported = (name in all_names) if all_names is not None else not name.startswith("_")
                    symbols.append(Symbol(kind="const", name=name, qualname=name, start=idx + 1, end=idx + 1,
                                          signature=sig, exported=exported, line=idx + 1))
        _fill_ends(symbols, mlines)
        header = _header(text)
        decls = [s.signature for s in symbols if s.exported and s.kind != "const"]
        if all_names is not None:
            decls.append("__all__ = " + ", ".join(sorted(all_names)))
        info = FileInfo(path=path, lang=self.name, header=header, symbols=symbols, idents=idents_of(m.text),
                        line_count=len(rlines))
        info.surface = surface_text(header, decls)
        info.types = [s.name for s in symbols if not s.container and s.kind in ("class", "function") and s.exported]
        info.imports = python_imports(m.text, text)
        return info


def python_imports(masked: str, text: str) -> list[str]:
    """Module specifiers as written: ``import a.b`` → ``a.b``; ``from .x import y`` →
    ``.x`` and ``.x.y`` (``y`` may be a submodule; resolution keeps what exists)."""
    out: list[str] = []

    def add(spec: str) -> None:
        if spec and spec not in out:
            out.append(spec)

    for m in _IMPORT.finditer(masked):
        for part in m.group(1).split(","):
            words = part.split()
            if words:
                add(words[0])
    for m in _FROM.finditer(masked):
        mod = m.group(1)
        if mod == "__future__":
            continue
        add(mod)
        for part in m.group(2).replace("\\\n", " ").strip().strip("()").split(","):
            words = part.split()
            if words and words[0] != "*":
                add(mod + words[0] if mod.endswith(".") else f"{mod}.{words[0]}")
    for m in _LOADER.finditer(masked):
        lit = _LITERAL.match(text, m.end())
        if m.group(1) != "spec_from_file_location" and lit and "f" not in lit.group(1).lower():
            add(lit.group(3))
        else:
            add(DYNAMIC)
    return out


_OPENERS = str.maketrans("", "", "".join(chr(c) for c in range(128) if chr(c) not in "([{)]}"))


def _bracket_delta(masked_line: str) -> int:
    """Net brackets opened on a masked line (strings and comments already blanked)."""
    b = masked_line.translate(_OPENERS) if any(c in masked_line for c in "([{)]}") else ""
    return sum(1 for c in b if c in "([{") - sum(1 for c in b if c in ")]}")


def _signature(mlines: list[str], rlines: list[str], idx: int) -> str:
    """The def/class line(s) up to the colon that ends the header (multi-line params)."""
    depth = 0
    parts = []
    for k in range(idx, min(idx + 40, len(mlines))):
        ml = mlines[k]
        for j, ch in enumerate(ml):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ":" and depth == 0 and not ml[j + 1:j + 2] == "=":
                parts.append(rlines[k][:j])
                return norm(" ".join(parts))
        parts.append(rlines[k])
    return norm(" ".join(parts))


def _fill_ends(symbols: list[Symbol], mlines: list[str]) -> None:
    for s in symbols:
        if s.kind == "const":
            depth = 0
            for k in range(s.line - 1, len(mlines)):
                for ch in mlines[k]:
                    if ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                if depth <= 0:
                    s.end = k + 1
                    break
            continue
        line_idx = s.line - 1
        base = len(mlines[line_idx]) - len(mlines[line_idx].lstrip())
        last = line_idx
        depth = max(0, _bracket_delta(mlines[line_idx]))
        for k in range(line_idx + 1, len(mlines)):
            ml = mlines[k]
            if not ml.strip():
                continue
            carried = depth
            depth = max(0, depth + _bracket_delta(ml))
            if carried == 0 and len(ml) - len(ml.lstrip()) <= base:
                break
            last = k
        s.end = last + 1


def _doc_after(rlines: list[str], idx: int) -> str:
    for k in range(idx + 1, min(idx + 12, len(rlines))):
        st = rlines[k].strip()
        if not st:
            continue
        m = re.match(r'[rRuUbB]?("""|\'\'\'|"|\')(.*)', st)
        if not m:
            return ""
        q = m.group(1)
        body = m.group(2)
        if q in ('"""', "'''"):
            chunk = [body]
            if q not in body:
                for j in range(k + 1, min(k + 30, len(rlines))):
                    chunk.append(rlines[j])
                    if q in rlines[j]:
                        break
            return doc_summary("\n".join(chunk).split(q)[0])
        return doc_summary(body.rstrip(q))
    return ""


def _header(text: str) -> list[str]:
    m = _DOCSTRING.match(text)
    if m:
        return [ln for ln in m.group(2).split("\n")]
    return head_comment(text)


def _dunder_all(text: str) -> set[str] | None:
    m = re.search(r"^__all__\s*(?::[^=]+)?=\s*([\[(][^\])]*[\])])", text, re.M | re.S)
    if not m:
        return None
    try:
        value = ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError):
        return None
    return {x for x in value if isinstance(x, str)}
