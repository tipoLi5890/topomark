"""``topomark search <keywords>``: find code by what it is about (BM25 over names, docs, paths)."""

from __future__ import annotations

from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "search", "find code by keywords: BM25 over symbol names, signatures, docs and paths",
            "Ranks symbols by how well their name (split at case changes and underscores), container,\n"
            "signature, doc summary and path match the keywords, plus their file's header and code-map\n"
            "row. A test whose name matches lends its score to the code its body uses (`via`).\n"
            "Production code ranks above tests, code above Markdown and data files. Give a few\n"
            "keywords, not a pasted issue: every extra word dilutes the ranking. Output is capped\n"
            "(--limit, --tokens) with a count of what was left out; there are no further pages.",
            "examples:\n  topomark search review stamp surface hash\n  topomark search \"cache directory\" --limit 5\n"
            "  topomark search token budget --area core --tokens 600")
    p.add_argument("query", nargs="+", help="keywords (several words, quoted or not)")
    p.add_argument("--limit", type=int, default=15, metavar="N", help="results to show (default 15)")
    p.add_argument("--area", help="only files in this area (or top-level directory)")
    p.add_argument("--tokens", type=int, metavar="N", help="stop adding results at this many output tokens")
    p.set_defaults(handler=run)


def _line(h, width: int) -> str:
    from ..navigate import clip

    loc = f"{h.path}:{h.start}-{h.end}" if h.qualname else h.path
    text = f"  {loc:<{width}}  {h.kind}  {h.qualname}" if h.qualname else f"  {loc:<{width}}  file"
    if h.signature:
        text += f"  {clip(h.signature, 100)}"
    if h.group != "code":
        text += f"  [{h.group}]"
    if h.via:
        text += f"  (via {h.via[0]}{' …' if len(h.via) > 1 else ''})"
    return text


def run(args, ctx) -> Result:
    from .. import search as S
    from ..errors import TopomarkError
    from ..navigate import Nav, estimate_tokens

    if args.limit < 1:
        raise TopomarkError("USAGE", "--limit must be 1 or more")
    nav = Nav(ctx)
    nav.check_area(args.area)
    text = " ".join(args.query)
    if not S.query_terms(text):
        raise TopomarkError("USAGE", f"no searchable words in {text!r} (stop words and punctuation are ignored)")
    keep = (lambda p: nav.in_area(p, args.area)) if args.area else None
    res = S.search(S.load(nav), text, args.limit, keep)
    head = (f"search {text!r}: {res.total} match{'es' if res.total != 1 else ''} in {res.files} "
            f"file{'s' if res.files != 1 else ''}")
    width = min(60, max([len(f"{h.path}:{h.start}-{h.end}") for h in res.hits] + [10]))
    lines = [head]
    used = estimate_tokens(head)
    kept: list[S.Hit] = []
    for h in res.hits:
        line = _line(h, width)
        cost = estimate_tokens(line) + 1
        if args.tokens is not None and kept and used + cost > args.tokens:
            break
        kept.append(h)
        lines.append(line)
        used += cost
    if not res.hits:
        lines.append("  nothing matches; try other words, or `topomark find <Name>` for a name fragment")
    elif res.total > len(kept):
        why = "--tokens" if len(kept) < len(res.hits) else "--limit"
        lines.append(f"… {res.total - len(kept)} more (raise {why}, or add a distinctive keyword)")
    data = {"query": text, "terms": res.terms, "total": res.total, "files": res.files, "shown": len(kept),
            "truncated": res.total > len(kept), "results": [h.to_json() for h in kept]}
    return Result(data, "\n".join(lines))
