"""``topomark tests-for``: which tests does a change need, and the command to run them."""

from __future__ import annotations

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "tests-for", "the tests that cover changed files, as runnable commands",
            "Changed files (the paths given, else `git diff HEAD` plus untracked files) → the names\n"
            "they declare → test files that mention those names → the test methods whose bodies use\n"
            "them. Changed test files are selected as a whole. Commands come from [[tests.runner]] in\n"
            "topomark.toml ({file} {files} {class} {method} {names}); `names` = file|class|method,\n"
            "above `max_names` it falls back to `fallback`.",
            "examples:\n  topomark tests-for                  # working tree vs HEAD\n"
            "  topomark tests-for --staged\n  topomark tests-for --since main\n  topomark tests-for src/core/router.py")
    p.add_argument("paths", nargs="*", help="files to treat as changed (default: --diff)")
    p.add_argument("--diff", action="store_true", help="working tree vs HEAD, untracked included (default)")
    p.add_argument("--staged", action="store_true", help="only staged changes")
    p.add_argument("--since", metavar="REV", help="changes since REV (working tree vs REV)")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from ..errors import TopomarkError
    from ..navigate import Nav, changed_files, pick_tests, render_runner, runner_for, whole_test_file

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

    picks: dict[str, object] = {}
    names_of: dict[str, list[str]] = {}
    uncovered: list[str] = []
    test_paths = [p for p in nav.infos if nav.is_test(p)]
    for p in present:
        if nav.is_test(p):
            picks[p] = whole_test_file(nav, p, "changed test file")
            continue
        if not nav.is_code(p):
            continue
        names = nav.decl_names(p)
        names_of[p] = names
        covered = False
        if names:
            wanted = set(names)
            for t in test_paths:
                if t == p or not (wanted & nav.infos[t].idents):
                    continue
                pk = pick_tests(nav, t, names)
                if pk is None:
                    continue
                covered = True
                if t in picks:
                    old = picks[t]
                    if not getattr(old, "whole_file", False) and old.reason != "changed test file":
                        for m in pk.methods:
                            if m not in old.methods:
                                old.methods.append(m)
                        old.classes = sorted(set(old.classes) | set(pk.classes))
                        old.names = sorted(set(old.names) | set(pk.names))
                else:
                    picks[t] = pk
        if not covered:
            uncovered.append(p)

    ordered = [picks[k] for k in sorted(picks)]
    groups: dict[int, list] = {}
    unmatched = []
    for pk in ordered:
        r = runner_for(pk.path, ctx.config.runners)
        if r is None:
            unmatched.append(pk)
        else:
            groups.setdefault(ctx.config.runners.index(r), []).append(pk)
    commands = []
    for idx in sorted(groups):
        r = ctx.config.runners[idx]
        cmds, gran = render_runner(r, groups[idx])
        commands.append({"runner": r.match, "names": gran, "files": [pk.path for pk in groups[idx]], "commands": cmds})

    data = {"source": source, "changed": changed, "deleted": gone, "ignored": ignored, "declared": names_of,
            "tests": [pk.to_json() for pk in ordered], "commands": commands,
            "unmatched": [pk.path for pk in unmatched], "uncovered": uncovered}
    lines = [f"changed ({source}): {len(changed)} files" + (f", {len(gone)} deleted" if gone else "")]
    for pk in ordered:
        what = ("whole file" if pk.whole_file else
                (f"{len(pk.methods)} tests: " + ", ".join(f"{c}.{m}" if c else m for c, m in pk.methods[:6])
                 + (" …" if len(pk.methods) > 6 else "")) if pk.methods else "classes " + ", ".join(pk.classes))
        lines.append(f"  {pk.path}  {what}" + (f"  ({pk.reason})" if pk.reason else ""))
    if not ordered:
        lines.append("  no tests mention the changed files' names")
    for c in commands:
        lines.append(f"\nrun ({c['runner']}, by {c['names']}):")
        lines += [f"  {cmd}" for cmd in c["commands"]]
    if unmatched:
        lines.append("\nno [[tests.runner]] matches these test files (add one to topomark.toml):")
        lines += [f"  {pk.path}" for pk in unmatched]
    if uncovered:
        lines.append("\nno test mentions these changed files:")
        lines += [f"  {p}" for p in uncovered]
    return Result(data, "\n".join(lines))
