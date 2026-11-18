"""``topomark capabilities``: describe every command and flag from the live parser."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "capabilities", "describe every command, argument and flag (use --json)")
    p.set_defaults(handler=run)


def describe(parser: argparse.ArgumentParser) -> dict:
    commands = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {a.dest: a.help for a in action._choices_actions}
            for name, sp in action.choices.items():
                args = []
                for a in sp._actions:
                    if isinstance(a, argparse._HelpAction):
                        continue
                    if a.dest in ("repo", "config", "verbose", "quiet", "json", "debug"):
                        continue
                    args.append({"name": a.option_strings or [a.dest], "help": a.help,
                                 "required": bool(a.required) if a.option_strings else a.nargs not in ("?", "*"),
                                 **({"choices": list(a.choices)} if a.choices else {})})
                commands[name] = {"help": helps.get(name, ""), "arguments": args}
    return commands


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from .. import __version__
    from ..cli import build_parser
    from ..errors import EXIT

    cmds = describe(build_parser())
    text = "\n".join(f"{n:<14} {c['help']}" for n, c in cmds.items())
    return Result({"version": __version__, "commands": cmds, "exit_codes": EXIT,
                   "global_flags": ["--json", "-C/--repo", "--config", "-v", "-q", "--debug"]}, text)
