#!/usr/bin/env python3
"""Keep the plugin manifests' version fields in lockstep with ``pyproject.toml``.

``pyproject.toml`` ``[project].version`` is the single source of truth. Three
manifests carry it:

* ``.claude-plugin/plugin.json``      top-level ``"version"``
* ``.claude-plugin/marketplace.json`` ``"version"`` of each entry in ``"plugins"``
* ``.codex-plugin/plugin.json``       top-level ``"version"``

All three are required: a missing manifest is exit 2, never a silent skip. Only
keys that already exist are touched.

    python3 tools/sync_version.py           # rewrite the manifests to match pyproject
    python3 tools/sync_version.py --check   # exit 1 on drift (CI gate)

Stdlib only (``tomllib``, Python >= 3.11).
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json")


def pyproject_version(root: Path) -> str:
    with open(root / "pyproject.toml", "rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(path: Path, doc: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _stamp(doc: dict, version: str) -> bool:
    """Set every declared version to *version*; return True if anything changed."""
    changed = False
    if "version" in doc and doc["version"] != version:
        doc["version"] = version
        changed = True
    for entry in doc.get("plugins", []) or []:
        if isinstance(entry, dict) and "version" in entry and entry["version"] != version:
            entry["version"] = version
            changed = True
    return changed


def sync(root: Path, check: bool) -> tuple[int, list[str]]:
    version = pyproject_version(root)
    messages: list[str] = []
    code = 0
    for rel in TARGETS:
        path = root / rel
        if not path.is_file():
            messages.append(f"sync_version: MISSING required manifest {rel}")
            code = 2
            continue
        doc = _load(path)
        if not _stamp(doc, version):
            continue
        if check:
            messages.append(f"sync_version: DRIFT in {rel} (expected {version})")
            code = max(code, 1)
        else:
            _dump(path, doc)
            messages.append(f"sync_version: updated {rel} -> {version}")
    if not messages:
        messages.append(f"sync_version: all manifests match pyproject ({version})")
    return code, messages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 on drift instead of fixing it")
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this checkout)")
    args = ap.parse_args(argv)
    code, messages = sync(args.root.resolve(), args.check)
    for m in messages:
        print(m, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
