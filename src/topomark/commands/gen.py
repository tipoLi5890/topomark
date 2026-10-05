"""``topomark gen``: (re)write the generated reports under ``<docs_dir>/_generated/``."""

from __future__ import annotations

from ..repo import write_text
from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "gen", "regenerate <docs_dir>/_generated/ (fan-in table, module graph)",
            "Rebuild the generated reports from the code. They are compared by `check`; never edit them by hand.")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..workspace import Workspace

    ws = Workspace(ctx)
    written = []
    for path, text in ws.generated().items():
        full = ctx.root / path
        old = full.read_text(encoding="utf-8") if full.is_file() else None
        if old != text:
            write_text(ctx.root, path, text)
            written.append(path)
    lines = [f"wrote {p}" for p in written] or ["generated reports already up to date"]
    return Result({"written": written, "files": sorted(ws.generated())}, "\n".join(lines))
