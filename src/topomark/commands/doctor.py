"""``topomark doctor``: environment and repo health, offline. Exit 1 if a check fails."""

from __future__ import annotations

import shutil
import sys

from . import Result
from ._common import add


def register(sub, common) -> None:
    p = add(sub, common, "doctor", "check Python, git, the config, tracked secrets and the cache")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from .. import __version__
    from ..errors import TopomarkError
    from ..index import cache_dir
    from ..repo import is_secret

    checks = []

    def add_check(name: str, ok: bool, detail: str, hint: str = "", warn: bool = False) -> None:
        status = "ok" if ok else ("warn" if warn else "fail")
        checks.append({"name": name, "ok": ok or warn, "status": status, "detail": detail,
                       **({"hint": hint} if hint and not ok else {})})

    add_check("python", sys.version_info >= (3, 11), sys.version.split()[0], "topomark needs Python >= 3.11")
    add_check("git", shutil.which("git") is not None, shutil.which("git") or "not found", "install git")
    root = None
    try:
        root = ctx.root
        add_check("repo", True, str(root))
    except TopomarkError as e:
        add_check("repo", False, e.message, "run inside a git work tree or pass -C <dir>")
    if root is not None:
        try:
            cfg = ctx.config
            add_check("config", True, str(cfg.path) if cfg.path else "no topomark.toml (defaults)")
            secrets = [f for f in ctx.all_files if is_secret(f)]
            tracked = set()
            if secrets:
                from ..repo import git
                tracked = set(git(root, "ls-files", "-z", "--", *secrets).split("\0")) - {""}
            add_check("secrets", not tracked,
                      f"{len(secrets)} secret-looking file(s) visible, {len(tracked)} tracked by git"
                      + (": " + ", ".join(sorted(tracked)[:5]) if tracked else ""),
                      "these are never read by topomark, but git tracks them; consider removing them from the repo",
                      warn=True)
            add_check("docs_dir", True, f"{cfg.docs_dir} ({'exists' if (root / cfg.docs_dir).is_dir() else 'not created yet'})")
            add_check("files", True, f"{len(ctx.files)} files after excludes ({len(ctx.all_files)} visible to git)")
            add_check("cache", True, str(cache_dir(root)))
        except TopomarkError as e:
            add_check("config", False, e.message, e.remediation)
    ok = all(c["ok"] for c in checks)
    lines = [f"topomark {__version__}"]
    for c in checks:
        lines.append(f"  {c['status'].upper():<4} {c['name']:<9} {c['detail']}" +
                     (f"\n       hint: {c['hint']}" if c.get("hint") else ""))
    return Result({"ok": ok, "version": __version__, "checks": checks}, "\n".join(lines), 0 if ok else 1)
