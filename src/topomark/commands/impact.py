"""``topomark impact <Name|file>``: what does touching this affect?"""

from __future__ import annotations

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "impact", "one-shot impact summary for a file or a symbol: callers, tests, docs",
            "For a file: the names it declares, fan-in (prod/test), the files that import it (Python,\n"
            "JS/TS), cross-area callers, owning area, review-stamp state, tests that mention it, docs\n"
            "that mention its path. For a symbol: definitions, references by area, tests that use\n"
            "it, and mentions in docs/contracts.",
            "examples:\n  topomark impact src/core/router.py\n  topomark impact Router\n  topomark impact Budget.ReactionFloor")
    p.add_argument("target", help="a repo path or a symbol name (Name or Type.Member)")
    p.add_argument("--top", type=int, default=10, metavar="N", help="list length per section (default 10)")
    p.set_defaults(handler=run)


def _list(title: str, items: list[str], top: int, total: int | None = None) -> list[str]:
    total = len(items) if total is None else total
    if not total:
        return [f"{title}: none"]
    out = [f"{title} ({total}):"] + [f"  {x}" for x in items[:top]]
    if total > min(top, len(items)):
        out.append(f"  … {total - min(top, len(items))} more (--top N lists more)")
    return out


def run(args, ctx) -> Result:
    from ..navigate import Nav, impact_file, impact_symbol

    nav = Nav(ctx)
    path = rel(ctx, args.target)
    if nav.exists(path):
        data = impact_file(nav, path, args.top)
        return Result(data, _file_text(data, args.top))
    if "/" in args.target:
        from ..errors import TopomarkError

        raise TopomarkError("NOT_FOUND", f"no such file: {path}")
    data = impact_symbol(nav, args.target, args.top)
    return Result(data, _symbol_text(data, args.top))


def _file_text(d: dict, top: int) -> str:
    names, usable, fan = d["declares"], d["fanin_names"], d["fanin"]
    unit, stamp = d["unit"], d["stamp"]
    lines = [f"{d['path']}  ({d['line_count']} lines, {d['lang']})",
             f"declares: {', '.join(names) or '-'}" + (f"  (fan-in counted on: {', '.join(usable)})"
                                                         if usable and usable != names else ""),
             f"area: {d['area_file'] or '(no area)'}" + (f"  unit {unit}" if unit and unit != d["path"] else "")
             + (f"  review stamp: {stamp}" if stamp else ""),
             f"fan-in {fan['prod']}/{fan['test']}" + (f"  cross-area: {', '.join(d['cross_areas'])}"
                                                       if d["cross_areas"] else "")]
    lines += _list("callers (prod)", fan["prod_files"], top, fan["prod"])
    lines += _list("importers", d["importers"]["files"], top, d["importers"]["count"])
    lines += _list("tests", fan["test_files"], top, fan["test"])
    lines += _list("docs mentioning", d["mentions"]["files"], top, d["mentions"]["file_count"])
    return "\n".join(lines)


def _symbol_text(d: dict, top: int) -> str:
    refs = d["refs"]
    lines = [d["name"]]
    lines += _list("defined", [f"{x['path']}:{x['start']}-{x['end']}  {x['kind']}  {x['qualname']}"
                               for x in d["definitions"]], top)
    lines.append(f"refs: {refs['sites']} sites in {refs['prod_files']} prod + {refs['test_files']} test files")
    for g in refs["by_area"][:top]:
        lines.append(f"  {g['group']}: {g['sites']} sites in {g['files']} files")
    lines += _list("callers (prod)", d["callers"], top, refs["prod_files"])
    lines += _list("tests", d["tests"], top, refs["test_files"])
    lines += _list("docs/contracts mentioning", [f"{m['path']}:{m['line']}  {m['text'][:100]}"
                                                 for m in d["mentions"]["lines"]], top, d["mentions"]["count"])
    return "\n".join(lines)
