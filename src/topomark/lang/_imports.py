"""Import specifiers of the brace languages whose imports name repo files (``FileInfo.imports``).

Each function finds its keyword in the masked text (so a commented-out import is not one) and
reads the specifier from the original at the same offset, where string literals still stand.
What a specifier resolves to is ``topomark.imports``' business; these only say what was written:

* C, C++, Objective-C: ``#include "x.h"`` and ``#import "x.h"`` as written. ``<x.h>`` is a system
  or dependency header and is left out. Read from the original text (the adapter blanks
  preprocessor lines), so only a directive at the start of a line counts; one inside a block
  comment that starts its own line would too.
* Dart: ``import``, ``export`` and ``part`` URIs (``part of`` names the owner, not a file).
* Go: every path in ``import "x"`` and ``import ( ... )``.
* Rust: ``mod name;`` as ``mod:name`` and the ``crate::`` / ``super::`` / ``self::`` paths of ``use``.
* Java and Kotlin: ``import a.b.C`` and ``import a.b.*`` (``static`` dropped).
"""

from __future__ import annotations

import re

_C_AT = re.compile(r"^[ \t]*#[ \t]*(?:include|import)\b", re.M)
_C_QUOTED = re.compile(r'[ \t]*"([^"\n]+)"')
_DART_AT = re.compile(r"^[ \t]*(?:import|export|part)\b(?![ \t]+of\b)", re.M)
_QUOTED = re.compile(r"""\s*(['"])([^'"\n]+)\1""")
_GO_AT = re.compile(r"^import\b(?:[ \t]*(\())?", re.M)
_GO_STRING = re.compile(r'"([^"\n]+)"|`([^`\n]+)`')
_RUST_MOD = re.compile(r"^[ \t]*(?:pub(?:\([^)\n]*\))?[ \t]+)?mod[ \t]+(\w+)[ \t]*;", re.M)
_RUST_USE = re.compile(r"\buse[ \t]+((?:crate|super|self)(?:::\w+)+)")
_JVM = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?([A-Za-z_][\w.]*?)(\.\*)?[ \t]*(?:;|$|[ \t]as\b)", re.M)


def _add(out: list[str], spec: str) -> None:
    if spec and spec not in out:
        out.append(spec)


def c_includes(masked: str, original: str) -> list[str]:
    out: list[str] = []
    for hit in _C_AT.finditer(masked):
        lit = _C_QUOTED.match(original, hit.end())
        if lit:
            _add(out, lit.group(1))
    return out


def dart_imports(masked: str, original: str) -> list[str]:
    out: list[str] = []
    for hit in _DART_AT.finditer(masked):
        lit = _QUOTED.match(original, hit.end())
        if lit:
            _add(out, lit.group(2))
    return out


def go_imports(masked: str, original: str) -> list[str]:
    out: list[str] = []
    for hit in _GO_AT.finditer(masked):
        if hit.group(1):
            end = masked.find(")", hit.end())
            end = len(masked) if end < 0 else end
        else:
            end = masked.find("\n", hit.end())
            end = len(masked) if end < 0 else end
        for lit in _GO_STRING.finditer(original, hit.end(), end):
            _add(out, lit.group(1) or lit.group(2))
    return out


def rust_imports(masked: str, original: str) -> list[str]:
    out: list[str] = []
    for hit in _RUST_MOD.finditer(masked):
        _add(out, "mod:" + hit.group(1))
    for hit in _RUST_USE.finditer(masked):
        _add(out, hit.group(1))
    return out


def jvm_imports(masked: str, original: str) -> list[str]:
    out: list[str] = []
    for hit in _JVM.finditer(masked):
        _add(out, hit.group(1) + (".*" if hit.group(2) else ""))
    return out
