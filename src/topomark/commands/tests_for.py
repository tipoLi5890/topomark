"""``topomark tests-for``: which tests does a change need, and the command to run them."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add, rel

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "tests-for", "the tests that cover changed files, as runnable commands",
            "Changed files (the paths given, else `git diff HEAD` plus untracked files) → the names\n"
            "they declare → test files that mention those names → the test methods whose bodies use\n"
            "them. Changed test files are selected as a whole. A file no test mentions is followed to\n"
            "its callers, up to --depth hops (import statements, transitively; name references, one\n"
            "hop), and their tests are selected `via` them; more than 30 callers, or nothing found,\n"
            "points to the runner's `suite` command. Commands come from [[tests.runner]] in\n"
            "topomark.toml ({file} {files} {class} {method} {names}); `names` = file|class|method,\n"
            "above `max_names` it falls back to `fallback`.",
            "examples:\n  topomark tests-for                  # working tree vs HEAD\n"
            "  topomark tests-for --staged\n  topomark tests-for --since main\n  topomark tests-for src/core/router.py\n"
            "  topomark tests-for src/core/util.py --depth 3")
    p.add_argument("paths", nargs="*", help="files to treat as changed (default: --diff)")
    p.add_argument("--diff", action="store_true", help="working tree vs HEAD, untracked included (default)")
    p.add_argument("--staged", action="store_true", help="only staged changes")
    p.add_argument("--since", metavar="REV", help="changes since REV (working tree vs REV)")
    p.add_argument("--depth", type=int, default=2, metavar="N",
                   help="caller hops to follow for files no test mentions (default 2; 0 = names only)")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav, changed_files
    from ..runners import runner_commands
    from ..testsel import MAX_CALLERS, select_tests

    if args.depth < 0:
        raise TopomarkError("USAGE", "--depth must be 0 or more")
    nav = Nav(ctx)
    if args.paths:
        changed = [rel(ctx, p) for p in args.paths]
        missing = [p for p in changed if not nav.exists(p)]
        if missing and len(missing) == len(changed):
            raise TopomarkError("NOT_FOUND", f"no such file: {', '.join(missing)}")
        source = "paths"
    else:
        changed = changed_files(ctx, staged=args.staged, since=args.since)
        source = "staged" if args.staged else (f"since {args.since}" if args.since else "diff")
    gone = [p for p in changed if not nav.exists(p)]
    present = [p for p in changed if nav.exists(p) and p in nav.infos]
    ignored = [p for p in changed if nav.exists(p) and p not in nav.infos]

    sel = select_tests(nav, present, args.depth)
    ordered = sel.ordered()
    runners = ctx.config.runners
    commands, unmatched = runner_commands(runners, ordered)
    suite = list(dict.fromkeys(r.suite for r in runners if r.suite)) if sel.uncovered else []

    data = {"source": source, "changed": changed, "deleted": gone, "ignored": ignored, "declared": sel.names_of,
            "depth": sel.depth, "tests": [pk.to_json() for pk in ordered], "commands": commands,
            "unmatched": [pk.path for pk in unmatched], "uncovered": sel.uncovered, "limited": sel.limited,
            "dynamic_loaders": sel.dynamic_loaders, "suite_commands": suite}
    lines = [f"changed ({source}): {len(changed)} files" + (f", {len(gone)} deleted" if gone else "")]
    for pk in ordered:
        what = ("whole file" if pk.whole_file else
                (f"{len(pk.methods)} tests: " + ", ".join(f"{c}.{m}" if c else m for c, m in pk.methods[:6])
                 + (" …" if len(pk.methods) > 6 else "")) if pk.methods else "classes " + ", ".join(pk.classes))
        lines.append(f"  {pk.path}  {what}" + (f"  ({pk.reason})" if pk.reason else ""))
    if not ordered:
        lines.append("  no tests mention the changed files' names")
    for c in commands:
        lines.append(f"\nrun ({c['runner']}, by {c['names']}; command from {c['source']}):")
        lines += [f"  {cmd}" for cmd in c["commands"]]
    if unmatched:
        lines.append("\nno [[tests.runner]] matches these test files (add one to topomark.toml):")
        lines += [f"  {pk.path}" for pk in unmatched]
    if sel.uncovered:
        hops = f", nor their callers within {sel.depth} hop{'s' if sel.depth > 1 else ''}" if sel.depth else ""
        lines.append(f"\nno test mentions these changed files{hops}:")
        lines += [f"  {p}" + (f"  (over {MAX_CALLERS} callers: too central to pick by name)" if p in sel.limited else "")
                  for p in sel.uncovered]
        if sel.dynamic_loaders:
            shown = ", ".join(sel.dynamic_loaders[:5]) + (" …" if len(sel.dynamic_loaders) > 5 else "")
            lines.append(f"may miss tests: modules are also loaded by computed names in {shown}")
        if suite:
            lines.append("run the whole suite:")
            lines += [f"  {cmd}" for cmd in suite]
        elif runners:
            lines.append("run the whole suite (add `suite = \"...\"` to a [[tests.runner]] to print it here)")
    return Result(data, "\n".join(lines))
