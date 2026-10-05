"""``topomark find <Name>``: where is something defined?"""

from __future__ import annotations

from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "find", "find definitions by name across the repo (substring, case-insensitive)",
            "Matches declaration names (and qualified names when the query has a dot). Exact\n"
            "matches sort first, then production code before tests.",
            "examples:\n  topomark find router\n  topomark find Router.add --exact\n  topomark find Pad --kind class")
    p.add_argument("name")
    p.add_argument("--kind", metavar="K,..", help="only these kinds (class,method,function,const,...)")
    p.add_argument("--exact", action="store_true", help="whole name (or Qual.Name suffix), case-sensitive")
    p.add_argument("--limit", type=int, default=50, metavar="N", help="max results (default 50)")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav

    nav = Nav(ctx)
    q = args.name
    ql = q.lower()
    kinds = {k.strip() for k in args.kind.split(",") if k.strip()} if args.kind else None
    hits = []
    for path, info in nav.infos.items():
        for s in info.symbols:
            if kinds is not None:
                if s.kind not in kinds:
                    continue
            elif s.kind == "namespace":
                continue
            if args.exact:
                ok = s.name == q or s.qualname == q or s.qualname.endswith("." + q)
            else:
                ok = ql in (s.qualname.lower() if "." in q else s.name.lower())
            if ok:
                rank = (0 if s.name == q or s.qualname == q else 1 if s.name.lower() == ql else 2,
                        nav.is_test(path), path, s.start)
                hits.append((rank, path, s))
    hits.sort(key=lambda h: h[0])
    if not hits:
        raise TopomarkError("NOT_FOUND", f"no definition matching {q!r}")
    shown = hits[: max(1, args.limit)]
    rows = [{"path": p, "start": s.start, "end": s.end, "line": s.line, "kind": s.kind, "qualname": s.qualname,
             "signature": s.signature, "exported": s.exported, "test": nav.is_test(p)} for _, p, s in shown]
    text = [f"{r['path']}:{r['start']}-{r['end']}  {r['kind']}  {r['qualname']}  {r['signature'][:120]}" for r in rows]
    if len(hits) > len(shown):
        text.append(f"… {len(hits) - len(shown)} more (use --limit)")
    return Result({"query": q, "total": len(hits), "results": rows}, "\n".join(text))
