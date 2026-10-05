"""``topomark symbol <file>#<Name> | <Name>``: print one symbol's source lines."""

from __future__ import annotations

from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "symbol", "print just one symbol's source (file#Name, file#Outer.Name, or a bare Name)",
            "Prints the symbol's lines with line numbers (like `cat -n`). With a bare Name the repo is\n"
            "searched; a name declared in several files lists the candidates and exits 4. Overloads in\n"
            "one file are all printed.",
            "examples:\n  topomark symbol src/router.py#Router.add\n  topomark symbol Router --signature\n"
            "  topomark symbol Views.cs#ResultView --context 3")
    p.add_argument("spec", help="<file>#<Name|Qual.Name> or <Name>")
    p.add_argument("--signature", action="store_true", help="signature and doc summary only")
    p.add_argument("--context", type=int, default=0, metavar="N", help="extra lines before and after")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..navigate import Nav

    nav = Nav(ctx)
    matches, candidates = nav.resolve(args.spec)
    if candidates:
        cands = [{"path": p, "qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end,
                  "signature": s.signature} for p, s in candidates]
        text = [f"{args.spec!r} is declared in {len({p for p, _ in candidates})} files; pick one with <file>#<Name>:"]
        text += [f"  {c['path']}#{c['qualname']}  {c['start']}-{c['end']}  {c['kind']}  {c['signature']}" for c in cands]
        return Result({"spec": args.spec, "ambiguous": True, "candidates": cands, "matches": []}, "\n".join(text), 4)
    out = []
    blocks = []
    ctxn = max(0, args.context)
    for path, s in matches:
        item = {"path": path, "qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end,
                "line": s.line, "signature": s.signature, "doc": s.doc, "exported": s.exported}
        if s.attrs:
            item["attrs"] = s.attrs
        head = f"{path}:{s.start}-{s.end}  {s.kind}  {s.qualname}"
        if args.signature:
            blocks.append("\n".join([head, "  " + s.signature] + (["  // " + s.doc] if s.doc else [])))
        else:
            lines = nav.lines(path)
            lo, hi = max(1, s.start - ctxn), min(len(lines), s.end + ctxn)
            width = len(str(hi))
            body = [f"{n:>{width}}\t{lines[n - 1]}" for n in range(lo, hi + 1)]
            item.update({"from": lo, "to": hi, "source": "\n".join(lines[lo - 1:hi])})
            blocks.append("\n".join([head] + body))
        out.append(item)
    return Result({"spec": args.spec, "ambiguous": False, "matches": out}, "\n\n".join(blocks))
