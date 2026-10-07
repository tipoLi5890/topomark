"""``topomark changes [--staged | --since REV]``: the symbols a diff touches, interface or body,
who still uses the changed interfaces, the tests to run, and the code-map rows to review."""

from __future__ import annotations

from . import Result
from ._common import add

MAX_IMPACT = 12   # interface changes whose references are looked up; the rest get a pointer to `impact`


def register(sub, common) -> None:
    p = add(sub, common, "changes", "the symbols a diff touches (interface or body), their callers, tests, rows to review",
            "`git diff -U0` line ranges mapped to the innermost declaration on each side; the old side\n"
            "is analyzed from `git show REV:path`. By qualified name: added, removed or a changed\n"
            "signature is an interface change, other edited lines are body changes. For interface\n"
            "changes: who still references the name (one hop), the tests to run (as `tests-for`) and\n"
            "the code-map rows whose review stamp the change affects. Default: working tree vs HEAD,\n"
            "untracked files included.",
            "examples:\n  topomark changes\n  topomark changes --staged\n  topomark changes --since main --top 10")
    p.add_argument("--staged", action="store_true", help="the index vs HEAD (what the next commit holds)")
    p.add_argument("--since", metavar="REV", help="the working tree vs REV")
    p.add_argument("--top", type=int, default=5, metavar="N", help="callers listed per interface change (default 5)")
    p.set_defaults(handler=run)


def _sides(ctx, nav, path: str, status: str, base: str | None, staged: bool):
    """(old FileInfo, new FileInfo, old lines, new lines) for one changed file; None where a side
    does not exist or is too large to parse."""
    from ..index import MAX_BYTES
    from ..lang import registry
    from ..repo import git

    old = new = old_lines = new_lines = None
    if status != "added" and base:
        text = git(ctx.root, "show", f"{base}:{path}", check=False).replace("\r\n", "\n")
        if len(text) <= MAX_BYTES:
            old, old_lines = registry.analyze(path, text), text.split("\n")
    if status != "deleted":
        if staged:
            text = git(ctx.root, "show", f":{path}", check=False).replace("\r\n", "\n")
            if len(text) <= MAX_BYTES:
                new, new_lines = registry.analyze(path, text), text.split("\n")
        elif nav.exists(path):
            new, new_lines = nav.info(path), nav.lines(path)
    return old, new, old_lines, new_lines


def _fold(symbols: list[dict]) -> list[tuple[dict, int]]:
    """Members of an added (or removed) type fold into it: (symbol, folded member count)."""
    whole = {s["qualname"]: s["change"] for s in symbols if s["change"] in ("added", "removed")}
    counts: dict[str, int] = {}
    order: list[dict] = []
    for s in symbols:
        parts = s["qualname"].split(".")
        top = next((".".join(parts[:k]) for k in range(1, len(parts))
                    if whole.get(".".join(parts[:k])) == s["change"]), None)
        if top is None:
            order.append(s)
            counts.setdefault(s["qualname"], 0)
        else:
            counts[top] = counts.get(top, 0) + 1
    return [(s, counts.get(s["qualname"], 0)) for s in order]


