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
    """A user-supplied path → repo-relative POSIX path (``repo.user_path``)."""
    from ..repo import user_path

    return user_path(ctx.root, raw)
