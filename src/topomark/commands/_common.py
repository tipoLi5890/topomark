"""Helpers shared by command modules."""

from __future__ import annotations

import argparse
from typing import Any

from ..workspace import Problem


def add(sub: Any, common: argparse.ArgumentParser, name: str, help_text: str, description: str = "",
        epilog: str = "") -> argparse.ArgumentParser:
    p = sub.add_parser(name, parents=[common], help=help_text, description=description or help_text,
                       epilog=epilog or None, formatter_class=argparse.RawDescriptionHelpFormatter)
    return p


def format_problems(problems: list[Problem]) -> str:
    return "\n".join(f"FAIL  {p.code:<15} {p.file}: {p.message}" for p in problems)


def rel(ctx: Any, raw: str) -> str:
    """A user-supplied path → repo-relative POSIX path (accepts absolute, ./x, or repo-relative)."""
    import os
    from pathlib import Path

    p = Path(raw)
    if p.is_absolute() or os.path.exists(raw):
        try:
            return Path(os.path.abspath(raw)).resolve().relative_to(ctx.root.resolve()).as_posix()
        except ValueError:
            return raw.replace("\\", "/")
    return raw.replace("\\", "/").lstrip("./") if raw.startswith("./") else raw.replace("\\", "/")
