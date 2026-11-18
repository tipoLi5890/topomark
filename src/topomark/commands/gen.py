"""``topomark gen``: (re)write the generated reports under ``<docs_dir>/_generated/``."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from ..repo import read_text, write_text
from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "gen", "regenerate <docs_dir>/_generated/ (fan-in table, module graph)",
            "Rebuild the generated reports from the code. They are compared by `check`; never edit them by hand.")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..workspace import Workspace

    ws = Workspace(ctx)
    written = []
    for path, text in ws.generated().items():
        old = read_text(ctx.root, path) if (ctx.root / path).is_file() else None
        if old != text:
            write_text(ctx.root, path, text)
            written.append(path)
    lines = [f"wrote {p}" for p in written] or ["generated reports already up to date"]
    return Result({"written": written, "files": sorted(ws.generated())}, "\n".join(lines))
