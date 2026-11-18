"""Command modules. Each exposes ``register(sub, common)`` and a handler
``run(args, ctx) -> Result``. ``COMMAND_MODULES`` is the registry the parser and
``capabilities`` both read, so a command can't exist without being described."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

# Order here is the order in `topomark --help`.
_NAMES = [
    "init", "doctor", "capabilities",
    "gen", "check", "sync", "stamp", "diff", "stale", "owner", "draft", "hook", "agent_hook",
    "outline", "symbol", "find", "search", "locate", "refs", "impact", "brief", "tests_for", "changes", "syntax", "map",
]


@dataclass
class Result:
    """What a handler returns: ``data`` for --json, ``text`` for humans, ``exit`` code."""

    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    exit: int = 0


def command_module(cli_name: str) -> ModuleType | None:
    """The one module behind a command as typed (``tests-for`` → ``tests_for``), or None.

    Importing all of ``COMMAND_MODULES`` costs every call about 45 ms; a plugin hook runs on every
    Read and Edit, so the CLI loads only the command it was given."""
    name = cli_name.replace("-", "_")
    if "_" in cli_name or name not in _NAMES:
        return None
    import importlib

    return importlib.import_module(f"{__name__}.{name}")


def COMMAND_MODULES() -> list[ModuleType]:  # noqa: N802 - reads like a constant at call sites
    # Written out (not computed from _NAMES) so `impact` and `tests-for` see who loads each command;
    # tests/test_meta.py checks this list against _NAMES. Inside the function: the modules import Result.
    from . import (
        agent_hook, brief, capabilities, changes, check, diff, doctor, draft, find, gen, hook, impact, init, locate,
        map, outline, owner, refs, search, stale, stamp, symbol, sync, syntax, tests_for,
    )

    return [
        init, doctor, capabilities,
        gen, check, sync, stamp, diff, stale, owner, draft, hook, agent_hook,
        outline, symbol, find, search, locate, refs, impact, brief, tests_for, changes, syntax, map,
    ]
