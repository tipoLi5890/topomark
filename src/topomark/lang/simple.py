"""Small adapters: shell, SQL, data files (JSON/JSONC/YAML/TOML), Markdown, and the
plain-text fallback for anything without a dedicated adapter."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any

from .base import FileInfo, Symbol, count_lines, head_comment, idents_of, norm, norm_lines, surface_text
from .scan import Masked, Syntax, mask

# ---------------------------------------------------------------- shell
_SH = Syntax(line_comments=("#",), block_comments=(), quotes=('"', "'"))
_SH_FUNC = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w:.-]*)\s*\(\s*\)\s*\{?|^\s*function\s+([A-Za-z_][\w:.-]*)\s*\{?")
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")


def mask_shell(text: str) -> Masked:
    """Blank shell comments, quoted strings and heredoc bodies (offsets kept).

    ``#`` starts a comment only at the start of a word, so ``${#arr[@]}`` and
    ``$#`` stay code; ``"..."`` honours backslash escapes, ``'...'`` does not."""
    buf = list(text)
    n = len(text)
    i = 0
    heredocs: list[tuple[str, bool]] = []
    while i < n:
        c = text[i]
        if c == "\n" and heredocs:
            i = _skip_heredocs(text, i + 1, heredocs, buf)
            heredocs = []
            continue
        if c == "\\":
            i += 2
            continue
        if c == "#" and (i == 0 or text[i - 1] in " \t\n;|&()"):
            e = text.find("\n", i)
            e = n if e < 0 else e
            _blank_range(buf, i, e)
            i = e
            continue
        if c in "'\"":
            e = i + 1
            while e < n and text[e] != c:
                e += 2 if c == '"' and text[e] == "\\" else 1
            _blank_range(buf, i, min(n, e + 1))
            i = e + 1
            continue
        if c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
            hm = _HEREDOC.match(text, i)
            if hm:
                heredocs.append((hm.group(3), hm.group(1) == "-"))
                i = hm.end()
                continue
        i += 1
    return Masked(text, "".join(buf))


def _skip_heredocs(text: str, i: int, pending: list[tuple[str, bool]], buf: list[str]) -> int:
    """Blank the bodies of the heredocs opened on the previous line; return the offset after them."""
    n = len(text)
    for word, dash in pending:
        start = i
        while i < n:
            e = text.find("\n", i)
            e = n if e < 0 else e
            line = text[i:e]
            if (line.lstrip("\t") if dash else line) == word:
                _blank_range(buf, start, i)
                i = e + 1
                break
            i = e + 1
        else:
            _blank_range(buf, start, n)
    return i


def _blank_range(buf: list[str], start: int, end: int) -> None:
    for k in range(start, end):
        if buf[k] != "\n":
            buf[k] = " "


class Shell:
    name = "shell"
    syntax = _SH

    def premask(self, text: str) -> str:
        """Used by navigation: the shell-aware mask, since ``Syntax`` can't express it."""
        return mask_shell(text).text

    def analyze(self, path: str, text: str) -> FileInfo:
        m = mask_shell(text)
        lines = m.text.split("\n")
        rlines = text.split("\n")
        symbols = []
        for idx, ml in enumerate(lines):
            fm = _SH_FUNC.match(ml)
            if not fm:
                continue
            name = fm.group(1) or fm.group(2)
            end = _match_brace(m, idx)
            symbols.append(Symbol(kind="function", name=name, qualname=name, start=idx + 1, end=end,
                                  signature=norm(rlines[idx].split("{")[0]), line=idx + 1))
        header = head_comment(text)
        info = FileInfo(path=path, lang=self.name, header=header, symbols=symbols, idents=idents_of(m.text),
                        line_count=count_lines(text))
        info.surface = surface_text(header, [s.signature for s in symbols])
        info.types = [s.name for s in symbols]
        return info


def _match_brace(m: Masked, line_idx: int) -> int:
    """Line of the ``}`` closing the first ``{`` at or after ``line_idx`` (a function body)."""
    masked = m.text
    pos = masked.find("{", m._starts[line_idx])
    if pos < 0:
        return line_idx + 1
    depth = 0
    for mm in _BRACES.finditer(masked, pos):
        if mm.group(0) == "{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.line_of(mm.start())
    return m.line_count


_BRACES = re.compile(r"[{}]")


# ---------------------------------------------------------------- SQL
_SQL = Syntax(line_comments=("--",), block_comments=(("/*", "*/"),), quotes=("'", '"'))
_SQL_CREATE = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?(?:unique\s+)?(?:temp(?:orary)?\s+)?(table|index|view|trigger|"
                         r"function|procedure|type|sequence|schema)\s+(?:if\s+not\s+exists\s+)?([\w.\"`\[\]]+)", re.I)


