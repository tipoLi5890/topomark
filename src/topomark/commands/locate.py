"""``topomark locate "<message>" | --trace [FILE|-]``: the code behind an error message or a stack trace."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context

TRACE_CAP = 30  # frames listed; a deep recursion repeats itself


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "locate", "from an error message or a stack trace to the code that produced it",
            "A message: its word runs are looked up literally in every parsed file (so interpolated\n"
            "values and strings split across lines still match), weighted by how rare each run is, and\n"
            "summed per enclosing symbol; production code first, then tests, then docs and data. A\n"
            "trace (--trace FILE, or stdin with --trace or --trace -): Python, Node/V8, Firefox/Safari,\n"
            "Java/Kotlin, C#, Dart, Go and Rust frames and generic path:line, mapped to repo files by the\n"
            "longest shared path suffix, innermost frame first; frames outside the repo are skipped.",
            "examples:\n  topomark locate \"error: NOT_FOUND: no such file: src/app.py\"\n"
            "  topomark locate --trace crash.txt\n  pytest 2>&1 | topomark locate --trace\n"
            "  topomark locate \"unknown (section|key)\" --regex")
    p.add_argument("text", nargs="?", help="the message as printed (quote it)")
    p.add_argument("--trace", nargs="?", const="-", metavar="FILE", help="read a stack trace from FILE, or stdin")
    p.add_argument("--regex", action="store_true", help="TEXT is a regular expression, matched line by line")
    p.add_argument("--limit", type=int, default=10, metavar="N", help="places to show for a message (default 10)")
    p.set_defaults(handler=run)


def _read_trace(arg: str) -> str:
    import os
    import sys

    from ..errors import TopomarkError
    from ..repo import is_secret

    if arg == "-":
        return sys.stdin.read()
    path = os.path.abspath(arg)
    if is_secret(os.path.basename(path)):
        raise TopomarkError("REFUSED", f"--trace {arg}: the name looks like a secret, so it is not opened")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError as e:
        raise TopomarkError("NOT_FOUND", f"no such trace file: {arg}") from e
    except OSError as e:
        raise TopomarkError("NOT_FOUND", f"cannot read {arg}: {e.strerror}") from e


def _tag(group: str) -> str:
    return "" if group == "code" else f"[{group}] "


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from .. import locate as L
    from ..errors import TopomarkError
    from ..navigate import Nav

    if args.trace is not None and args.text:
        raise TopomarkError("USAGE", "give a message or --trace, not both")
    nav = Nav(ctx)
    if args.trace is not None:
        res = L.locate_trace(nav, _read_trace(args.trace))
        if not res.frames and not res.skipped:
            raise TopomarkError("USAGE", "no stack frames recognised (Python, Node, Java/Kotlin, C#, Dart, Go, Rust "
                                         "or path:line); for a message, pass it as text")
        frames = res.frames[:TRACE_CAP]
        data = {"mode": "trace", "formats": res.formats, "total": len(res.frames), "results": frames,
                "skipped": res.skipped, "truncated": len(res.frames) > len(frames)}
        lines = [f"trace ({', '.join(res.formats)}): {len(res.frames)} frame{'s' if len(res.frames) != 1 else ''} "
                 f"in the repo, innermost first" + (f"; {len(res.skipped)} outside skipped" if res.skipped else "")]
        for f in frames:
            where = f"{f['qualname']}  " if f["qualname"] else ""
            lines.append(f"  {_tag(f['group'])}{f['path']}:{f['line']}  {where}{f['text'].strip()}")
            if f.get("candidates"):
                lines.append(f"    also: {', '.join(f['candidates'][1:6])}")
        if len(res.frames) > len(frames):
            lines.append(f"… {len(res.frames) - len(frames)} more frames")
        if res.skipped:
            outside = ", ".join(f"{s['path']}:{s['line']}" for s in res.skipped[:3])
            lines.append(f"skipped (not in the repo): {outside}" + (" …" if len(res.skipped) > 3 else ""))
        if not res.frames:
            lines.append("no frame points into this repo")
        return Result(data, "\n".join(lines))
    if not args.text or not args.text.strip():
        raise TopomarkError("USAGE", "give the message to locate (quoted), or --trace FILE")
    if args.limit < 1:
        raise TopomarkError("USAGE", "--limit must be 1 or more")
    places = L.find_message(nav, args.text, regex=args.regex)
    shown = places[:args.limit]
    files = len({p.path for p in places})
    data = {"mode": "regex" if args.regex else "text", "query": args.text, "total": len(places), "files": files,
            "results": [p.to_json() for p in shown], "truncated": len(places) > len(shown)}
    lines = [f"locate {args.text!r}: {len(places)} place{'s' if len(places) != 1 else ''} in {files} "
             f"file{'s' if files != 1 else ''}" + (" (code first)" if places else "")]
    for p in shown:
        where = f"{p.qualname} ({p.kind} {p.start}-{p.end})  " if p.qualname else ""
        lines.append(f"  {_tag(p.group)}{p.path}:{p.line}  {where}{p.text.strip()}")
    if len(places) > len(shown):
        lines.append(f"… {len(places) - len(shown)} more (--limit N)")
    if not places:
        lines.append("  not found as written; try a shorter, distinctive part of the message, or --regex")
    return Result(data, "\n".join(lines))
