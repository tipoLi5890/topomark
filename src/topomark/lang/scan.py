"""Masking scanner: blank out comments and string literals, keep every offset.

``mask(text, syntax)`` returns a string of the same length where every character
inside a comment or a string literal (delimiters and interpolations included) is
replaced by a space, newlines kept. Brace matching, statement splitting and
identifier extraction then run on the masked text and map back to the original
by offset, so a ``{`` in a string or ``//`` in a URL can't derail them.

Interpolated strings are scanned with a mode stack so nested quotes inside the
holes don't end the string early: JS ``\\`${a ? `x` : "y"}\\```, C# ``$"{(a ? "x" : "y")}"``,
Kotlin and Dart ``"${...}"``, Swift ``"\\(...)"``, Python f-strings ``f"{x!r}"``.
The whole literal (holes included) is masked; identifiers inside holes are not
counted as references, an accepted approximation.

The scanner jumps between interesting characters with a compiled regex, so plain
code is skipped at C speed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from bisect import bisect_right
from functools import lru_cache

IDENT_CHARS = re.compile(r"[A-Za-z0-9_]")


@dataclass(frozen=True)
class Syntax:
    line_comments: tuple[str, ...] = ("//",)
    block_comments: tuple[tuple[str, str], ...] = (("/*", "*/"),)
    nested_block_comments: bool = False
    quotes: tuple[str, ...] = ('"', "'")
    triple_quotes: tuple[str, ...] = ()
    backtick: str = ""                      # "template" (JS: ${}) or "raw" (Go) or ""
    # interpolation holes inside double-quoted strings: "" (none), "${" (Kotlin/Dart), "\\(" (Swift)
    dq_interp: str = ""
    csharp_strings: bool = False            # @"..." verbatim, $"..." and $@"..." interpolated
    python_prefixes: bool = False           # r b u f and combos before quotes
    dart_raw: bool = False                  # r'...' / r"..." raw strings
    char_literals_only: bool = False        # single quote is a char literal (C/C++/Java/C#/Rust lifetimes)
    rust_raw: bool = False                  # r"..." r#"..."# br"..." raw strings
    cpp_raw: bool = False                   # R"delim(...)delim" raw strings (also u8R, uR, UR, LR)
    regex_literals: bool = False            # JS /re/flags where an expression may start
    extra_openers: tuple[str, ...] = field(default_factory=tuple)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


class Masked:
    """Masked text plus offset → line mapping."""

    def __init__(self, original: str, masked: str) -> None:
        self.original = original
        self.text = masked
        self._starts = _line_starts(original)

    def line_of(self, offset: int) -> int:
        """1-based line number of ``offset``."""
        return bisect_right(self._starts, offset)

    def line_text(self, line: int) -> str:
        start = self._starts[line - 1]
        end = self._starts[line] - 1 if line < len(self._starts) else len(self.original)
        return self.original[start:end]

    @property
    def line_count(self) -> int:
        return len(self._starts)


def _blank(buf: list[str], start: int, end: int) -> None:
    for k in range(start, end):
        if buf[k] != "\n":
            buf[k] = " "


def mask(text: str, syntax: Syntax) -> Masked:
    buf = list(text)
    n = len(text)
    openers: list[str] = []
    openers += list(syntax.line_comments)
    openers += [b[0] for b in syntax.block_comments]
    openers += list(syntax.triple_quotes)
    openers += list(syntax.quotes)
    if syntax.backtick:
        openers.append("`")
    if syntax.csharp_strings:
        openers += ["$@\"", "@$\"", "@\"", "$\""]
    if syntax.rust_raw:
        openers += ['r"', "r#"]
    if syntax.cpp_raw:
        openers.append('R"')
    if syntax.regex_literals:
        openers.append("/")
    openers += list(syntax.extra_openers)
    openers = sorted(set(openers), key=len, reverse=True)
    code_rx = re.compile("|".join(re.escape(o) for o in openers)) if openers else None
    i = 0
    while code_rx is not None and i < n:
        m = code_rx.search(text, i)
        if not m:
            break
        tok = m.group(0)
        s = m.start()
        # A quote that is the tail of an identifier-prefix (r"..", f'..', @"..") is
        # handled through the prefix logic below; a bare `'` in a char-literal
        # language only opens a literal when it closes within a few characters.
        if tok in syntax.line_comments:
            e = text.find("\n", s)
            e = n if e < 0 else e
            _blank(buf, s, e)
            i = e
            continue
        block = next((b for b in syntax.block_comments if b[0] == tok), None)
        if block:
            e = _block_end(text, s, block, syntax.nested_block_comments)
            _blank(buf, s, e)
            i = e
            continue
        if tok == "/":
            e = _regex_end(text, s)
            if e is None:
                i = s + 1
                continue
            _blank(buf, s, e)
            i = e
            continue
        if tok in ('r"', "r#", 'R"') and tok not in syntax.quotes:
            e, start = _raw_string(text, s, tok, syntax)
            if e is None:
                i = s + (1 if tok != "r#" else 2)  # rescan the quote as an ordinary one
                continue
            _blank(buf, start, e)
            i = e
            continue
        e = _string_end(text, s, tok, syntax)
        if e is None:
            i = s + len(tok)
            continue
        start = s - _prefix_len(text, s, syntax)
        _blank(buf, start, e)
        i = e
    return Masked(text, "".join(buf))


def _block_end(text: str, s: int, block: tuple[str, str], nested: bool) -> int:
    open_, close = block
    n = len(text)
    if not nested:
        e = text.find(close, s + len(open_))
        return n if e < 0 else e + len(close)
    rx = _nest_rx(open_, close)
    depth = 1
    i = s + len(open_)
    while True:
        mm = rx.search(text, i)
        if not mm:
            return n
        i = mm.end()
        if mm.group(0) == open_:
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return i


@lru_cache(maxsize=8)
def _nest_rx(open_: str, close: str) -> re.Pattern[str]:
    return re.compile(re.escape(open_) + "|" + re.escape(close))


def _prefix_len(text: str, s: int, syntax: Syntax) -> int:
    """Length of a string prefix (``rb``, ``f``, ``r``) glued to the quote at ``s``."""
    if not (syntax.python_prefixes or syntax.dart_raw):
        return 0
    k = s
    while k > 0 and text[k - 1] in "rRbBuUfF" and k > s - 3:
        k -= 1
    if k < s and (k == 0 or not IDENT_CHARS.match(text[k - 1])):
        prefix = text[k:s].lower()
        if syntax.python_prefixes and all(c in "rbuf" for c in prefix):
            return s - k
        if syntax.dart_raw and prefix == "r":
            return s - k
    return 0


def _string_end(text: str, s: int, tok: str, syntax: Syntax) -> int | None:
    """End offset (exclusive) of the literal starting at ``s`` with opener ``tok``,
    or None if ``tok`` doesn't open a literal here."""
    n = len(text)
    prefix = text[s - _prefix_len(text, s, syntax):s].lower() if (syntax.python_prefixes or syntax.dart_raw) else ""
    # Python raw strings still end only at an unescaped quote (r"\"" is one string);
    # Dart raw strings have no escapes at all.
    raw = "r" in prefix and not syntax.python_prefixes
    fstring = syntax.python_prefixes and "f" in prefix
    if tok in syntax.triple_quotes:
        if fstring:
            return _scan_interp_string(text, s + 3, tok, "{", "}", escape=not raw, double_brace=True)
        if syntax.dq_interp and not raw:
            return _scan_interp_string(text, s + 3, tok, syntax.dq_interp, _closer(syntax.dq_interp), escape=True)
        e = text.find(tok, s + 3) if raw else _find_unescaped(text, s + 3, tok)
        return n if e < 0 else e + 3
    if tok == "`" and syntax.backtick:
        if syntax.backtick == "raw":
            e = text.find("`", s + 1)
            return n if e < 0 else e + 1
        return _scan_interp_string(text, s + 1, "`", "${", "}", escape=True)
    if syntax.csharp_strings and tok in ('@"', '$@"', '@$"', '$"'):
        verbatim = "@" in tok
        interp = "$" in tok
        if interp:
            return _scan_interp_string(text, s + len(tok), '"', "{", "}", escape=not verbatim,
                                       double_brace=True, verbatim=verbatim)
        i = s + len(tok)
        while i < n:
            if text[i] == '"':
                if i + 1 < n and text[i + 1] == '"':
                    i += 2
                    continue
                return i + 1
            i += 1
        return n
    if tok in syntax.quotes:
        if tok == "'" and syntax.char_literals_only:
            # 'a' '\n' 'ሴ' '\''; anything longer is not a char literal (Rust lifetimes).
            m = re.compile(r"'(?:\\(?:u\{?[0-9A-Fa-f]{1,6}\}?|x[0-9A-Fa-f]{1,2}|.)|[^\\'\n])'").match(text, s)
            return m.end() if m else None
        if fstring:
            return _scan_interp_string(text, s + 1, tok, "{", "}", escape=not raw, double_brace=True, single_line=True)
        if syntax.dq_interp and not raw:
            return _scan_interp_string(text, s + 1, tok, syntax.dq_interp, _closer(syntax.dq_interp),
                                       escape=True, single_line=True)
        i = s + 1
        while i < n:
            c = text[i]
            if c == "\\" and not raw:
                i += 2
                continue
            if c == tok:
                return i + 1
            if c == "\n":
                return i  # unterminated on this line: stop at the newline
            i += 1
        return n
    return None


