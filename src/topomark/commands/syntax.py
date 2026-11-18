"""``topomark syntax [paths | --diff]``: do the edited files still parse? Exit 1 on findings."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add, rel

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "syntax", "check that edited files still parse: Python, JSON, TOML exactly; brackets elsewhere",
            "Python with ast.parse, JSON with json.loads (comments and trailing commas allowed when that is\n"
            "what makes it parse), TOML with tomllib. JS/TS, C#, Java, Kotlin, Swift, Dart, Go, Rust and\n"
            "C-family files get a bracket-balance check on comment- and string-masked text, reported only\n"
            "when the HEAD version was balanced (new files are not bracket-checked). Prints\n"
            "path:line:col: lang: message and exits 1 when anything fails. Default: the files changed\n"
            "vs HEAD, untracked included.",
            "examples:\n  topomark syntax\n  topomark syntax src/app.py web/main.ts\n  topomark syntax --diff --json")
    p.add_argument("paths", nargs="*", help="files to check (default: --diff)")
    p.add_argument("--diff", action="store_true", help="the files changed vs HEAD, untracked included (default)")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from .. import syntax as X
    from ..errors import TopomarkError
    from ..navigate import changed_files
    from ..repo import inside, is_secret, matches_any

    if args.paths:
        paths = list(dict.fromkeys(rel(ctx, p) for p in args.paths))
        if not any(inside(ctx.root, p) and (ctx.root / p).is_file() for p in paths):
            raise TopomarkError("NOT_FOUND", f"no such file: {', '.join(paths)}")
        source = "paths"
    else:
        ex = ctx.config.exclude
        paths = [p for p in changed_files(ctx) if (ctx.root / p).is_file() and not is_secret(p)
                 and not matches_any(p, ex)]
        source = "diff"
    results = X.check_paths(ctx, paths)
    findings = [f for r in results for f in r.findings]
    checked = [r.path for r in results if not r.skipped]
    skipped = [{"path": r.path, "reason": r.skipped} for r in results if r.skipped]
    data = {"source": source, "ok": not findings, "checked": checked, "skipped": skipped,
            "problems": [f.to_json() for f in findings]}
    lines = [f.text() for f in findings]
    bad = len({f.path for f in findings})
    if findings:
        lines.append(f"\nsyntax: {len(findings)} problem{'s' if len(findings) != 1 else ''} in {bad} "
                     f"file{'s' if bad != 1 else ''} ({len(checked)} checked, {len(skipped)} not checkable)")
    elif not paths:
        lines.append("syntax: no changed files")
    else:
        lines.append(f"syntax: ok ({len(checked)} file{'s' if len(checked) != 1 else ''} checked, {len(skipped)} "
                     f"not checkable)")
    return Result(data, "\n".join(lines), 1 if findings else 0)
