"""``topomark stale``: units needing review (blocking) and units whose body changed (advisory)."""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add, format_problems

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "stale", "list rows to review: interface changed (exit 1) and body-only changes (advisory)")
    p.add_argument("--area", help="only this area")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..workspace import Workspace

    ws = Workspace(ctx)
    blocking = ws.stamp_problems(args.area)
    flagged = {p.subject for p in blocking}
    soft: dict[str, list[str]] = defaultdict(list)
    candidates = [u for u, d in ws.units.items() if (not args.area or d["area"] == args.area)
                  and u in ws.stamps.units and u not in flagged]
    files = sorted({f for u in candidates for f in ws.units[u]["files"]})
    blobs = ws.current_blobs(files)  # compared, not stored: `stale` writes nothing
    for u in sorted(candidates):
        old = ws.stamps.units[u].get("blobs", {})
        if any(old.get(f) != blobs.get(f) for f in ws.units[u]["files"]):
            soft[ws.units[u]["area"]].append(u)
    lines = []
    if blocking:
        lines.append(format_problems(blocking))
    for area in sorted(soft):
        lines.append(f"{area}: {len(soft[area])} unit(s) changed in body only (rows likely still accurate; "
                     f"look, then stamp)")
        lines += [f"    {u}" for u in soft[area][:20]]
        if len(soft[area]) > 20:
            lines.append(f"    ... {len(soft[area]) - 20} more")
    if not lines:
        lines = ["topomark stale: every unit matches its last review"]
    return Result({"needs_review": [p.to_json() for p in blocking], "body_changed": dict(soft)},
                  "\n".join(lines), 1 if blocking else 0)
