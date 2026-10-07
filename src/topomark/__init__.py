"""topomark: a zero-dependency code map for AI coding agents.

The distribution, the import package and the CLI command are all ``topomark``.
``__version__`` prefers the sibling ``pyproject.toml`` when running from a source
checkout (``bin/topomark`` / ``PYTHONPATH=src``) so a stale installed copy can't
misreport, and falls back to the installed metadata.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def _version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        try:
            with pyproject.open("rb") as fh:
                return str(tomllib.load(fh)["project"]["version"])
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            pass
    from importlib import metadata  # slow to import (zipfile, email): only on this fallback path

    try:
        return metadata.version("topomark")
    except metadata.PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _version()
