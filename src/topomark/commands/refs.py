"""``topomark refs <Name>``: where is a name used (comments and strings excluded)?"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context


TEXT_LIMIT = 20
JSON_LIMIT = 200


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "refs", "reference sites of a name (word match in code, comments/strings excluded)",
            "Approximate: an identifier match, not a resolved binding. The declaration line itself is\n"
            "excluded. `Type.Member` lists `Member` lines in files that mention `Type` or declare it.\n"
            "Grouped production vs tests, then by area (or top-level directory without a code map).\n"
            f"Text shows every group's counts and the first {TEXT_LIMIT} sites; --limit N shows N (the JSON\n"
            f"always lists up to --limit, default {JSON_LIMIT}).",
            "examples:\n  topomark refs Router\n  topomark refs Budget.ReactionFloor --no-tests\n"
            "  topomark refs Router --area core --limit 20")
    p.add_argument("name")
    p.add_argument("--area", help="only files in this area (or top-level directory)")
    p.add_argument("--no-tests", action="store_true", help="skip test files")
    p.add_argument("--limit", type=int, metavar="N",
                   help=f"max sites listed (default: {TEXT_LIMIT} in text, {JSON_LIMIT} in --json)")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..navigate import Nav

    nav = Nav(ctx)
    nav.check_area(args.area)
    sites = nav.ref_sites(args.name, area=args.area, include_tests=not args.no_tests)
    groups: dict[tuple[bool, str], list] = defaultdict(list)
    for s in sites:
        groups[(s.test, s.group)].append(s)
    files = {s.path for s in sites}
    summary = {"sites": len(sites), "files": len(files), "prod_files": len({s.path for s in sites if not s.test}),
               "test_files": len({s.path for s in sites if s.test})}
    by_group = [{"test": t, "group": g, "sites": len(v), "files": len({s.path for s in v})}
                for (t, g), v in sorted(groups.items())]
    listed = sites[:max(0, JSON_LIMIT if args.limit is None else args.limit)]
    data = {"name": args.name, **summary, "groups": by_group, "truncated": len(sites) > len(listed),
            "results": [s.to_json() for s in listed]}
    if not sites:
        return Result(data, f"no references to {args.name} (comments and strings excluded)")
    shown = sites[:max(0, TEXT_LIMIT if args.limit is None else args.limit)]
    lines = [f"{args.name}: {len(sites)} sites in {len(files)} files "
             f"({summary['prod_files']} prod, {summary['test_files']} test)"]
    if len(sites) > len(shown):
        lines.append("by group: " + ", ".join(f"{'[test] ' if g['test'] else ''}{g['group']} {g['sites']}"
                                             for g in by_group))
    current = None
    for s in shown:
        key = (s.test, s.group)
        if key != current:
            current = key
            g = next(x for x in by_group if (x["test"], x["group"]) == key)
            lines.append(f"\n[{'test' if s.test else 'prod'}] {s.group}  ({g['sites']} sites, {g['files']} files)")
        lines.append(f"  {s.path}:{s.line}  {s.text}")
    if len(sites) > len(shown):
        lines.append(f"\n… {len(sites) - len(shown)} more sites (--limit N to list more, --area or --no-tests to narrow)")
    return Result(data, "\n".join(lines))
