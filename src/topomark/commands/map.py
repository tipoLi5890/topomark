"""``topomark map``: an Aider-style repo map within a token budget."""

from __future__ import annotations

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "map", "ranked repo map: the most central files and their key signatures, within a token budget",
            "Files are ranked by PageRank over the reference graph, personalised toward --focus files\n"
            "(or files declaring a focused name). Each file shows its highest-weight declarations\n"
            "(types and exported names first, weighted by how many files use the name), in source\n"
            "order, until --tokens is reached (see `estimated_tokens`). Tests and docs are left out.",
            "examples:\n  topomark map\n  topomark map --focus src/core/router.py --tokens 2000\n"
            "  topomark map --focus Router --area core")
    p.add_argument("--focus", nargs="+", default=[], metavar="PATH_OR_NAME", help="files or names to centre on")
    p.add_argument("--tokens", type=int, default=1024, metavar="N", help="token budget (default 1024)")
    p.add_argument("--area", help="only files in this area (or top-level directory)")
    p.set_defaults(handler=run)


def _render(nav, chosen: dict[str, list], order: list[str]) -> str:
    from ..navigate import clip, depth_of

    out = []
    for path in order:
        syms = chosen.get(path)
        if syms is None:
            continue
        out.append(f"{path}:")
        info = nav.infos[path]
        by_q = {s.qualname: s for s in info.symbols}
        shown = set()
        lines = []
        for s in sorted(syms, key=lambda x: x.start):
            parts = s.container.split(".") if s.container else []
            for k in range(1, len(parts) + 1):  # container context lines
                q = ".".join(parts[:k])
                c = by_q.get(q)
                if c is not None and q not in shown:
                    shown.add(q)
                    lines.append((c.start, depth_of(c), c.signature))
            if s.qualname not in shown:
                shown.add(s.qualname)
                lines.append((s.start, depth_of(s), s.signature))
        for _, d, sig in lines:
            out.append(f"│{'    ' * d}{clip(sig, 120)}")
    return "\n".join(out) + ("\n" if out else "")


def run(args, ctx) -> Result:
    import heapq

    from ..navigate import Nav, estimate_tokens, name_weight, name_weight_bound, outline_size, pagerank_files

    nav = Nav(ctx)
    nav.check_area(args.area)
    infos = nav.infos
    candidates = {p for p, i in infos.items()
                  if nav.is_code(p, i) and not nav.is_test(p) and (not args.area or nav.in_area(p, args.area))}
    focus_files: set[str] = set()
    focus_names: set[str] = set()
    unknown = []
    for f in args.focus:
        p = rel(ctx, f)
        if p in infos:
            focus_files.add(p)
        elif nav.exists(p):
            unknown.append(f)
        else:
            decl = set(nav.graph.declared.get(f, ())) or {q for q, _ in nav.find_symbols(f)}
            if decl:
                focus_names.add(f.rsplit(".", 1)[-1])
                focus_files |= decl
            else:
                unknown.append(f)
    ranks = pagerank_files(nav, focus_files, candidates, focus_names)
    files = sorted((p for p in ranks if p in candidates or p in focus_files),
                   key=lambda p: (-ranks[p], p))
    files = [p for p in files if outline_size(infos[p])]
    budget = max(1, args.tokens)
    # At most `budget` pairs are ever shown. Files come in rank order, so once a file's best
    # possible weight is below the budget-th weight kept so far, no later symbol can make it.
    bound = name_weight_bound(nav) * (10 if focus_names else 1)
    top: list[float] = []  # min-heap of the `budget` largest weights
    pairs = []
    for p in files:
        if len(top) >= budget and ranks[p] * bound < top[0]:
            break
        for s in infos[p].symbols:
            if s.kind == "namespace":
                continue
            w = ranks[p] * name_weight(nav, s)
            if s.name in focus_names:
                w *= 10
            pairs.append((w, p, s))
            if len(top) < budget:
                heapq.heappush(top, w)
            elif w > top[0]:
                heapq.heapreplace(top, w)
    pairs.sort(key=lambda x: (-x[0], x[1], x[2].start))

    def build(n: int):
        chosen: dict[str, list] = {}
        for _, p, s in pairs[:n]:
            chosen.setdefault(p, []).append(s)
        return chosen, _render(nav, chosen, files)

    lo, hi = 0, min(len(pairs), budget)
    best = ({}, "")
    while lo <= hi:
        mid = (lo + hi) // 2
        chosen, text = build(mid)
        if estimate_tokens(text) <= budget:
            best = (chosen, text)
            lo = mid + 1
        else:
            hi = mid - 1
    chosen, text = best
    used = estimate_tokens(text)
    order = [p for p in files if p in chosen]
    data = {"budget": budget, "estimated_tokens": used, "focus": sorted(focus_files), "unknown_focus": unknown,
            "ranked_files": len(files),
            "files": [{"path": p, "rank": float(f"{ranks[p]:.4g}"),
                       "symbols": [{"name": s.name, "qualname": s.qualname, "kind": s.kind, "line": s.line or s.start,
                                    "signature": s.signature} for s in sorted(chosen[p], key=lambda x: x.start)]}
                      for p in order]}
    if unknown:
        ctx.log(f"map: ignored focus (not a code file or declared name): {', '.join(unknown)}")
    return Result(data, text.rstrip("\n") or "(empty map: no ranked declarations fit the budget)")
