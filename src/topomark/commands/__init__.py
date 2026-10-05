"""Command modules. Each exposes ``register(sub, common)`` and a handler
``run(args, ctx) -> Result``. ``COMMAND_MODULES`` is the registry the parser and
``capabilities`` both read, so a command can't exist without being described."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

# Order here is the order in `topomark --help`.
_NAMES = [
    "init", "doctor", "capabilities",
    "gen", "check", "sync", "stamp", "diff", "stale", "owner", "draft", "hook",
    "outline", "symbol", "find", "refs", "impact", "tests_for", "map",
]


@dataclass
class Result:
    """What a handler returns: ``data`` for --json, ``text`` for humans, ``exit`` code."""

    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    exit: int = 0


def COMMAND_MODULES() -> list[ModuleType]:  # noqa: N802 - reads like a constant at call sites
    modules = []
    for name in _NAMES:
        try:
            modules.append(importlib.import_module(f"topomark.commands.{name}"))
        except ModuleNotFoundError as e:
            if e.name != f"topomark.commands.{name}":
                raise
    return modules
