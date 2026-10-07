"""``topomark brief <file|Name>``: what to know before editing, in one answer within a token budget.

For a file: its area and code-map row, its exported outline (two levels), fan-in, the callers
most coupled to it (one hop: files that use its names or import it, most names used first), the
tests that cover it (``select_tests``) and the command that runs them, and the docs that mention
it. For a name: its definition and signature, its exported members, references, the callers with
the most reference sites, the tests that use it, and the same area, run and docs lines.

Over ``--tokens`` (default 1500) the outline's tail goes first, then the docs line, then the
caller and test lists shrink to three each; every cut leaves a count. ``related`` in the JSON is
the callers then the tests as shown, the order an agent reads them.
"""

from __future__ import annotations

from . import Result
from ._common import add, rel

DEFAULT_TOKENS = 1500
TOP = 10      # longest caller and test lists before the budget cuts them
KEEP = 3      # what the budget leaves of those lists


def register(sub, common) -> None:
    p = add(sub, common, "brief", "one budgeted briefing before an edit: area row, outline, callers, tests, run command",
            "A file, <file>#<Name> or a Name. Combines owner (area, row, review stamp), outline\n"
            "(exported, two levels), impact (fan-in, importers, callers one hop away, most coupled\n"
            "first) and tests-for (tests and the runnable command). Over --tokens the outline's tail\n"
            "goes first, then docs, then callers and tests shrink to three; each cut says how many\n"
            "were left out.",
            "examples:\n  topomark brief src/core/router.py\n  topomark brief Router\n"
            "  topomark brief src/core/router.py#Router.add --tokens 800")
    p.add_argument("target", help="a repo path, <file>#<Name>, or a Name (Type.Member works)")
    p.add_argument("--tokens", type=int, default=DEFAULT_TOKENS, metavar="N",
                   help=f"output budget (default {DEFAULT_TOKENS})")
    p.set_defaults(handler=run)


# ---------------------------------------------------------------- gathering
def _outline_rows(symbols) -> list[dict]:
    from ..navigate import depth_of

    return [{"qualname": s.qualname, "kind": s.kind, "start": s.start, "end": s.end, "signature": s.signature,
             "depth": depth_of(s)} for s in symbols]


def _pick_json(pk) -> dict:
    d = pk.to_json()
    d.pop("names", None)
    return d


def _tests(nav, picks, runners) -> dict:
    from ..navigate import runner_commands

    commands, unmatched = runner_commands(runners, picks)
    return {"tests": [_pick_json(pk) for pk in picks], "commands": commands, "unmatched": [pk.path for pk in unmatched]}


def _file_brief(nav, path: str) -> dict:
    from ..navigate import code_map_row, depth_of, impact_file, select_tests

    info = nav.info(path)
    imp = impact_file(nav, path, top=10**6)
    names = imp["declares"]
    importers = set(imp["importers"]["files"])
    prod = (set(imp["fanin"]["prod_files"]) | {f for f in importers if not nav.is_test(f)}) - {path}
    callers = []
    for c in prod:
        i = nav.infos.get(c)
        used = [n for n in names if i is not None and n in i.idents]
        callers.append({"path": c, "uses": used, "imports": c in importers})
    callers.sort(key=lambda c: (-len(c["uses"]), not c["imports"], c["path"]))
    sel = select_tests(nav, [path] if path in nav.infos else [], depth=2)
    picks = sorted(sel.ordered(), key=lambda pk: (bool(pk.via), -len(pk.names), -len(pk.methods), pk.path))
    outline = [s for s in info.symbols if s.kind != "namespace" and s.exported and depth_of(s) < 2]
    return {"kind": "file", "target": path, "path": path, "lang": info.lang, "line_count": info.line_count,
            "test": nav.is_test(path), "header": next((h.strip() for h in info.header if h.strip()), ""),
            "area": code_map_row(nav, path), "outline": _outline_rows(outline),
            "impact": {"fanin": {"prod": imp["fanin"]["prod"], "test": imp["fanin"]["test"]},
                       "importers": imp["importers"]["count"], "cross_areas": imp["cross_areas"]},
            "callers": callers, **_tests(nav, picks, nav.cfg.runners),
            "uncovered": bool(sel.uncovered), "limited": bool(sel.limited), "dynamic_loaders": sel.dynamic_loaders[:5],
            "mentions": {"count": imp["mentions"]["count"], "files": imp["mentions"]["files"]}}


