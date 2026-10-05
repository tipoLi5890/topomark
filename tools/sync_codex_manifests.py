#!/usr/bin/env python3
"""Generate the Codex manifests from the Claude ones.

``.claude-plugin/plugin.json`` (with ``marketplace.json``) is the hand-edited
source. This writes:

* ``.codex-plugin/plugin.json``           name, version, description, author,
  links, keywords, ``skills`` and the ``interface`` block Codex shows
* ``.agents/plugins/marketplace.json``    the local marketplace entry

    python3 tools/sync_codex_manifests.py           # regenerate
    python3 tools/sync_codex_manifests.py --check   # exit 1 if the files differ (CI gate)

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_PLUGIN = ".claude-plugin/plugin.json"
CODEX_PLUGIN = ".codex-plugin/plugin.json"
AGENTS_MARKET = ".agents/plugins/marketplace.json"

SHORT = "Navigate any repo by symbol, impact and tests; keep a layered code map honest with review stamps."
LONG = ("Drives the zero-dependency `topomark` CLI: outline a file's symbols, print one symbol, find definitions "
        "and references, summarise the impact of a change, select the tests it needs, and build a ranked repo map "
        "in a token budget. Keeps a progressive-disclosure code map (an L0 index, one file per area, then the code) "
        "in sync with per-unit review stamps that fail `topomark check` when an interface changes without its "
        "summary being reviewed. Bundles one skill, `topomark`.")
PROMPTS = [
    "Orient me in this repo using its code map.",
    "Outline src/app/server.py and show me only the start method.",
    "What breaks if I change the Router class? Which tests should I run?",
    "Set up a topomark code map for this repo; show me the dry run first.",
]


def _load(root: Path, rel: str) -> dict:
    with open(root / rel, encoding="utf-8") as fh:
        return json.load(fh)


def _text(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def generate(root: Path) -> dict[str, str]:
    src = _load(root, CLAUDE_PLUGIN)
    author = {k: v for k, v in src.get("author", {}).items() if k in ("name", "url")}
    codex = {
        "name": src["name"],
        "version": src["version"],
        "description": src["description"],
        "author": author,
        "homepage": src.get("homepage", ""),
        "repository": src.get("repository", ""),
        "license": src.get("license", ""),
        "keywords": src.get("keywords", []),
        "skills": "./skills/",
        "interface": {
            "displayName": src.get("displayName", src["name"]),
            "shortDescription": SHORT,
            "longDescription": LONG,
            "developerName": author.get("name", ""),
            "category": "Developer Tools",
            "capabilities": ["Read", "Write"],
            "websiteURL": src.get("homepage", ""),
            "defaultPrompt": PROMPTS,
        },
    }
    market = {
        "name": src["name"],
        "interface": {"displayName": src.get("displayName", src["name"])},
        "plugins": [{
            "name": src["name"],
            "source": {"source": "local", "path": "./"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }],
    }
    return {CODEX_PLUGIN: _text(codex), AGENTS_MARKET: _text(market)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if a generated file differs")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    drift = []
    for rel, text in generate(root).items():
        path = root / rel
        old = None
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                old = fh.read().replace("\r\n", "\n")
        if old == text:
            continue
        if args.check:
            drift.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"sync_codex_manifests: wrote {rel}")
    if drift:
        print("sync_codex_manifests: out of date (run tools/sync_codex_manifests.py): " + ", ".join(drift),
              file=sys.stderr)
        return 1
    if args.check:
        print("sync_codex_manifests: up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
