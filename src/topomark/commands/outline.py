"""``topomark outline <file>``: a file's declarations with line ranges, nested by container."""

from __future__ import annotations

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "outline", "list a file's symbols with line ranges, kinds, signatures and doc summaries",
            "Every declaration a reader navigates to (types, members, top-level functions, constants),\n"
            "nested by container, with 1-based inclusive line ranges. The range includes leading doc\n"
            "comments and attributes; feed it to `topomark symbol <file>#<Name>` or a ranged read.",
            "examples:\n  topomark outline src/router.py\n  topomark outline Big.cs --kinds class,method --depth 2\n"
            "  topomark outline Big.cs --exported-only --json")
    p.add_argument("file")
    p.add_argument("--exported-only", action="store_true", help="hide private / non-exported declarations")
    p.add_argument("--kinds", metavar="K,..", help="only these kinds (class,method,function,const,...)")
    p.add_argument("--depth", type=int, metavar="N", help="nesting levels to show (1 = top level only)")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..navigate import Nav, clip, depth_of

    nav = Nav(ctx)
    path = rel(ctx, args.file)
    info = nav.info(path)
    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()} if args.kinds else None
    namespaces = [s.name for s in info.symbols if s.kind == "namespace"]
    shown = []
    for s in info.symbols:
        if s.kind == "namespace":
            continue
        if args.exported_only and not s.exported:
            continue
        if kinds and s.kind not in kinds:
            continue
        if args.depth is not None and depth_of(s) >= args.depth:
            continue
        shown.append(s)
    data = {"path": path, "lang": info.lang, "line_count": info.line_count, "header": info.header,
            "namespaces": namespaces, "count": len(shown), "total": sum(1 for s in info.symbols if s.kind != "namespace"),
            "symbols": [{**s.to_json(), "depth": depth_of(s)} for s in shown]}
    head = f"{path}  ({info.line_count} lines, {info.lang}" + (f", namespace {', '.join(namespaces)}" if namespaces else "") + ")"
    lines = [head]
    header = [h for h in info.header if h.strip()]
    for h in header[:3]:
        lines.append("  " + clip(h, 120))
    if len(header) > 3:
        lines.append(f"  … ({len(header) - 3} more header lines)")
    width = len(str(info.line_count or 1))
    for s in shown:
        rng = f"{s.start}-{s.end}".rjust(2 * width + 1)
        mark = "" if s.exported else " -"
        doc = f"  // {clip(s.doc, 80)}" if s.doc else ""
        attrs = f"[{', '.join(s.attrs)}] " if s.attrs else ""
        lines.append(f"{'  ' * (depth_of(s) + 1)}{rng}  {s.kind}{mark}  {attrs}{clip(s.signature, 140)}{doc}")
    if not shown:
        lines.append("  (no declarations" + (" match the filters)" if data["total"] else ")"))
    return Result(data, "\n".join(lines))