def _symbol_brief(nav, spec: str) -> dict:
    from collections import Counter

    from ..navigate import code_map_row, impact_symbol, pick_tests, select_tests

    matches, candidates = nav.resolve(spec)
    if candidates:
        return {"ambiguous": True, "candidates": [{"path": p, "qualname": s.qualname, "kind": s.kind, "start": s.start,
                                                   "end": s.end, "signature": s.signature} for p, s in candidates]}
    path, sym = matches[0]
    name = spec.split("#", 1)[1] if "#" in spec else spec
    sites = nav.ref_sites(name)
    imp = impact_symbol(nav, name, top=10**6, sites=sites)
    per_file = Counter(s.path for s in sites)
    callers = [{"path": f, "sites": n} for f, n in per_file.items() if not nav.is_test(f) and f != path]
    callers.sort(key=lambda c: (-c["sites"], c["path"]))
    picks = []
    for t in sorted({s.path for s in sites if s.test}, key=lambda f: (-per_file[f], f)):
        pk = pick_tests(nav, t, [sym.name])
        if pk is not None:
            picks.append(pk)
    uncovered, limited, loaders = False, False, []
    if not picks and path in nav.infos:
        sel = select_tests(nav, [path], depth=2)
        picks = sorted(sel.ordered(), key=lambda pk: (bool(pk.via), -len(pk.names), -len(pk.methods), pk.path))
        uncovered, limited, loaders = bool(sel.uncovered), bool(sel.limited), sel.dynamic_loaders[:5]
    info = nav.info(path)
    members = [s for s in info.symbols if s.container == sym.qualname and s.exported and s.kind != "namespace"]
    return {"kind": "symbol", "target": spec, "path": path, "lang": info.lang, "line_count": info.line_count,
            "test": nav.is_test(path),
            "symbol": {"qualname": sym.qualname, "kind": sym.kind, "start": sym.start, "end": sym.end,
                       "signature": sym.signature, "doc": sym.doc, "overloads": len(matches)},
            "area": code_map_row(nav, path), "outline": _outline_rows(members),
            "impact": {"refs": imp["refs"]["sites"], "prod_files": imp["refs"]["prod_files"],
                       "test_files": imp["refs"]["test_files"], "by_area": imp["refs"]["by_area"][:5]},
            "callers": callers, **_tests(nav, picks, nav.cfg.runners),
            "uncovered": uncovered, "limited": limited, "dynamic_loaders": loaders,
            "mentions": {"count": imp["mentions"]["count"], "files": imp["mentions"]["files"]}}


# ---------------------------------------------------------------- rendering
def _render(b: dict, lim: dict, suite: list[str]) -> list[str]:
    from ..navigate import clip

    out: list[str] = []
    if b["kind"] == "file":
        out.append(f"{b['path']}  ({b['line_count']} lines, {b['lang']}{', test file' if b['test'] else ''})")
        if b["header"]:
            out.append(f"  {clip(b['header'], 120)}")
    else:
        s = b["symbol"]
        more = f"  (+{s['overloads'] - 1} overloads)" if s["overloads"] > 1 else ""
        out.append(f"{b['target']}  {s['kind']}  {b['path']}:{s['start']}-{s['end']}{more}")
        out.append(f"  {clip(s['signature'], 140)}")
        if s["doc"]:
            out.append(f"  // {clip(s['doc'], 120)}")
    a = b["area"]
    if a["file"]:
        out.append(f"area: {a['file']}" + (f"  unit {a['unit']}" if a["unit"] != b["path"] else "")
                   + (f"  review stamp: {a['stamp']}" if a["stamp"] else ""))
        out.append(f"row: {clip(a['row'], 240)}" if a["row"] else "row: none yet (`topomark draft "
                   f"{a['name']}`)")
    elif a["code_map"]:
        out.append("area: none; add a scope entry for it to an area file")
    outline = b["outline"]
    if outline:
        n = lim["outline"]
        title = "outline (exported, 2 levels)" if b["kind"] == "file" else "members (exported)"
        out.append(f"{title}:" if n >= len(outline) else f"{title}, {n} of {len(outline)}:")
        base = min(o["depth"] for o in outline)
        for o in outline[:n]:
            out.append(f"  {'  ' * (o['depth'] - base)}{o['start']}-{o['end']}  {o['kind']}  {clip(o['signature'], 110)}")
        if n < len(outline):
            out.append(f"  … {len(outline) - n} more (`topomark outline {b['path']}`)")
    imp = b["impact"]
    if b["kind"] == "file":
        line = f"fan-in {imp['fanin']['prod']}/{imp['fanin']['test']}, {imp['importers']} importers"
        out.append(line + (f", cross-area: {', '.join(imp['cross_areas'])}" if imp["cross_areas"] else ""))
    else:
        out.append(f"refs: {imp['refs']} sites in {imp['prod_files']} prod + {imp['test_files']} test files")
    callers = b["callers"]
    if callers:
        n = min(lim["callers"], len(callers))
        out.append(f"callers ({len(callers)}, most coupled first):")
        for c in callers[:n]:
            if "uses" in c:
                why = (f"uses {', '.join(c['uses'][:4])}{' …' if len(c['uses']) > 4 else ''}" if c["uses"]
                       else "") + ("; imports it" if c["imports"] and c["uses"] else "imports it" if c["imports"] else "")
            else:
                why = f"{c['sites']} site{'s' if c['sites'] != 1 else ''}"
            out.append(f"  {c['path']}  ({why})")
        if n < len(callers):
            out.append(f"  … {len(callers) - n} more (`topomark impact {b['target']}`)")
    else:
        out.append("callers: none found")
    tests = b["tests"]
    if tests:
        n = min(lim["tests"], len(tests))
        out.append(f"tests ({len(tests)}):")
        for t in tests[:n]:
            k = len(t["methods"])
            what = ("whole file" if t["whole_file"] else f"{k} test{'s' if k != 1 else ''}: " + ", ".join(t["methods"][:4])
                    + (" …" if len(t["methods"]) > 4 else "") if t["methods"] else "classes " + ", ".join(t["classes"]))
            out.append(f"  {t['path']}  {what}" + (f"  (via {t['via'][-1]})" if t["via"] else ""))
        if n < len(tests):
            out.append(f"  … {len(tests) - n} more (`topomark tests-for {b['path']}`)")
    elif b["limited"]:
        out.append("tests: none picked: over 30 callers, too central to pick by name; run the whole suite")
    else:
        out.append("tests: none found" + ("; modules are also loaded by computed names, so some may be missed"
                                          if b["dynamic_loaders"] else ""))
    for c in b["commands"]:
        out += [f"run: {cmd}" for cmd in c["commands"]]
    if b["unmatched"]:
        out.append("no [[tests.runner]] matches " + ", ".join(b["unmatched"][:3]) + " (add one to topomark.toml)")
    if suite:
        out += [f"run the whole suite: {cmd}" for cmd in suite]
    m = b["mentions"]
    if m["count"] and lim["mentions"]:
        out.append(f"docs mentioning ({len(m['files'])}): " + ", ".join(m["files"][:5]) + (" …" if len(m["files"]) > 5 else ""))
    return out


