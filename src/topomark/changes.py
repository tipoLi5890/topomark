"""A diff mapped to symbols, for ``topomark changes``.

``git diff -U0`` gives the changed line ranges of each file on both sides. The old side is
analyzed from ``git show REV:path`` with the same language adapter as the new side, and each
changed line is attributed to the innermost declaration around it, on its own side. Then, by
qualified name:

* **interface:** a symbol that is new, gone, or whose signature (with its attributes, kind
  and exportedness) differs between the two sides; a changed header comment counts too;
* **body:** a symbol present on both sides with the same signature whose lines changed.

Renames are a removal plus an addition (``--no-renames``): that is what callers see.
"""

from __future__ import annotations

import codecs
import re
from collections import defaultdict
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileDiff:
    path: str
    status: str                                            # added | deleted | modified
    old: set[int] = field(default_factory=set)             # changed lines on the old side
    new: set[int] = field(default_factory=set)             # changed lines on the new side
    whole: bool = False                                    # untracked: not in the diff at all


def _unquote(p: str) -> str:
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        raw = codecs.escape_decode(p[1:-1].encode("utf-8"))[0]
        return raw.decode("utf-8", errors="replace")
    return p


def _side(p: str) -> str | None:
    """A ``---`` / ``+++`` path without its ``a/`` or ``b/``; None for ``/dev/null``. Git ends an
    unquoted name that holds a space with a tab (a quoted name has its tabs escaped)."""
    if p.startswith('"'):
        return _unquote(p)[2:]
    if p.endswith("\t"):
        p = p[:-1]
    return None if p == "/dev/null" else p[2:]


def _header_path(rest: str) -> str | None:
    """The path in ``diff --git a/P b/P``. Without renames both sides name the same file, quoted
    alike, so the separating space sits in the middle; None when the line is not like that."""
    half = (len(rest) - 1) // 2
    left, right = rest[:half], rest[half + 1:]
    if len(rest) % 2 == 0 or rest[half] != " ":
        return None
    a, b = _unquote(left), _unquote(right)
    if not (a.startswith("a/") and b.startswith("b/") and a[2:] == b[2:]):
        return None
    return a[2:]


def parse_diff(text: str) -> dict[str, FileDiff]:
    """``git diff -U0 --no-renames`` output → path → changed lines per side.

    Each file starts at its ``diff --git`` header, which names it even when no ``---``/``+++``
    lines follow (a mode change, a binary file, an empty file added or deleted); ``new file
    mode`` and ``deleted file mode`` set the status, anything else is ``modified``. After the
    first ``@@`` every line up to the next header is hunk content, so a removed ``-- comment``
    line is never read as a ``---`` header."""
    out: dict[str, FileDiff] = {}
    old_path: str | None = None
    cur: FileDiff | None = None
    in_hunks = False
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            path = _header_path(line[len("diff --git "):])
            cur = out.setdefault(path, FileDiff(path, "modified")) if path else None
            old_path, in_hunks = None, False
        elif line.startswith("@@"):
            in_hunks = True
            m = _HUNK.match(line)
            if cur is None or not m:
                continue
            a, b = int(m[1]), int(m[2]) if m[2] is not None else 1
            c, d = int(m[3]), int(m[4]) if m[4] is not None else 1
            cur.old.update(range(a, a + b))
            cur.new.update(range(c, c + d))
        elif in_hunks:
            continue
        elif line.startswith("new file mode") and cur is not None:
            cur.status = "added"
        elif line.startswith("deleted file mode") and cur is not None:
            cur.status = "deleted"
        elif line.startswith("--- "):
            old_path = _side(line[4:])
        elif line.startswith("+++ "):
            new_path = _side(line[4:])
            path = new_path or old_path
            if path and (cur is None or cur.path != path):  # a header we could not read
                status = "added" if old_path is None else "deleted" if new_path is None else "modified"
                cur = out.setdefault(path, FileDiff(path, status))
    return out


def _key(s) -> tuple:
    return (s.kind, " ".join(s.signature.split()), tuple(s.attrs), bool(s.exported))


def _by_qualname(info) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    if info is not None:
        for s in info.symbols:
            if s.kind != "namespace":
                out[s.qualname].append(s)
    return out


def _touched(info, lines: set[int], text: list[str] | None) -> set[str]:
    """Qualified names of the innermost declarations around ``lines`` ("" = outside any).
    Blank lines don't count: adding a method brings a blank line that belongs to no one."""
    from .navigate import enclosing_symbol

    out: set[str] = set()
    if info is None:
        return out
    for n in lines:
        if text is not None and (n > len(text) or not text[n - 1].strip()):
            continue
        s = enclosing_symbol(info, n)
        out.add(s.qualname if s is not None else "")
    return out


def classify(old_info, new_info, diff: FileDiff, old_text: list[str] | None = None,
             new_text: list[str] | None = None) -> tuple[list[dict], bool, bool]:
    """(changed symbols, header changed, lines outside any declaration changed) for one file.
    Symbols come in new-file order, removed ones after, each ``{"qualname", "kind", "change",
    "signature", "old_signature", "start", "end", "exported"}`` with ``change`` in
    added | removed | signature | body."""
    old, new = _by_qualname(old_info), _by_qualname(new_info)
    touched = _touched(old_info, diff.old, old_text) | _touched(new_info, diff.new, new_text)
    out: list[dict] = []
    for q, syms in new.items():
        s = syms[0]
        item = {"qualname": q, "kind": s.kind, "signature": s.signature, "old_signature": None, "start": s.start,
                "end": s.end, "exported": bool(s.exported)}
        if q not in old:
            out.append({**item, "change": "added"})
        elif sorted(map(_key, syms)) != sorted(map(_key, old[q])):
            out.append({**item, "change": "signature", "old_signature": old[q][0].signature})
        elif q in touched:
            out.append({**item, "change": "body"})
    for q, syms in old.items():
        if q not in new:
            s = syms[0]
            out.append({"qualname": q, "kind": s.kind, "signature": None, "old_signature": s.signature,
                        "start": s.start, "end": s.end, "exported": bool(s.exported), "change": "removed"})
    header = bool(old_info is not None and new_info is not None and
                  [h.strip() for h in old_info.header] != [h.strip() for h in new_info.header])
    return out, header, "" in touched


INTERFACE = ("added", "removed", "signature")