class Sql:
    name = "sql"

    def analyze(self, path: str, text: str) -> FileInfo:
        m = mask(text, _SQL)
        symbols = []
        for cm in _SQL_CREATE.finditer(m.text):
            end = m.text.find(";", cm.end())
            end = len(m.text) - 1 if end < 0 else end
            name = cm.group(2).strip('"`[]')
            first = norm(text[cm.start():text.find("\n", cm.start()) if "\n" in text[cm.start():] else len(text)])
            symbols.append(Symbol(kind=cm.group(1).lower(), name=name, qualname=name, start=m.line_of(cm.start()),
                                  end=m.line_of(end), signature=first, line=m.line_of(cm.start())))
        header = head_comment(text)
        info = FileInfo(path=path, lang=self.name, header=header, symbols=symbols, idents=idents_of(m.text),
                        line_count=count_lines(text))
        info.surface = surface_text(header, [_sql_statement(m, s.start) for s in symbols])
        info.types = [s.name for s in symbols if s.kind in ("table", "view", "function", "procedure", "type")]
        return info


def _sql_statement(m: Masked, line: int) -> str:
    """The statement starting on ``line`` up to its ``;`` (found in masked text, so a
    ``;`` inside a string literal doesn't cut it), normalized and capped."""
    start = m._starts[line - 1]
    end = m.text.find(";", start)
    return norm(m.original[start:end if end >= 0 else len(m.original)])[:400]