def run(args, ctx) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav, estimate_tokens

    if args.tokens < 1:
        raise TopomarkError("USAGE", "--tokens must be 1 or more")
    nav = Nav(ctx)
    path = rel(ctx, args.target)
    if "#" not in args.target and nav.exists(path):
        b = _file_brief(nav, path)
    elif "/" in args.target and "#" not in args.target:
        raise TopomarkError("NOT_FOUND", f"no such file: {path}")
    else:
        b = _symbol_brief(nav, args.target)
        if b.get("ambiguous"):
            cands = b["candidates"]
            msg = [f"{args.target!r} is declared in {len({c['path'] for c in cands})} files; brief one of them:"]
            msg += [f"  topomark brief {c['path']}#{c['qualname']}" for c in cands]
            return Result({"target": args.target, **b}, "\n".join(msg), 4)
    suite = list(dict.fromkeys(r.suite for r in ctx.config.runners if r.suite)) if b["uncovered"] else []
    lim = {"outline": len(b["outline"]), "callers": TOP, "tests": TOP, "mentions": True}
    trimmed: list[str] = []
    lines = _render(b, lim, suite)
    while estimate_tokens("\n".join(lines)) > args.tokens:
        if lim["outline"] > 0:
            lim["outline"] = max(0, lim["outline"] - max(1, lim["outline"] // 4))
            step = "outline"
        elif lim["mentions"] and b["mentions"]["count"]:
            lim["mentions"], step = False, "mentions"
        elif lim["callers"] > KEEP and len(b["callers"]) > KEEP:
            lim["callers"], step = KEEP, "callers"
        elif lim["tests"] > KEEP and len(b["tests"]) > KEEP:
            lim["tests"], step = KEEP, "tests"
        else:
            break
        if step not in trimmed:
            trimmed.append(step)
        lines = _render(b, lim, suite)
    text = "\n".join(lines)
    shown_callers = b["callers"][:lim["callers"]]
    shown_tests = b["tests"][:lim["tests"]]
    related = ([{"path": c["path"], "role": "caller"} for c in shown_callers]
               + [{"path": t["path"], "role": "test"} for t in shown_tests])
    data = {**b, "outline": b["outline"][:lim["outline"]], "outline_total": len(b["outline"]),
            "callers": shown_callers, "callers_total": len(b["callers"]),
            "tests": shown_tests, "tests_total": len(b["tests"]), "suite_commands": suite,
            "related": related, "budget": args.tokens, "estimated_tokens": estimate_tokens(text), "trimmed": trimmed}
    if not lim["mentions"]:
        data["mentions"] = {"count": b["mentions"]["count"], "files": []}
    return Result(data, text)
