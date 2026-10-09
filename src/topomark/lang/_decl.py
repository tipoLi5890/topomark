"""Helpers the brace adapters outside C#/Java/JS share: signatures, balanced skips,
top-level splits, annotations, enum entries.

Shared rules of the brace adapters outside C#/Java/JS (see ``_decl.py``): signatures
stop at the body (``{``) or an expression body (``=>`` / ``=``); "exported" follows the
language's visibility convention; enum members go into the surface; function bodies are
never classified. An outline for navigation, not a compiler.
"""

from __future__ import annotations

import re

from .base import FileInfo, norm

_IDENT = r"[A-Za-z_]\w*"
_TYPE_SCOPES = {"class", "struct", "interface", "enum", "record", "object", "trait", "protocol", "extension",
                "impl", "mixin"}


def _sig(raw: str, cuts: tuple[str, ...] = ()) -> str:
    """Normalized declaration text cut before the first of ``cuts`` (expression body).

    Block headers already stop before the body brace, so they pass no cuts: a
    ``{`` inside the parameters (Dart named parameters) must survive."""
    s = raw.strip()
    for cut in cuts:
        k = s.find(cut)
        if k > 0:
            s = s[:k]
    return norm(s)  # the walker clips what an outline shows; the surface keeps the whole signature


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


def _is_kind(info: FileInfo, name: str, kind: str) -> bool:
    """True when every top-level symbol called ``name`` is of ``kind`` (an extension/impl, not a declaration)."""
    kinds = {s.kind for s in info.symbols if not s.container and s.name == name}
    return kinds == {kind}


def _short(raw: str, limit: int = 160) -> str:
    s = norm(raw)
    if len(s) <= limit:
        return s
    return (s.split("=")[0].strip() + " = …") if "=" in s else s[:limit - 1] + "…"
