"""Comments and strings blanked, per file, with the file's own adapter syntax.

A leaf: it needs the language adapters and nothing else, so the code that runs on every
edit (``syntax.check_file`` from the post-edit hook) can mask a file without loading the
index, the workspace or the reference graph.
"""

from __future__ import annotations

import re

from .lang.scan import Masked, mask

# Languages whose text is prose or data: never masked, never a reference site, ranked after code.
# The data adapter is named "data"; the files it parses report json, toml or yaml.
NON_CODE_LANGS = frozenset({"markdown", "data", "json", "toml", "yaml", "text", "large"})


def word_rx(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(name) + r"(?![A-Za-z0-9_$])")


def mask_file(path: str, text: str) -> Masked:
    """``text`` with comments and strings blanked by the adapter for ``path`` (offsets kept);
    prose and data files come back unmasked. ``original`` is ``text``."""
    from .lang import registry
    from .lang.python import SYNTAX as PY_SYNTAX

    adapter = registry.adapter_for(path)
    if getattr(adapter, "name", "") in NON_CODE_LANGS:
        return Masked(text, text)
    syntax = getattr(adapter, "syntax", None) or PY_SYNTAX
    premask = getattr(adapter, "premask", None)
    m = mask(premask(text) if callable(premask) else text, syntax)
    m.original = text
    return m
