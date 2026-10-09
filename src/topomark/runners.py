"""Runner commands: the selected tests printed as commands a shell can run.

``[[tests.runner]]`` templates from ``topomark.toml`` are filled with the picked files,
classes or methods; every value is quoted for a POSIX shell according to the quoting
state of the template at that point, so a hostile file name cannot run anything.
"""

from __future__ import annotations

import re

from . import repo
from .config import TestRunner
from .testsel import TestPick

def runner_for(path: str, runners: list[TestRunner]) -> TestRunner | None:
    for r in runners:
        if path.startswith(r.match) or repo.matches(path, r.match):
            return r
    return None


def runner_commands(runners: list[TestRunner], picks: list[TestPick]) -> tuple[list[dict], list[TestPick]]:
    """Commands per ``[[tests.runner]]`` for these picks (first matching runner wins), and the
    picks no runner matches."""
    groups: dict[int, list[TestPick]] = {}
    unmatched = []
    for pk in picks:
        r = runner_for(pk.path, runners)
        if r is None:
            unmatched.append(pk)
        else:
            groups.setdefault(runners.index(r), []).append(pk)
    commands = []
    for idx in sorted(groups):
        r = runners[idx]
        cmds, gran = render_runner(r, groups[idx])
        commands.append({"runner": r.match, "names": gran, "files": [pk.path for pk in groups[idx]], "commands": cmds})
    return commands, unmatched


def _items(picks: list[TestPick], gran: str) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for p in picks:
        if gran == "method" and p.methods and not p.whole_file:
            for c, m in p.methods:
                key = (p.path, c, m)
                if key not in seen:
                    seen.add(key)
                    out.append({"file": p.path, "class": c, "method": m, "name": f"{c}.{m}" if c else m})
            continue
        if gran in ("method", "class") and p.classes and not p.whole_file:
            for c in p.classes:
                key = (p.path, c, "")
                if key not in seen:
                    seen.add(key)
                    out.append({"file": p.path, "class": c, "method": "", "name": c})
            continue
        key = (p.path, "", "")
        if key not in seen:
            seen.add(key)
            out.append({"file": p.path, "class": "", "method": "", "name": p.path})
    return out


_PLACEHOLDER = re.compile(r"\{(file|files|class|method|names)\}")
_SEPARATORS = ("::", ".", "#", ":")   # what an empty {class} or {method} takes with it


def _shell_state(text: str, state: str) -> str:
    """The POSIX shell quote state ("", "'" or '"') after ``text``, starting in ``state``."""
    i = 0
    while i < len(text):
        c = text[i]
        if state == "'":
            if c == "'":
                state = ""
        elif c == "\\":
            i += 1
        elif state == '"':
            if c == '"':
                state = ""
        elif c in "'\"":
            state = c
        i += 1
    return state


def _shell_quote(value: str, state: str) -> str:
    """``value`` made literal for the POSIX shell where it lands: ``shlex.quote`` outside quotes
    (a plain path or name comes back unchanged), escapes inside a template's own quotes."""
    import shlex

    if not value:
        return value
    if state == "'":
        return value.replace("'", "'\\''")
    if state == '"':
        return re.sub(r'([\\"$`])', r"\\\1", value)
    return shlex.quote(value)


def fill_template(tmpl: str, values: dict[str, str | list[str]], join: str = " ") -> str:
    """A runner command: placeholders replaced by shell-quoted values (list values quoted one by
    one, then joined with ``join``). An empty ``{class}`` or ``{method}`` drops with the separator
    before it (``::``, ``.``, ``#``, ``:``), or after it when none precedes, so
    ``{file}::{class}::{method}`` gives ``x.py::m`` or ``x.py`` and nothing else in the template
    is touched. Quoting is POSIX shell quoting."""
    parts = _PLACEHOLDER.split(tmpl)
    lits, names = parts[0::2], parts[1::2]
    for k, name in enumerate(names):
        if name not in ("class", "method") or values.get(name):
            continue
        sep = next((x for x in _SEPARATORS if lits[k].endswith(x)), None)
        if sep:
            lits[k] = lits[k][: -len(sep)]
            continue
        sep = next((x for x in _SEPARATORS if lits[k + 1].startswith(x)), None)
        if sep:
            lits[k + 1] = lits[k + 1][len(sep):]
    out: list[str] = []
    state = ""
    for k, lit in enumerate(lits):
        out.append(lit)
        state = _shell_state(lit, state)
        if k < len(names):
            v = values.get(names[k], "")
            out.append(join.join(_shell_quote(x, state) for x in v) if isinstance(v, list) else _shell_quote(v, state))
    return "".join(out).rstrip()


def render_runner(runner: TestRunner, picks: list[TestPick]) -> tuple[list[str], str]:
    """Commands for one runner, and the granularity actually used."""
    gran = runner.names
    items = _items(picks, gran)
    if len(items) > runner.max_names and gran != runner.fallback:
        gran = runner.fallback
        items = _items(picks, gran)
        if len(items) > runner.max_names and gran == "class":
            gran = "file"
            items = _items(picks, gran)
    files = sorted({p.path for p in picks})
    tmpl = runner.command
    per_item = any(k in tmpl for k in ("{file}", "{class}", "{method}")) and "{names}" not in tmpl \
        and "{files}" not in tmpl
    if per_item:
        cmds = []
        for it in items:
            cmd = fill_template(tmpl, {"file": it["file"], "class": it["class"] or "", "method": it["method"] or ""})
            if cmd not in cmds:
                cmds.append(cmd)
        return cmds, gran
    cmd = fill_template(tmpl, {"names": [it["name"] for it in items], "files": files,
                               "file": files[0] if files else "", "class": "", "method": ""}, runner.join)
    return [cmd], gran