def run(args, ctx) -> Result:
    from .. import changes as C
    from ..errors import TopomarkError
    from ..lang import registry
    from ..navigate import (NON_CODE_LANGS, Nav, changed_files, clip, code_map_row, impact_symbol, runner_commands,
                            select_tests)
    from ..repo import git, is_secret, matches_any

    if args.staged and args.since:
        raise TopomarkError("USAGE", "--staged and --since are alternatives; pick one")
    root = ctx.root
    if args.since:
        if not git(root, "rev-parse", "--verify", "-q", f"{args.since}^{{commit}}", check=False).strip():
            raise TopomarkError("NOT_FOUND", f"unknown revision: {args.since}")
        base: str | None = args.since
        diff_args, source = [args.since], f"since {args.since}"
    else:
        base = "HEAD" if git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).strip() else None
        diff_args, source = (["--cached"] if args.staged else ["HEAD"]), ("staged" if args.staged else "diff")
    out = git(root, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
              *diff_args, "--", check=False) if base or args.staged else ""
    diffs = C.parse_diff(out)
    for name in changed_files(ctx, staged=args.staged, since=args.since):
        if name not in diffs:
            diffs[name] = C.FileDiff(name, "added", whole=True)
    nav = Nav(ctx)
    cfg = ctx.config
    files: list[dict] = []
    other: list[dict] = []
    interface: list[tuple[str, dict]] = []
    for path in sorted(diffs):
        d = diffs[path]
        if is_secret(path) or matches_any(path, cfg.exclude):
            continue
        if getattr(registry.adapter_for(path), "name", "") in NON_CODE_LANGS or path.startswith(cfg.docs_prefix):
            other.append({"path": path, "status": d.status})
            continue
        old, new, old_lines, new_lines = _sides(ctx, nav, path, d.status, base, args.staged)
        syms, header, outside = C.classify(old, new, d, old_lines, new_lines)
        files.append({"path": path, "status": d.status, "lang": (new or old).lang if (new or old) else "",
                      "header_changed": header, "outside_declarations": outside and d.status == "modified",
                      "symbols": syms})
        interface += [(path, s) for s in syms if s["change"] in C.INTERFACE]
    # who still uses what changed shape: removed first, then changed signatures, exported first
    reach: list[dict] = []
    looked = [(p, s) for p, s in interface if s["change"] != "added"]
    looked.sort(key=lambda x: (x[1]["change"] != "removed", not x[1]["exported"], x[0], x[1]["start"]))
    for path, s in looked[:MAX_IMPACT]:
        try:
            imp = impact_symbol(nav, s["qualname"], top=max(1, args.top))
            refs = imp["refs"]
            item = {"path": path, "qualname": s["qualname"], "change": s["change"], "sites": refs["sites"],
                    "prod_files": refs["prod_files"], "test_files": refs["test_files"], "callers": imp["callers"],
                    "tests": imp["tests"]}
        except TopomarkError:  # nothing defines or mentions it any more
            item = {"path": path, "qualname": s["qualname"], "change": s["change"], "sites": 0, "prod_files": 0,
                    "test_files": 0, "callers": [], "tests": []}
        reach.append(item)
    present = [f["path"] for f in files if f["status"] != "deleted" and f["path"] in nav.infos]
    sel = select_tests(nav, present, depth=2)
    picks = sel.ordered()
    commands, unmatched = runner_commands(cfg.runners, picks)
    suite = list(dict.fromkeys(r.suite for r in cfg.runners if r.suite)) if sel.uncovered else []
    review = []
    for f in files:
        if f["header_changed"] or any(s["change"] in C.INTERFACE for s in f["symbols"]):
            row = code_map_row(nav, f["path"])
            if row["file"]:
                review.append({"path": f["path"], "status": f["status"], "area": row["name"], "area_file": row["file"],
                               "unit": row["unit"], "stamp": row["stamp"], "row": row["row"]})
    n_iface = len(interface) + sum(1 for f in files if f["header_changed"])
    n_body = sum(1 for f in files for s in f["symbols"] if s["change"] == "body")
    data = {"source": source, "base": base, "files": files, "other": other, "interface": reach,
            "interface_total": len(looked), "tests": [pk.to_json() for pk in picks], "commands": commands,
            "unmatched": [pk.path for pk in unmatched], "uncovered": sel.uncovered, "suite_commands": suite,
            "review": review, "counts": {"files": len(files), "interface": n_iface, "body": n_body}}

    vs = f"working tree vs {base or 'nothing (no commit yet)'}" if source == "diff" else (
        "index vs HEAD" if source == "staged" else f"working tree vs {args.since}")
    lines = [f"changes ({vs}): {len(files)} code file{'s' if len(files) != 1 else ''}, {n_iface} interface, "
             f"{n_body} body" + (f"; {len(other)} other file{'s' if len(other) != 1 else ''}" if other else "")]
    if not files:
        lines.append("  no code changed")
    for f in files:
        lines.append(f"{f['path']}  ({f['status']})" + ("  header comment changed" if f["header_changed"] else ""))
        for s, folded in _fold(f["symbols"]):
            sig = s["signature"] if s["signature"] is not None else s["old_signature"]
            more = f"  (+{folded} member{'s' if folded != 1 else ''})" if folded else ""
            lines.append(f"  {s['change']:<9} {s['kind']:<9} {s['qualname']}{more}  {clip(sig or '', 90)}")
            if s["change"] == "signature":
                lines.append(f"  {'':<9} {'':<9} was: {clip(s['old_signature'] or '', 100)}")
        if f["outside_declarations"]:
            lines.append("  lines outside any declaration changed (imports, module-level code)")
    if reach:
        lines.append("interface changes reach:")
        for r in reach:
            if not r["sites"]:
                lines.append(f"  {r['qualname']} ({r['change']}): no references left")
                continue
            warn = "  still referenced after removal" if r["change"] == "removed" else ""
            shown = ", ".join(r["callers"][:args.top]) or "tests only"
            more = r["prod_files"] - min(len(r["callers"]), args.top)
            lines.append(f"  {r['qualname']} ({r['change']}): {r['sites']} site{'s' if r['sites'] != 1 else ''} "
                         f"in {r['prod_files']} prod + "
                         f"{r['test_files']} test files: {shown}{f' … +{more}' if more > 0 else ''}{warn}")
        if len(looked) > len(reach):
            lines.append(f"  … {len(looked) - len(reach)} more interface changes (`topomark impact <Name>` each)")
    if picks:
        lines.append(f"tests ({len(picks)}):")
        for pk in picks[:10]:
            what = ("whole file" if pk.whole_file else f"{len(pk.methods)} test{'s' if len(pk.methods) != 1 else ''}"
                    if pk.methods else "classes " + ", ".join(pk.classes))
            lines.append(f"  {pk.path}  {what}" + (f"  (via {pk.via[-1]})" if pk.via else ""))
        if len(picks) > 10:
            lines.append(f"  … {len(picks) - 10} more (`topomark tests-for --{'staged' if args.staged else 'diff'}`)")
    elif files:
        lines.append("tests: none picked" + ("; run the whole suite" if sel.uncovered else ""))
    for c in commands:
        lines += [f"run: {cmd}" for cmd in c["commands"]]
    lines += [f"run the whole suite: {cmd}" for cmd in suite]
    if review:
        lines.append("code-map rows to review (then `topomark stamp <unit>`):")
        for r in review:
            state = "deleted: drop the row" if r["status"] == "deleted" else f"stamp {r['stamp'] or 'n/a'}"
            lines.append(f"  {r['area_file']}  {r['unit']}  ({state})")
    return Result(data, "\n".join(lines))
