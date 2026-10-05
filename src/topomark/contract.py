"""Versioned contracts that other tools and agents depend on.

* ``SCHEMA_VERSION`` stamps every ``--json`` payload. Bump the major part when a
  field is removed or changes meaning; add fields freely.
* ``STAMPS_VERSION`` is the format of ``<docs_dir>/stamps.json``.
* ``estimate_tokens`` is the one token estimate used by ``map --tokens`` and
  reported as ``estimated_tokens``: ASCII costs 1 token per 4 characters, every
  non-ASCII character (CJK comments, emoji) costs 1. It is deliberately simple and
  reproducible, not tied to any tokenizer.
"""

from __future__ import annotations

SCHEMA_VERSION = "topomark/1"
STAMPS_VERSION = 2
CONFIG_FILE = "topomark.toml"
CACHE_DIR = ".topomark"


def estimate_tokens(text: str) -> int:
    ascii_chars = 0
    other = 0
    for ch in text:
        if ord(ch) < 128:
            ascii_chars += 1
        else:
            other += 1
    return (ascii_chars + 3) // 4 + other
