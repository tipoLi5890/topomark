"""``topomark hook install|uninstall|status``: an opt-in git pre-commit gate.

Installs into ``.git/hooks/pre-commit``. When ``core.hooksPath`` points outside the
repository's .git (a global hooks folder, or one a cloned repository's config names),
install and uninstall are REFUSED rather than writing there. An
existing pre-commit is kept as ``pre-commit.local`` and run first; uninstall
restores it.
"""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context

MARK = "# topomark pre-commit gate"
SCRIPT = """#!/bin/sh
{mark}
# Runs `topomark check` on any commit with staged changes; only findings (exit 1) block it, so a
# broken config or a topomark crash never stops a commit. Skip once: git commit --no-verify
hooks_dir=$(dirname "$0")
if [ -x "$hooks_dir/pre-commit.local" ]; then "$hooks_dir/pre-commit.local" "$@" || exit $?; fi
if ! git diff --cached --name-only --diff-filter=ACMRD | grep -q .; then exit 0; fi
if command -v topomark >/dev/null 2>&1; then TM=topomark; else TM={fallback}; fi
out=$($TM check 2>&1); status=$?
if [ $status -eq 1 ]; then
  echo "$out" | head -40 >&2
  echo "" >&2
  echo "topomark: the code map is out of sync. Fix the rows (topomark diff / stamp), or skip once with --no-verify." >&2
  exit 1
fi
exit 0
"""


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "hook", "install/uninstall an opt-in git pre-commit gate that runs `topomark check`")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.set_defaults(handler=run)


def _hooks_dir(ctx: Context) -> Path:
    from ..repo import git

    rel_path = git(ctx.root, "rev-parse", "--git-path", "hooks").strip()
    d = Path(rel_path)
    return d if d.is_absolute() else ctx.root / d


def _outside_git_dir(ctx: Context, d: Path) -> bool:
    """``--git-path hooks`` follows ``core.hooksPath``: a global setting (one hooks folder for every
    repository) or one from the repository's own config would put the gate, and the renamed
    ``pre-commit.local``, outside this repository's .git."""
    from ..repo import git

    common = Path(git(ctx.root, "rev-parse", "--git-common-dir").strip())
    common = (common if common.is_absolute() else ctx.root / common).resolve()
    return not d.resolve().is_relative_to(common)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError

    d = _hooks_dir(ctx)
    target = d / "pre-commit"
    local = d / "pre-commit.local"
    ours = target.is_file() and MARK in target.read_text(encoding="utf-8", errors="replace")
    if args.action == "status":
        state = "installed" if ours else ("other hook present" if target.exists() else "not installed")
        return Result({"state": state, "path": str(target)}, f"pre-commit: {state} ({target})")
    if _outside_git_dir(ctx, d):
        raise TopomarkError("REFUSED", f"core.hooksPath points outside this repository's .git ({d}); "
                                       "topomark only installs into the repository's own hooks folder. "
                                       "Unset core.hooksPath, or add `topomark check` to that hook by hand")
    if args.action == "install":
        if ours:
            return Result({"state": "installed"}, "pre-commit gate already installed")
        d.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if local.exists():
                raise TopomarkError("REFUSED", f"{local} already exists; resolve it by hand")
            os.replace(target, local)
        bin_path = Path(__file__).resolve().parents[3] / "bin" / "topomark"
        fallback = f"'{bin_path.as_posix()}'" if bin_path.is_file() else "topomark"
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(SCRIPT.format(mark=MARK, fallback=fallback))
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        kept = " (previous hook kept as pre-commit.local)" if local.exists() else ""
        return Result({"state": "installed", "path": str(target)}, f"installed {target}{kept}")
    if not ours:
        return Result({"state": "not installed"}, "no topomark pre-commit gate to remove")
    target.unlink()
    if local.exists():
        os.replace(local, target)
    return Result({"state": "uninstalled"}, "removed the topomark pre-commit gate" +
                  (" and restored the previous hook" if target.exists() else ""))
