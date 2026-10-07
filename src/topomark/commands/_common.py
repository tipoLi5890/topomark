"""Helpers shared by command modules."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # importing workspace pulls in the index and hashlib: too slow for --help and hooks
    from ..workspace import Problem


def add(sub: Any, common: argparse.ArgumentParser, name: str, help_text: str, description: str = "",
        epilog: str = "") -> argparse.ArgumentParser:
    p = sub.add_parser(name, parents=[common], help=help_text, description=description or help_text,
                       epilog=epilog or None, formatter_class=argparse.RawDescriptionHelpFormatter)
    return p


def format_problems(problems: list[Problem]) -> str:
    return "\n".join(f"FAIL  {p.code:<15} {p.file}: {p.message}" for p in problems)


def rel(ctx: Any, raw: str) -> str:
    """A user-supplied path → repo-relative POSIX path.

    An absolute path, or a relative one that exists from the current directory, is resolved
    and must lie inside the repository. Any other relative path is taken as repo-relative
    (what ``-C`` callers mean): ``./`` prefixes and ``a/../b`` are normalised, a trailing ``/``
    is kept. A path that leads out of the repository is NOT_FOUND."""
    import os
    import posixpath
    from pathlib import Path

    from ..errors import TopomarkError

    def outside() -> TopomarkError:
        return TopomarkError("NOT_FOUND", f"{raw} is outside the repository ({ctx.root})")

    p = Path(raw)
    if p.is_absolute() or os.path.exists(raw):
        try:
            return Path(os.path.abspath(raw)).resolve().relative_to(ctx.root.resolve()).as_posix()
        except ValueError:
            if p.is_absolute():
                raise outside() from None
            # outside when read from the current directory: maybe repo-relative (with -C)
    s = raw.replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s:
        return s
    norm = posixpath.normpath(s)
    if norm == ".." or norm.startswith(("../", "/")):
        raise outside()
    return norm + "/" if s.endswith("/") and norm != "." else norm
