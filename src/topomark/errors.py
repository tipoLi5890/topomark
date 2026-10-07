"""Exit-code table, error-code registry and the single ``TopomarkError`` exception.

Exit codes are part of the public contract (agents and hooks branch on them):

    0 OK          the command ran and found nothing to report
    1 FINDINGS    check/stale/doctor/syntax found problems (not an error: the tool worked)
    2 USAGE       bad flags or arguments
    3 CONFIG      topomark.toml is missing a required field or is malformed
    4 NOT_FOUND   a path, symbol or area does not exist
    5 UNSUPPORTED the file's language has no adapter for this operation
    6 NOT_GIT     the target directory is not inside a git work tree
    7 INTERNAL    a bug; rerun with --debug for the traceback
"""

from __future__ import annotations

from typing import NoReturn

EXIT: dict[str, int] = {
    "OK": 0,
    "FINDINGS": 1,
    "USAGE": 2,
    "CONFIG": 3,
    "NOT_FOUND": 4,
    "UNSUPPORTED": 5,
    "NOT_GIT": 6,
    "INTERNAL": 7,
}

ERROR_CODES: frozenset[str] = frozenset(
    {"USAGE", "CONFIG", "NOT_FOUND", "UNSUPPORTED", "NOT_GIT", "INTERNAL", "REFUSED"}
)

_CODE_EXIT: dict[str, str] = {
    "USAGE": "USAGE",
    "CONFIG": "CONFIG",
    "NOT_FOUND": "NOT_FOUND",
    "UNSUPPORTED": "UNSUPPORTED",
    "NOT_GIT": "NOT_GIT",
    "INTERNAL": "INTERNAL",
    "REFUSED": "USAGE",
}

REMEDIATION: dict[str, str] = {
    "USAGE": "Run `topomark <command> --help` for the accepted arguments.",
    "CONFIG": "Fix topomark.toml (see `topomark init --dry-run` for a valid starting point).",
    "NOT_FOUND": "Check the spelling; `topomark find <Name>` lists definitions, `topomark owner <path>` checks paths.",
    "UNSUPPORTED": "This file type has no language adapter; topomark falls back to plain text where it can.",
    "NOT_GIT": "Run inside a git work tree, or pass -C <repo>.",
    "INTERNAL": "This is a topomark bug. Rerun with --debug and report the traceback.",
    "REFUSED": "topomark refused an action that would lose information; read the message for the explicit flag.",
}


class TopomarkError(Exception):
    """The one exception type the CLI turns into an exit code and a message."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def exit(self) -> int:
        return EXIT[_CODE_EXIT[self.code]]

    @property
    def remediation(self) -> str:
        return REMEDIATION[self.code]


def fail(code: str, message: str) -> NoReturn:
    raise TopomarkError(code, message)
