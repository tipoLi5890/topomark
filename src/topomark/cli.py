"""argparse dispatch, global flags and exit codes for the ``topomark`` CLI.

Conventions
-----------
* **stdout = data, stderr = logs.** ``--json`` prints exactly one JSON object on
  stdout, stamped with ``schema_version`` and ``command``; failures under ``--json``
  still print an error envelope on stdout.
* Global flags (``--json -C/--repo --config -q -v --debug``) are accepted before
  or after the subcommand.
* Each command family is one module in ``topomark.commands`` exposing
  ``register(sub, common)``; handlers take ``(args, ctx)`` and return a
  ``Result``. Heavy imports happen inside handlers so ``--help`` stays fast.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn

from . import __version__
from .commands import COMMAND_MODULES, Result, command_module
from .contract import SCHEMA_VERSION
from .errors import EXIT, TopomarkError

_GLOBAL_DEFAULTS = {"repo": None, "config": None, "verbose": 0, "quiet": False, "json": False, "debug": False}
_JSON_REQUESTED = False


def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")


def _discard_stdout() -> None:
    """Point stdout at the null device, so the interpreter's flush at exit does not fail again."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def _error_payload(code: str, message: str, exit_code: int, remediation: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "topomark_version": __version__,
        "error": {"code": code, "message": message, "exit": exit_code, "remediation": remediation},
    }


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors stay machine-readable under ``--json``."""

    def error(self, message: str) -> NoReturn:
        if _JSON_REQUESTED:
            _emit_json(_error_payload("USAGE", f"{self.prog}: {message}", EXIT["USAGE"],
                                      "Run `topomark <command> --help` for the accepted arguments."))
            raise SystemExit(EXIT["USAGE"])
        self.print_usage(sys.stderr)
        self.exit(EXIT["USAGE"], f"{self.prog}: error: {message}\n")


def _global_flags() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", "--repo", metavar="DIR", default=argparse.SUPPRESS,
                        help="run as if started in DIR (like git -C)")
    common.add_argument("--config", metavar="PATH", default=argparse.SUPPRESS,
                        help="path to topomark.toml (default: <repo root>/topomark.toml)")
    common.add_argument("-v", "--verbose", action="count", default=argparse.SUPPRESS,
                        help="more detail on stderr (-v, -vv)")
    common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS,
                        help="suppress non-error logs")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print one machine-readable JSON object on stdout")
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="show full tracebacks for internal errors")
    return common


_VALUE_FLAGS = ("-C", "--repo", "--config")
_BARE_FLAGS = frozenset({"--json", "--debug", "--quiet", "--verbose", "--version"})


def _command_in(argv: list[str]) -> str | None:
    """The command word in ``argv`` when only spelled-out global flags precede it, else None.

    None means "build the whole parser": help before the command, an abbreviated or unknown flag,
    ``--``, or no command at all. A wrong guess here could only cost time, never change parsing,
    because ``build_parser`` falls back to every command when the word is not one it registered."""
    i = 0
    while i < len(argv):
        token = argv[i]
        if not token.startswith("-"):
            return token
        if token in _VALUE_FLAGS:
            i += 2
        elif token in _BARE_FLAGS or token.startswith(("--repo=", "--config=")) or (
                token.startswith("-C") and len(token) > 2) or (token[1:] and set(token[1:]) <= {"v", "q"}):
            i += 1
        else:
            return None
    return None


def build_parser(only: str | None = None) -> argparse.ArgumentParser:
    """The whole parser, or with ``only`` the parser for that one command (same parse, fewer imports)."""
    common = _global_flags()
    parser = _Parser(
        prog="topomark",
        description="A zero-dependency code map for AI coding agents: progressive-disclosure "
                    "docs, per-file review stamps that catch stale summaries, and fast "
                    "symbol / impact / test navigation.",
        epilog=(
            "typical workflow:\n"
            "  topomark init --dry-run              # see what topomark would set up\n"
            "  topomark outline src/big_file.py     # symbols with line ranges\n"
            "  topomark symbol src/big_file.py#Foo  # print just that symbol\n"
            "  topomark impact Foo                  # callers, tests, docs that mention it\n"
            "  topomark tests-for --diff            # the tests your change needs\n"
            "  topomark check                       # code map in sync with the code?\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    module = command_module(only) if only else None
    if module is not None:
        module.register(sub, common)
        if only in sub.choices:
            return parser
        return build_parser()  # the module registers another name: let argparse report all choices
    for module in COMMAND_MODULES():
        module.register(sub, common)
    return parser


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace", newline="\n")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    global _JSON_REQUESTED
    _configure_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    _JSON_REQUESTED = "--json" in argv
    parser = build_parser(_command_in(argv))
    args = parser.parse_args(argv)
    for key, value in _GLOBAL_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    if args.version:
        if args.json:
            _emit_json({"schema_version": SCHEMA_VERSION, "command": "version", "topomark_version": __version__})
        else:
            print(f"topomark {__version__}")
        return EXIT["OK"]
    handler = getattr(args, "handler", None)
    if handler is None:
        if args.json:
            _emit_json(_error_payload("USAGE", "topomark: no command given", EXIT["USAGE"],
                                      "Run `topomark --help` for the commands."))
        else:
            parser.print_help(sys.stderr)
        return EXIT["USAGE"]

    from .context import Context

    try:
        result: Result = handler(args, Context(args))
    except TopomarkError as e:
        if args.json:
            _emit_json(_error_payload(e.code, e.message, e.exit, e.remediation))
        else:
            sys.stderr.write(f"error: {e.code}: {e.message}\nhint: {e.remediation}\n")
        return e.exit
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # the CLI boundary turns bugs into exit 7
        if args.debug:
            raise
        message = f"{type(e).__name__}: {e}"
        if args.json:
            _emit_json(_error_payload("INTERNAL", message, EXIT["INTERNAL"],
                                      "This is a topomark bug. Rerun with --debug and report the traceback."))
        else:
            sys.stderr.write(f"error: INTERNAL: {message}\nhint: rerun with --debug for the traceback\n")
            if args.verbose:
                import traceback  # not at the top: it costs every hook call ~20 ms of imports

                traceback.print_exc()
        return EXIT["INTERNAL"]

    try:
        if args.json:
            _emit_json({"schema_version": SCHEMA_VERSION, "command": args.command, **result.data})
        elif result.text:
            sys.stdout.write(result.text if result.text.endswith("\n") else result.text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:  # the reader left (`| head`): not an error, and nothing more to say
        _discard_stdout()
    return result.exit
