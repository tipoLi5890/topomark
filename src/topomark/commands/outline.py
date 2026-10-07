"""``topomark outline <path>..``: a file's declarations with line ranges, nested by container;
several files or a directory at once, top level only, within a token budget."""

from __future__ import annotations

from . import Result
from ._common import add, rel


MULTI_TOKENS = 2000  # default budget when several files are outlined


def register(sub, common) -> None:
    p = add(sub, common, "outline", "list a file's symbols with line ranges, kinds, signatures and doc summaries",
            "Every declaration a reader navigates to (types, members, top-level functions, constants),\n"
            "nested by container, with 1-based inclusive line ranges. The range includes leading doc\n"
            "comments and attributes; feed it to `topomark symbol <file>#<Name>` or a ranged read.\n"
            "Several files or a directory (its git code files, recursively) are outlined together:\n"
            "top-level declarations only unless --depth says otherwise, within --tokens (default\n"
            f"{MULTI_TOKENS}), with a count of the files left out; the JSON is then {{\"files\": [...]}}.",
            "examples:\n  topomark outline src/router.py\n  topomark outline Big.cs --kinds class,method --depth 2\n"
            "  topomark outline Big.cs --exported-only --json\n  topomark outline src/core/ --tokens 1200\n"
            "  topomark outline src/a.py src/b.py --depth 2")
    p.add_argument("paths", nargs="+", metavar="path", help="a file, several files, or directories")
    p.add_argument("--exported-only", action="store_true", help="hide private / non-exported declarations")
    p.add_argument("--kinds", metavar="K,..", help="only these kinds (class,method,function,const,...)")
    p.add_argument("--depth", type=int, metavar="N",
                   help="nesting levels to show (1 = top level only; default: all for one file, 1 for several)")
    p.add_argument("--tokens", type=int, metavar="N",
                   help=f"several files: stop adding files at this many output tokens (default {MULTI_TOKENS})")
    p.set_defaults(handler=run)


def _outline(info, path: str, args, depth: int | None, header_lines: int = 3) -> tuple[dict, list[str]]:
    """The JSON object and text lines of one file's outline."""
    from ..navigate import clip, depth_of

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
        if depth is not None and depth_of(s) >= depth:
            continue
        shown.append(s)
    data = {"path": path, "lang": info.lang, "line_count": info.line_count, "header": info.header,
            "namespaces": namespaces, "count": len(shown), "total": sum(1 for s in info.symbols if s.kind != "namespace"),
            "symbols": [{**s.to_json(), "depth": depth_of(s)} for s in shown]}
    head = f"{path}  ({info.line_count} lines, {info.lang}" + (f", namespace {', '.join(namespaces)}" if namespaces else "") + ")"
    lines = [head]
    header = [h for h in info.header if h.strip()]
    for h in header[:header_lines]:
        lines.append("  " + clip(h, 120))
    if len(header) > header_lines and header_lines > 1:
        lines.append(f"  … ({len(header) - header_lines} more header lines)")
    width = len(str(info.line_count or 1))
    for s in shown:
        rng = f"{s.start}-{s.end}".rjust(2 * width + 1)
        mark = "" if s.exported else " -"
        doc = f"  // {clip(s.doc, 80)}" if s.doc else ""
        attrs = f"[{', '.join(s.attrs)}] " if s.attrs else ""
        lines.append(f"{'  ' * (depth_of(s) + 1)}{rng}  {s.kind}{mark}  {attrs}{clip(s.signature, 140)}{doc}")
    if not shown:
        lines.append("  (no declarations" + (" match the filters)" if data["total"] else ")"))
    return data, lines


def _targets(nav, ctx, raw_paths: list[str]) -> tuple[list[str], bool]:
    """The files to outline, and whether a directory was expanded."""
    from ..errors import TopomarkError
    from ..lang import registry
    from ..navigate import NON_CODE_LANGS

    out: list[str] = []
    expanded = False
    for raw in raw_paths:
        path = rel(ctx, raw).rstrip("/")
        if nav.exists(path):
            found = [path]
        else:
            prefix = path + "/" if path not in ("", ".") else ""
            found = [f for f in ctx.code_files if f.startswith(prefix)
                     and getattr(registry.adapter_for(f), "name", "") not in NON_CODE_LANGS]
            if not found:
                what = "code files under" if (ctx.root / path).is_dir() else "such file or directory:"
                raise TopomarkError("NOT_FOUND", f"no {what} {path or '.'}")
            expanded = True
        out += [f for f in found if f not in out]
    return out, expanded


def run(args, ctx) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav, estimate_tokens

    nav = Nav(ctx)
    files, expanded = _targets(nav, ctx, args.paths)
    if len(files) == 1 and not expanded:
        data, lines = _outline(nav.info(files[0]), files[0], args, args.depth)
        return Result(data, "\n".join(lines))
    budget = MULTI_TOKENS if args.tokens is None else args.tokens
    if budget < 1:
        raise TopomarkError("USAGE", "--tokens must be 1 or more")
    depth = 1 if args.depth is None else args.depth
    shown: list[dict] = []
    text: list[str] = []
    used = 0
    for path in files:
        try:
            info = nav.info(path)
        except (OSError, TopomarkError):
            continue
        data, lines = _outline(info, path, args, depth, header_lines=1)
        cost = estimate_tokens("\n".join(lines)) + 1
        if shown and used + cost > budget:
            break
        shown.append(data)
        text += lines
        used += cost
    left = len(files) - len(shown)
    if left:
        text.append(f"… {left} more file{'s' if left != 1 else ''} (raise --tokens, or outline a narrower path)")
    out = {"files": shown, "total_files": len(files), "shown_files": len(shown), "truncated": left > 0,
           "depth": depth, "budget": budget, "estimated_tokens": used}
    return Result(out, "\n".join(text))