# ---------------------------------------------------------------- data files
def json_skeleton(obj: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for k in sorted(obj):
            keys.append(prefix + "." + k)
            keys += json_skeleton(obj[k], prefix + "." + k)
    elif isinstance(obj, list):
        seen: set[str] = set()
        for v in obj:
            for k in json_skeleton(v, prefix + "[]"):
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
    return keys


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments (outside strings) and trailing commas."""
    out = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


_TOP_KEY = re.compile(r'^\s{0,4}"([^"]+)"\s*:', re.M)


class Data:
    """JSON / JSONC / asmdef / YAML / TOML: key skeleton as surface, top-level keys as symbols."""

    name = "data"

    def analyze(self, path: str, text: str) -> FileInfo:
        low = path.lower()
        keys: list[str] = []
        symbols: list[Symbol] = []
        lang = "json"
        try:
            if low.endswith((".json", ".asmdef", ".asmref", ".jsonc", ".json5")) or low.endswith("tsconfig.json"):
                raw = strip_jsonc(text) if not low.endswith((".asmdef", ".asmref")) else text
                obj = json.loads(raw)
                keys = json_skeleton(obj)
                symbols = self._json_symbols(text, obj)
            elif low.endswith(".toml"):
                lang = "toml"
                obj = tomllib.loads(text)
                keys = json_skeleton(obj)
                symbols = self._toml_symbols(text)
            elif low.endswith((".yaml", ".yml")):
                lang = "yaml"
                keys, symbols = self._yaml(text)
        except (ValueError, tomllib.TOMLDecodeError):
            return Plain().analyze(path, text)
        info = FileInfo(path=path, lang=lang, symbols=symbols, idents=set(), line_count=count_lines(text))
        info.surface = "\n".join(keys)
        if low.endswith((".asmdef", ".asmref")):
            # assembly definitions are contracts: a changed reference or define is an interface change
            info.surface = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1)
        return info

    def _json_symbols(self, text: str, obj: Any) -> list[Symbol]:
        if not isinstance(obj, dict):
            return []
        out = []
        lines = text.split("\n")
        for k in obj:
            for idx, ln in enumerate(lines):
                if re.match(r'^\s{0,4}"' + re.escape(k) + r'"\s*:', ln):
                    out.append(Symbol(kind="key", name=k, qualname=k, start=idx + 1, end=idx + 1,
                                      signature=norm(ln)[:120], line=idx + 1))
                    break
        _ends_by_next(out, len(lines))
        return out

    def _toml_symbols(self, text: str) -> list[Symbol]:
        out = []
        lines = text.split("\n")
        for idx, ln in enumerate(lines):
            mm = re.match(r"^\s*\[\[?([^\]]+)\]\]?", ln)
            if mm:
                out.append(Symbol(kind="table", name=mm.group(1).strip(), qualname=mm.group(1).strip(),
                                  start=idx + 1, end=idx + 1, signature=norm(ln), line=idx + 1))
        _ends_by_next(out, len(lines))
        return out

    def _yaml(self, text: str) -> tuple[list[str], list[Symbol]]:
        """Key paths by indentation; list items add ``[]`` (``.server.hosts[].url``)."""
        keys: list[str] = []
        seen: set[str] = set()
        symbols: list[Symbol] = []
        path_stack: list[tuple[int, str]] = []  # (column, segment); "[]" marks a list item
        lines = text.split("\n")
        for idx, ln in enumerate(lines):
            if not ln.strip() or ln.lstrip().startswith(("#", "---", "...")):
                continue
            mm = _YAML_KEY.match(ln)
            if not mm:
                dash = re.match(r"^(\s*)-(?:\s|$)", ln)
                if dash:  # a scalar list item still closes deeper keys
                    _yaml_pop(path_stack, len(dash.group(1)))
                continue
            key_col = mm.start(3)
            if mm.group(2):  # `- key: value` opens a list item at the dash column
                dash_col = len(mm.group(1))
                _yaml_pop(path_stack, dash_col)
                path_stack.append((dash_col, "[]"))
            _yaml_pop(path_stack, key_col)
            key = mm.group(3).strip("\"'")
            full = _yaml_path([p for _, p in path_stack] + [key])
            if full not in seen:
                seen.add(full)
                keys.append(full)
            if key_col == 0:
                symbols.append(Symbol(kind="key", name=key, qualname=key, start=idx + 1, end=idx + 1,
                                      signature=norm(ln)[:120], line=idx + 1))
            path_stack.append((key_col, key))
        _ends_by_next(symbols, len(lines))
        return keys, symbols


_YAML_KEY = re.compile(r"^(\s*)(-\s+)?([A-Za-z_$][\w$.-]*|\"[^\"]+\"|'[^']+')\s*:(?:\s|$)")


def _yaml_pop(stack: list[tuple[int, str]], col: int) -> None:
    while stack and stack[-1][0] >= col:
        stack.pop()


def _yaml_path(parts: list[str]) -> str:
    out = ""
    for p in parts:
        out += p if p == "[]" else "." + p
    return out


def _ends_by_next(symbols: list[Symbol], total: int) -> None:
    for k, s in enumerate(symbols):
        s.end = (symbols[k + 1].start - 1) if k + 1 < len(symbols) else total
        s.end = max(s.end, s.start)


# ---------------------------------------------------------------- Markdown
class Markdown:
    """Headings (ATX ``#`` and setext ``===``/``---``) outside fenced code and YAML front matter."""

    name = "markdown"

    def analyze(self, path: str, text: str) -> FileInfo:
        lines = text.split("\n")
        symbols: list[Symbol] = []
        levels: list[int] = []
        fence = ""
        start = _front_matter_end(lines)
        for idx in range(start, len(lines)):
            ln = lines[idx]
            st = ln.lstrip()
            if fence:
                if st.startswith(fence):
                    fence = ""
                continue
            if st.startswith(("```", "~~~")):
                fence = st[:3]
                continue
            mm = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", ln) or re.match(r"^ {0,3}(#{1,6})\s*$", ln)
            level, title, at = 0, "", idx
            if mm:
                level, title = len(mm.group(1)), (mm.group(2) if mm.lastindex and mm.lastindex > 1 else "")
            elif idx > start and re.match(r"^ {0,3}(=+|-+)\s*$", ln) and _setext_text(lines[idx - 1]):
                level, title, at = (1 if "=" in ln else 2), lines[idx - 1].strip(), idx - 1
                if symbols and symbols[-1].line == at + 1:
                    continue
            if level:
                symbols.append(Symbol(kind=f"h{level}", name=title, qualname=title, start=at + 1, end=at + 1,
                                      signature=norm(lines[at]) if mm else "#" * level + " " + title, line=at + 1))
                levels.append(level)
        for k, s in enumerate(symbols):
            end = len(lines)
            for j in range(k + 1, len(symbols)):
                if levels[j] <= levels[k]:
                    end = symbols[j].start - 1
                    break
            s.end = max(s.start, end)
        info = FileInfo(path=path, lang=self.name, symbols=symbols, line_count=count_lines(text))
        info.surface = "\n".join(s.signature for s in symbols)
        return info


def _front_matter_end(lines: list[str]) -> int:
    """Index of the first line after a leading ``---`` YAML front matter block (0 if none)."""
    if not lines or lines[0].strip() != "---":
        return 0
    for k in range(1, min(len(lines), 200)):
        if lines[k].strip() in ("---", "..."):
            return k + 1
    return 0


def _setext_text(prev: str) -> bool:
    """A setext heading's text line: non-blank paragraph text, not a list item, quote, table or rule."""
    st = prev.strip()
    return bool(st) and not prev.startswith(("    ", "\t")) and not re.match(r"^(?:[-*+>|#]|\d+[.)]\s|=+$|-+$)", st)


# ---------------------------------------------------------------- fallback
class Plain:
    name = "text"

    def analyze(self, path: str, text: str) -> FileInfo:
        info = FileInfo(path=path, lang=self.name, header=head_comment(text), line_count=count_lines(text),
                        idents=idents_of(text))
        info.surface = "\n".join(norm_lines(text.split("\n")))
        return info
