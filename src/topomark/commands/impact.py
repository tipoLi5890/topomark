"""``topomark impact <Name|file>``: what does touching this affect?"""

from __future__ import annotations

from collections import Counter

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "impact", "one-shot impact summary for a file or a symbol: callers, tests, docs",
            "For a file: the names it declares, fan-in (prod/test), cross-area callers, owning area,\n"
            "review-stamp state, tests that mention it, docs that mention its path. For a symbol:\n"
            "definitions, references by area, tests that use it, and mentions in docs/contracts.",
            "examples:\n  topomark impact src/core/router.py\n  topomark impact Router\n  topomark impact Budget.ReactionFloor")
    p.add_argument("target", help="a repo path or a symbol name (Name or Type.Member)")
    p.add_argument("--top", type=int, default=10, metavar="N", help="list length per section (default 10)")
    p.set_defaults(handler=run)


def _list(title: str, items: list[str], top: int) -> list[str]:
    if not items:
        return [f"{title}: none"]
    out = [f"{title} ({len(items)}):"] + [f"  {x}" for x in items[:top]]
    if len(items) > top:
        out.append(f"  … {len(items) - top} more")
    return out


def run(args, ctx) -> Result:
    from ..navigate import Nav

    nav = Nav(ctx)
    path = rel(ctx, args.target)
    if nav.exists(path):
        return _file(nav, path, args.top)
    if "/" in args.target:
        from ..errors import TopomarkError

        raise TopomarkError("NOT_FOUND", f"no such file: {path}")
    return _symbol(nav, args.target, args.top)


def _file(nav, path: str, top: int) -> Result:
    from .. import docs as D

    ws = nav.ws
    info = nav.info(path)
    names = nav.decl_names(path)
    usable = sorted(nav.graph.names_of(path)) if path in nav.infos else []
    fi = nav.graph.fanin(path) if path in nav.infos else None
    prod = sorted(fi.prod) if fi else []
    tests = sorted(fi.test) if fi else []
    if not tests and names:  # graph ignores short/ambiguous names; fall back to a direct scan
        tests = sorted(p for p, i in nav.infos.items() if nav.is_test(p) and p != path and set(names) & i.idents)
    cross = nav.graph.cross_areas(path) if fi and ws.areas else []
    a, _ = D.owner_of(path, ws.areas)
    unit = D.unit_of(path, a) if a else None
    stamp = None
    if unit and unit in ws.units:
        rec = ws.stamps.units.get(unit)
        stamp = "none" if not rec else ("current" if rec.get("surface") == ws.unit_hash(unit) else "changed")
    base = path.rsplit("/", 1)[-1]
    mentions = [m for m in nav.mentions(base) if m.path != path]
    data = {"kind": "file", "path": path, "lang": info.lang, "line_count": info.line_count,
            "declares": names, "fanin_names": usable, "test": nav.is_test(path),
            "fanin": {"prod": len(prod), "test": len(tests), "prod_files": prod[:top], "test_files": tests[:top]},
            "cross_areas": cross, "area": a.name if a else None, "area_file": a.file if a else None,
            "unit": unit, "stamp": stamp,
            "mentions": {"count": len(mentions), "files": sorted({m.path for m in mentions})[:top]}}
    lines = [f"{path}  ({info.line_count} lines, {info.lang})",
             f"declares: {', '.join(names) or '-'}" + (f"  (fan-in counted on: {', '.join(usable)})"
                                                         if usable and usable != names else ""),
             f"area: {a.file if a else '(no area)'}" + (f"  unit {unit}" if unit and unit != path else "")
             + (f"  review stamp: {stamp}" if stamp else ""),
             f"fan-in {len(prod)}/{len(tests)}" + (f"  cross-area: {', '.join(cross)}" if cross else "")]
    lines += _list("callers (prod)", prod, top)
    lines += _list("tests", tests, top)
    lines += _list("docs mentioning", sorted({m.path for m in mentions}), top)
    return Result(data, "\n".join(lines))


def _symbol(nav, spec: str, top: int) -> Result:
    from ..errors import TopomarkError

    defs = nav.find_symbols(spec)
    sites = nav.ref_sites(spec)
    last = spec.rsplit(".", 1)[-1]
    if not defs and not sites:
        raise TopomarkError("NOT_FOUND", f"{spec!r} is neither a file nor a declared name (try `topomark find {last}`)")
    by_area: Counter = Counter()
    files_by_area: dict[str, set[str]] = {}
    for s in sites:
        if not s.test:
            by_area[s.group] += 1
            files_by_area.setdefault(s.group, set()).add(s.path)
    test_files = sorted({s.path for s in sites if s.test})
    prod_files = sorted({s.path for s in sites if not s.test})
    mentions = nav.mentions(spec) if "." in spec else []
    if not mentions:
        mentions = nav.mentions(last)
    def_files = {p for p, _ in defs}
    mentions = [m for m in mentions if m.path not in def_files]
    data = {"kind": "symbol", "name": spec,
            "definitions": [{"path": p, "qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end,
                             "signature": s.signature} for p, s in defs],
            "refs": {"sites": len(sites), "prod_files": len(prod_files), "test_files": len(test_files),
                     "by_area": [{"group": g, "sites": n, "files": len(files_by_area[g])}
                                 for g, n in by_area.most_common()]},
            "callers": prod_files[:top], "tests": test_files[:top],
            "mentions": {"count": len(mentions), "files": sorted({m.path for m in mentions})[:top],
                         "lines": [m.to_json() for m in mentions[:top]]}}
    lines = [f"{spec}"]
    lines += _list("defined", [f"{p}:{s.start}-{s.end}  {s.kind}  {s.qualname}" for p, s in defs], top)
    lines.append(f"refs: {len(sites)} sites in {len(prod_files)} prod + {len(test_files)} test files")
    for g, n in by_area.most_common(top):
        lines.append(f"  {g}: {n} sites in {len(files_by_area[g])} files")
    lines += _list("callers (prod)", prod_files, top)
    lines += _list("tests", test_files, top)
    lines += _list("docs/contracts mentioning", [f"{m.path}:{m.line}  {m.text[:100]}" for m in mentions], top)
    return Result(data, "\n".join(lines))
