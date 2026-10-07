"""Syntax checks after an edit, for ``topomark syntax`` and editor or agent hooks.

* **Python** (``.py``, ``.pyi``): ``ast.parse`` of the running interpreter, exact for that version.
  Code for a newer Python (PEP 695 generics under 3.11, ``except A, B:`` before 3.14) fails it,
  so a Python finding names the interpreter, and says when the nearest ``pyproject.toml``'s
  ``[project] requires-python`` minimum is newer than it (``newer_python``); the post-edit hook
  stays quiet about Python findings then. Other ways of pinning a version are not read.
* **JSON** (``.json``, ``.asmdef``, ``.asmref``): ``json.loads``; a file that only parses with
  ``//`` and ``/* */`` comments and trailing commas removed (``tsconfig.json`` and friends) is
  accepted as JSONC. ``.jsonc`` is checked as JSONC; ``.json5`` is not checked.
* **TOML** (``.toml``): ``tomllib``.
* **Brace languages** (JS/TS, C#, Java, Kotlin, Swift, Dart, Go, Rust, C/C++/Objective-C):
  ``()``, ``[]`` and ``{}`` balance on the text with comments and strings masked by the file's
  adapter. The masker is lexical, so JSX text or an unusual regex literal (Swift's bare
  ``/a(b/`` is not masked; its raw strings ``#"…"#`` and ``#/…/#`` literals are) can fool it; a
  file is therefore reported only when its HEAD version was balanced and the current one is not.
  A file without a HEAD version is not bracket-checked.

For Python, JSON and TOML a finding says whether the HEAD version does not parse either
(``preexisting``), so a hook can stay quiet about errors the edit did not cause.

``check_file(ctx, path)`` needs only a ``Context`` (root and ``read``): no index, no reference
graph, and git only when a check fails. Files are read through ``Context.read``, so
secret-looking paths are refused.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Callable

PY_EXT = (".py", ".pyi")
JSON_EXT = (".json", ".asmdef", ".asmref")
JSONC_EXT = (".jsonc",)
TOML_EXT = (".toml",)
BRACE_LANGS = frozenset({"js", "csharp", "java", "kotlin", "swift", "dart", "go", "rust", "c"})
_PAIRS = {")": "(", "]": "[", "}": "{"}
_BRACKETS = re.compile(r"[()\[\]{}]")
_TOML_AT = re.compile(r"\(at line (\d+), column (\d+)\)")
_PY_MIN = re.compile(r"(?:>=|~=|==|>)\s*(\d+)\.(\d+)")
RUNNING = sys.version_info[:2]


@dataclass
class Finding:
    path: str
    line: int
    col: int
    lang: str
    message: str
    preexisting: bool = False   # the HEAD version does not parse either (Python, JSON, TOML)

    def to_json(self) -> dict:
        return {"path": self.path, "line": self.line, "col": self.col, "lang": self.lang, "message": self.message,
                "preexisting": self.preexisting}

    def text(self) -> str:
        where = f"{self.path}:{self.line}" + (f":{self.col}" if self.col else "")
        return f"{where}: {self.lang}: {self.message}" + ("  (also at HEAD)" if self.preexisting else "")


@dataclass
class Checked:
    path: str
    lang: str = ""                       # python | json | jsonc | toml | brackets:<adapter> | ""
    findings: list[Finding] = field(default_factory=list)
    skipped: str = ""                    # why the file was not checked


# ---------------------------------------------------------------- strict parsers
def _python(path: str, text: str) -> tuple[int, int, str] | None:
    try:
        ast.parse(text, filename=path)
    except SyntaxError as e:
        return e.lineno or 1, e.offset or 0, e.msg
    except ValueError as e:  # null bytes
        return 1, 0, str(e)
    return None


def strip_jsonc(text: str) -> str:
    """JSON with ``//`` and ``/* */`` comments and trailing commas removed; line numbers kept."""
    out: list[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_str = c != '"'
            i += 1
            continue
        if c == '"':
            in_str = True
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            end = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, end))
            i = end
            continue
        out.append(c)
        i += 1
    s = "".join(out)
    res: list[str] = []
    i, n, in_str = 0, len(s), False
    while i < n:
        c = s[i]
        if in_str:
            res.append(c)
            if c == "\\" and i + 1 < n:
                res.append(s[i + 1])
                i += 2
                continue
            in_str = c != '"'
        elif c == '"':
            in_str = True
            res.append(c)
        elif c == ",":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if not (j < n and s[j] in "}]"):
                res.append(c)
        else:
            res.append(c)
        i += 1
    return "".join(res)


def _json(text: str, jsonc: bool) -> tuple[int, int, str] | None:
    try:
        json.loads(strip_jsonc(text) if jsonc else text)
        return None
    except ValueError as e:
        err = e
    if not jsonc:
        try:
            json.loads(strip_jsonc(text))
            return None  # JSON with comments (tsconfig.json, .vscode/*.json): fine
        except ValueError:
            pass
    if isinstance(err, json.JSONDecodeError):
        return err.lineno, err.colno, err.msg
    return 1, 0, str(err)


