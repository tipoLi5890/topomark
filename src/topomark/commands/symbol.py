"""``topomark symbol <file>#<Name> | <Name>``: print one symbol's source lines."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context
    from ..lang.base import Symbol
    from ..navigate import Nav


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "symbol", "print just one symbol's source (file#Name, file#Outer.Name, or a bare Name)",
            "Prints the symbol's lines with line numbers (like `cat -n`). With a bare Name the repo is\n"
            "searched; a name declared in several files lists the candidates and exits 4. Overloads in\n"
            "one file are all printed. --skeleton keeps every declaration and replaces the bodies of the\n"
            "innermost members with `… (lines A-B)`, so a whole class costs a fraction of its source.",
            "examples:\n  topomark symbol src/router.py#Router.add\n  topomark symbol Router --signature\n"
            "  topomark symbol src/router.py#Router --skeleton\n  topomark symbol Views.cs#ResultView --context 3")
    p.add_argument("spec", help="<file>#<Name|Qual.Name> or <Name>")
    p.add_argument("--signature", action="store_true", help="signature and doc summary only")
    p.add_argument("--skeleton", action="store_true",
                   help="declarations only: member bodies become `… (lines A-B)`")
    p.add_argument("--context", type=int, default=0, metavar="N", help="extra lines before and after")
    p.set_defaults(handler=run)


def _skeleton(nav: Nav, path: str, s: Symbol, lo: int, hi: int) -> tuple[list[str], str, list[list[int]]]:
    """Numbered lines, plain text, and the left-out ranges of a skeleton of ``s``."""
    from ..navigate import skeleton_gaps

    lines = nav.lines(path)
    gaps = {a: b for a, b in skeleton_gaps(nav, path, s)}
    width = len(str(hi))
    numbered, plain = [], []
    n = lo
    while n <= hi:
        if n in gaps:
            end = min(gaps[n], hi)
            first = next((ln for ln in lines[n - 1:end] if ln.strip()), "")
            indent = first[:len(first) - len(first.lstrip())]
            mark = f"{indent}… (lines {n}-{end})"
            numbered.append(f"{'':>{width}}\t{mark}")
            plain.append(mark)
            n = end + 1
            continue
        numbered.append(f"{n:>{width}}\t{lines[n - 1]}")
        plain.append(lines[n - 1])
        n += 1
    return numbered, "\n".join(plain), [[a, b] for a, b in sorted(gaps.items())]


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav

    if args.skeleton and args.signature:
        raise TopomarkError("USAGE", "--skeleton and --signature are alternatives; pick one")

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
        elif args.skeleton:
            lines = nav.lines(path)
            lo, hi = max(1, s.start - ctxn), min(len(lines), s.end + ctxn)
            numbered, plain, gaps = _skeleton(nav, path, s, lo, hi)
            item.update({"from": lo, "to": hi, "skeleton": plain, "elided": gaps})
            blocks.append("\n".join([head] + numbered))
        else:
            lines = nav.lines(path)
            lo, hi = max(1, s.start - ctxn), min(len(lines), s.end + ctxn)
            width = len(str(hi))
            body = [f"{n:>{width}}\t{lines[n - 1]}" for n in range(lo, hi + 1)]
            item.update({"from": lo, "to": hi, "source": "\n".join(lines[lo - 1:hi])})
            blocks.append("\n".join([head] + body))
        out.append(item)
    return Result({"spec": args.spec, "ambiguous": False, "matches": out}, "\n\n".join(blocks))