_REGEX_PREV = set("(,=:[!&|?{};+-*%~^")
_REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "yield",
                   "await", "instanceof"}


def _regex_end(text: str, s: int) -> int | None:
    """End of a JS regex literal starting at ``s``, or None when this ``/`` is division
    (decided by the previous token) or the literal does not close on its line."""
    k = s - 1
    while k >= 0 and text[k] in " \t\r\n":
        k -= 1
    if k >= 0:
        c = text[k]
        if c == ">":
            if not (k > 0 and text[k - 1] == "="):  # `=> /re/` yes, JSX `<b>/x</b>` no
                return None
        elif IDENT_CHARS.match(c) or c == "$":
            j = k
            while j > 0 and (IDENT_CHARS.match(text[j - 1]) or text[j - 1] == "$"):
                j -= 1
            if text[j:k + 1] not in _REGEX_KEYWORDS:
                return None
        elif c not in _REGEX_PREV:
            return None
    n = min(len(text), s + 1000)  # a literal longer than this is not a regex; bounds minified lines
    i = s + 1
    in_class = False
    while i < n:
        c = text[i]
        if c == "\n":
            return None
        if c == "\\":
            i += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            i += 1
            while i < n and IDENT_CHARS.match(text[i]):
                i += 1
            return i
        i += 1
    return None


