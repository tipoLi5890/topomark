"""``topomark sync``: rewrite stale ``fan-in P/T`` numbers in area files (numbers only)."""

from __future__ import annotations

from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "sync", "update the fan-in numbers written in area files",
            "Rows whose first cell is a file or directory unit and whose text contains `fan-in P/T` get\n"
            "the current numbers. Nothing else in the file changes.")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..repo import write_text
    from ..workspace import FAN_RX, Workspace

    ws = Workspace(ctx)
    changed = []
    for a in ws.areas:
        lines = a.text.split("\n")
        hits = ws.fan_mismatches(a.text)
        for i, subject, old, new in hits:
            m = FAN_RX.search(lines[i])
            lines[i] = lines[i][:m.start()] + f"fan-in {new[0]}/{new[1]}" + lines[i][m.end():]
            changed.append({"file": a.file, "subject": subject, "old": list(old), "new": list(new)})
        if hits:
            write_text(ctx.root, a.file, "\n".join(lines))
    return Result({"changed": changed}, f"topomark sync: updated {len(changed)} fan-in number(s)")
