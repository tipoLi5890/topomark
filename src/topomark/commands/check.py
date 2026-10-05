"""``topomark check``: is the code map in sync with the code? Exit 1 on any problem."""

from __future__ import annotations

from collections import Counter

from . import Result
from ._common import add, format_problems


def register(sub, common) -> None:
    p = add(sub, common, "check", "verify the code map: coverage, dead paths, caps, fan-in, generated, stamps",
            "Fails (exit 1) when any required file or directory has no row in its area, a path in the docs\n"
            "does not exist, a doc is over its line cap, a fan-in number is stale, the generated reports are\n"
            "stale, or a review stamp is missing/changed/orphaned.")
    p.add_argument("--area", help="only check this area")
    p.add_argument("--no-stamps", action="store_true", help="skip review-stamp checks")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..errors import TopomarkError
    from ..workspace import Workspace

    ws = Workspace(ctx)
    if args.area and args.area not in {a.name for a in ws.areas}:
        raise TopomarkError("NOT_FOUND", f"no area named {args.area!r} (have: {', '.join(a.name for a in ws.areas)})")
    problems = ws.problems(args.area, include_stamps=not args.no_stamps)
    counts = Counter(p.code for p in problems)
    scope = f" (area {args.area})" if args.area else ""
    if problems:
        text = format_problems(problems) + f"\n\ntopomark check{scope}: {len(problems)} problem(s) in {len(ws.areas)} areas"
    else:
        text = f"topomark check{scope}: ok ({len(ws.areas)} areas, {len(ws.units)} units)"
    return Result({"ok": not problems, "areas": len(ws.areas), "units": len(ws.units), "counts": dict(counts),
                   "problems": [p.to_json() for p in problems]}, text, 1 if problems else 0)