_RUST_RAW = re.compile(r'r(#*)"')
_CPP_RAW = re.compile(r'R"([^ ()\\\t\n]{0,16})\(')


def _raw_string(text: str, s: int, tok: str, syntax: Syntax) -> tuple[int | None, int]:
    """Rust ``r#"..."#`` / C++ ``R"x(...)x"``: (end, start) or (None, s) when the
    match at ``s`` is an identifier tail (``bar"``) or a raw identifier (``r#type``)."""
    k = s
    while k > 0 and IDENT_CHARS.match(text[k - 1]):
        k -= 1
    prefix = text[k:s]
    allowed = ("", "b") if tok != 'R"' else ("", "u8", "u", "U", "L")
    if prefix not in allowed:
        return None, s
    n = len(text)
    if tok == 'R"':
        m = _CPP_RAW.match(text, s)
        if not m:
            return None, s
        e = text.find(")" + m.group(1) + '"', m.end())
        return (n if e < 0 else e + len(m.group(1)) + 2), k
    m = _RUST_RAW.match(text, s)
    if not m:
        return None, s
    close = '"' + m.group(1)
    e = text.find(close, m.end())
    return (n if e < 0 else e + len(close)), k


def _closer(opener: str) -> str:
    return ")" if opener.endswith("(") else "}"


def _find_unescaped(text: str, start: int, needle: str) -> int:
    i = start
    while True:
        j = text.find(needle, i)
        if j < 0:
            return -1
        k = j - 1
        backslashes = 0
        while k >= start and text[k] == "\\":
            backslashes += 1
            k -= 1
        if backslashes % 2 == 0:
            return j
        i = j + 1


@lru_cache(maxsize=64)
def _interest(chars: str) -> re.Pattern[str]:
    return re.compile("[" + re.escape("".join(sorted(set(chars)))) + "]")


def _scan_interp_string(text: str, i: int, quote: str, hole_open: str, hole_close: str, *, escape: bool,
                        double_brace: bool = False, verbatim: bool = False, single_line: bool = False) -> int:
    """Scan a string body with interpolation holes; return the end offset (exclusive).

    Jumps between the characters that can matter (quote, hole opener, escape,
    newline) with a cached regex, so long literals cost C speed."""
    n = len(text)
    rx = _interest(quote[0] + hole_open[0] + ("\\" if escape else "") + ("\n" if single_line else ""))
    while i < n:
        mm = rx.search(text, i)
        if not mm:
            return n
        i = mm.start()
        if escape and text[i] == "\\" and not text.startswith(hole_open, i):
            i += 2
            continue
        if verbatim and text.startswith('""', i):
            i += 2
            continue
        if text.startswith(quote, i):
            return i + len(quote)
        if double_brace and text.startswith(hole_open * 2, i) and len(hole_open) == 1:
            i += 2
            continue
        if text.startswith(hole_open, i):
            i = _skip_hole(text, i + len(hole_open), hole_open, hole_close)
            continue
        if single_line and text[i] == "\n":
            return i
        i += 1
    return n


_HOLE_INTEREST = re.compile(r"[\\\"'`()\[\]{}]")


def _skip_hole(text: str, i: int, hole_open: str, hole_close: str) -> int:
    """Skip an interpolation hole's code, honouring nested strings and brackets."""
    n = len(text)
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    while i < n:
        mm = _HOLE_INTEREST.search(text, i)
        if not mm:
            return n
        i = mm.start()
        c = text[i]
        if c == "\\":  # Python 3.12 f-string holes may hold escapes
            i += 2
            continue
        if c in "\"'`":
            q = c
            if c == "`":
                i = _scan_interp_string(text, i + 1, "`", "${", "}", escape=True)
            elif text.startswith(q * 3, i):
                e = _find_unescaped(text, i + 3, q * 3)
                i = n if e < 0 else e + 3
            elif hole_open == "{" and not (i > 0 and text[i - 1] in "$fF"):
                # C# / Python: a plain string inside a hole has no holes of its own
                e = i + 1
                while e < n and text[e] not in (q, "\n"):
                    e += 2 if text[e] == "\\" else 1
                i = e + 1 if e < n and text[e] == q else e
            else:
                i = _scan_interp_string(text, i + 1, q, hole_open, hole_close, escape=True, single_line=True)
            continue
        if c in pairs:
            depth += 1
        elif c in ")]}":
            if depth == 0 and c == hole_close:
                return i + 1
            depth = max(0, depth - 1)
        i += 1
    return n