def _toml(text: str) -> tuple[int, int, str] | None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        msg = str(e)
        m = _TOML_AT.search(msg)
        return (int(m[1]), int(m[2]), _TOML_AT.sub("", msg).strip()) if m else (1, 0, msg)
    return None


# ---------------------------------------------------------------- brackets
def imbalance(masked: str) -> tuple[int, str] | None:
    """(offset, message) of the first bracket problem in masked text, or None when balanced."""
    stack: list[tuple[str, int]] = []
    for m in _BRACKETS.finditer(masked):
        ch = m.group(0)
        if ch in "([{":
            stack.append((ch, m.start()))
            continue
        if not stack:
            return m.start(), f"unmatched '{ch}'"
        top, pos = stack.pop()
        if top != _PAIRS[ch]:
            return m.start(), f"'{ch}' closes '{top}' opened at line {masked.count(chr(10), 0, pos) + 1}"
    if stack:
        ch, pos = stack[-1]
        more = f" ({len(stack)} unclosed)" if len(stack) > 1 else ""
        return pos, f"'{ch}' is never closed{more}"
    return None


def _head_text(ctx, path: str) -> str | None:
    from .repo import git

    root = ctx.root
    if not git(root, "ls-tree", "--name-only", "HEAD", "--", path, check=False).strip():
        return None  # no commit yet, or the file is new
    return git(root, "show", f"HEAD:{path}", check=False).replace("\r\n", "\n")


def newer_python(ctx, path: str) -> str | None:
    """The ``requires-python`` of the ``pyproject.toml`` nearest to ``path`` (its folder, then up
    to the repo root) when its minimum is newer than the running interpreter, else None."""
    from .errors import TopomarkError

    parts = path.split("/")[:-1]
    for k in range(len(parts), -1, -1):
        cand = "/".join([*parts[:k], "pyproject.toml"])
        if not (ctx.root / cand).is_file():
            continue
        try:
            spec = tomllib.loads(ctx.read(cand)).get("project", {}).get("requires-python")
        except (OSError, TopomarkError, tomllib.TOMLDecodeError, AttributeError):
            return None
        if not isinstance(spec, str):
            return None
        lows = [(int(m[1]), int(m[2])) for m in _PY_MIN.finditer(spec)]
        return spec.strip() if lows and max(lows) > RUNNING else None
    return None


# ---------------------------------------------------------------- entry points
def check_file(ctx, path: str) -> Checked:
    """Check one repo file (repo-relative POSIX path) as it is on disk now."""
    from .errors import TopomarkError
    from .lang import registry
    from .navigate import mask_file

    low = path.lower()
    adapter = getattr(registry.adapter_for(path), "name", "")
    strict: Callable[[str, str], tuple[int, int, str] | None] | None
    if low.endswith(PY_EXT):
        lang, strict = "python", _python
    elif low.endswith(JSON_EXT):
        lang, strict = "json", (lambda p, t: _json(t, False))
    elif low.endswith(JSONC_EXT):
        lang, strict = "jsonc", (lambda p, t: _json(t, True))
    elif low.endswith(TOML_EXT):
        lang, strict = "toml", (lambda p, t: _toml(t))
    elif adapter in BRACE_LANGS:
        lang, strict = f"brackets:{adapter}", None
    else:
        return Checked(path, skipped=f"no syntax check for {adapter or 'this file type'}")
    try:
        text = ctx.read(path)
    except FileNotFoundError:
        return Checked(path, lang, skipped="deleted")
    except (OSError, TopomarkError) as e:
        return Checked(path, lang, skipped=f"unreadable: {getattr(e, 'message', None) or e}")
    res = Checked(path, lang)
    if strict is not None:
        hit = strict(path, text)
        if hit:
            head = _head_text(ctx, path)
            same = head is not None and strict(path, head) is not None
            line, col, msg = hit
            if lang == "python":
                need = newer_python(ctx, path)
                msg += f" (Python {RUNNING[0]}.{RUNNING[1]}" + (f"; the project requires {need})" if need else ")")
            res.findings.append(Finding(path, line, col, lang.split(":")[0], msg, preexisting=same))
        return res
    bad = imbalance(mask_file(path, text).text)
    if bad is None:
        return res
    head = _head_text(ctx, path)
    if head is None:
        res.skipped = "new file: brackets are only compared with HEAD"
        return res
    if imbalance(mask_file(path, head).text) is not None:
        res.skipped = "brackets were unbalanced at HEAD already (masking can't be trusted here)"
        return res
    offset, msg = bad
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    res.findings.append(Finding(path, line, col, adapter, msg + " (balanced at HEAD)"))
    return res


def check_paths(ctx, paths: list[str]) -> list[Checked]:
    return [check_file(ctx, p) for p in paths]
