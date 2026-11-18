"""``topomark draft <area>``: the rows an area's file table is missing.

One row per unit that the area file does not mention yet (a file, or a directory
with ``granularity: dir``): ``| `path` | summary | fan-in P/T |``. The summary is
prefilled from the file's header comment or docstring, else the first documented
symbol, else the names it declares; for a directory unit it is the summary of its
most representative file. The impact column is the current fan-in, ``fan-in P/T``,
so ``topomark sync`` keeps it current. ``--write`` appends the rows to the table
under the ``## Files`` heading (``File table``, ``Units`` and ``Files and units``
also count), creating it when missing.

Directory rows carry their file count right after the path, ``(N files)``, where
``check`` verifies it.
"""

from __future__ import annotations

import argparse
import re
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context
    from ..docs import Area
    from ..lang.base import FileInfo
    from ..workspace import Workspace

_HEADINGS = re.compile(r"^##\s+(?:Files|File table|Units|Files and units)\s*$", re.I)
_SKIP_HEADER = re.compile(r"^(copyright|\(c\)|©|spdx-license|licensed under|@license|all rights reserved|-\*-)", re.I)
_REPRESENTATIVE = ("__init__.py", "index.ts", "index.tsx", "index.js", "index.mjs", "mod.rs", "main.py", "main.go",
                   "main.ts", "main.dart", "lib.rs", "README.md")


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "draft", "print (or --write) the rows an area's file table is missing",
            "One row per unit the area file does not mention yet, with a summary from the code (header comment,\n"
            "docstring or first documented symbol) and the current fan-in. Prefilled text is a starting point:\n"
            "read the file, correct the row, then `topomark stamp <path>`.",
            "examples:\n"
            "  topomark draft core            # print the missing rows\n"
            "  topomark draft core --write    # append them under the area's file table")
    p.add_argument("area", help="area name (frontmatter `area`) or its file name")
    p.add_argument("--write", action="store_true", help="append the rows to the area file")
    p.set_defaults(handler=run)


def _cell(text: str, limit: int = 140) -> str:
    # no pipes (they end the cell) and no backticks (a backticked path would count as a row for that path)
    text = re.sub(r"\s+", " ", text.replace("|", "/").replace("`", "'")).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def file_summary(info: FileInfo | None) -> str:
    """One line from a FileInfo: header comment, else first documented symbol, else declared names."""
    from ..lang.base import doc_summary

    if info is None:
        return ""
    header = [ln for ln in info.header if not _SKIP_HEADER.match(re.sub(r"^[\s/#*\-<!>\"']+", "", ln))]
    s = doc_summary("\n".join(header)) if header else ""
    if s:
        return _cell(s)
    for sym in info.symbols:
        if sym.doc and not sym.container:
            return _cell(f"{sym.name}: {sym.doc}")
    names = [s.name for s in info.symbols if s.exported and not s.container][:4]
    return _cell(", ".join(names)) if names else ""


def unit_summary(ws: Workspace, unit: str, files: list[str]) -> str:
    if not unit.endswith("/"):
        return file_summary(ws.infos.get(unit))
    direct = sorted(f for f in files if "/" not in f[len(unit):])
    ordered = sorted(files, key=lambda f: (f.rsplit("/", 1)[-1] not in _REPRESENTATIVE, f not in direct,
                                           f.count("/"), f))
    for f in ordered:
        s = file_summary(ws.infos.get(f))
        if s:
            return _cell(s)
    return ""


def missing_rows(ws: Workspace, area: Area) -> list[dict]:
    from .. import docs as D

    rows = []
    for unit, u in sorted(ws.units.items()):
        if u["area"] != area.name or D.mentions(area.text, unit):
            continue
        p, t = ws.unit_fanin(unit)
        rows.append({"unit": unit, "summary": unit_summary(ws, unit, u["files"]), "impact": f"fan-in {p}/{t}",
                     "fanin": {"prod": p, "test": t}, "files": len(u["files"])})
    return rows


def row_text(r: dict) -> str:
    unit = f"`{r['unit']}`"
    if r["unit"].endswith("/"):
        n = r["files"]
        unit += f" ({n} file{'s' if n != 1 else ''})"
    return f"| {unit} | {r['summary']} | {r['impact']} |"


def insert_rows(text: str, rows: list[str]) -> str:
    """Append rows after the last row of the table under the files heading; create it when missing."""
    lines = text.split("\n")
    head = next((i for i, ln in enumerate(lines) if _HEADINGS.match(ln.strip())), None)
    table_head = ["| file | summary | impact |", "|---|---|---|"]
    if head is None:
        body = text.rstrip("\n")
        return body + "\n\n## Files\n\n" + "\n".join(table_head + rows) + "\n"
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    sep = next((i for i in range(head + 1, end) if re.match(r"^\|\s*:?-{3,}", lines[i].strip())), None)
    if sep is None:
        new = lines[:head + 1] + [""] + table_head + rows + lines[head + 1:]
        return "\n".join(new)
    last = sep
    while last + 1 < end and lines[last + 1].lstrip().startswith("|"):
        last += 1
    return "\n".join(lines[:last + 1] + rows + lines[last + 1:])


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError
    from ..repo import write_text
    from ..workspace import Workspace

    ws = Workspace(ctx)
    area = next((a for a in ws.areas if args.area in (a.name, a.file, a.file.rsplit("/", 1)[-1],
                                                       a.file.rsplit("/", 1)[-1][:-3])), None)
    if area is None:
        raise TopomarkError("NOT_FOUND", f"no area named {args.area!r} (have: {', '.join(a.name for a in ws.areas)})")
    rows = missing_rows(ws, area)
    lines = [row_text(r) for r in rows]
    data = {"area": area.name, "file": area.file, "granularity": area.granularity, "rows": rows, "written": False}
    if not rows:
        return Result(data, f"topomark draft {area.name}: every unit already has a row in {area.file}")
    if args.write:
        write_text(ctx.root, area.file, insert_rows(area.text, lines))
        data["written"] = True
        tail = (f"\n\ntopomark draft: appended {len(rows)} row(s) to {area.file}. Read each file, correct its row, "
                f"then stamp each reviewed row with `topomark stamp <path>`.")
    else:
        tail = (f"\n\n{len(rows)} row(s) missing from {area.file}; `topomark draft {area.name} --write` appends them "
                f"under its file table.")
    return Result(data, "\n".join(lines) + tail)
