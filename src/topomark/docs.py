"""The code map documents: areas (L1 files), ownership, required files, path refs.

An area file is ``<docs_dir>/<area>.md`` (not ``README.md``, not ``_*.md``) with
YAML-ish frontmatter::

    ---
    area: pad
    title: Pad input layer
    summary: one line
    granularity: file        # or: dir
    depth: 1                 # dir granularity: unit = scope root + N path segments
    scope:
      - Assets/Scripts/Pad/
    ---

Ownership: a file belongs to the area whose ``scope`` entry is the longest
prefix of its path (a scope entry is a directory ending in ``/`` or one file);
two areas claiming the same longest prefix is a conflict.

Units: with ``granularity: file`` every required file is a unit and needs its own
row (full repo path in backticks). With ``dir`` the unit is the file's directory
truncated to ``depth`` segments below the scope root, written ``path/`` in
backticks, optionally followed by a file count ``（N 檔）`` / ``(N files)`` that
``check`` verifies.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .config import Config
from .context import Context
from .repo import matches_any

BACKTICK = re.compile(r"`([^`\n]+)`")


@dataclass
class Area:
    name: str
    file: str
    title: str = ""
    summary: str = ""
    scope: list[str] = field(default_factory=list)
    granularity: str = "file"
    depth: int = 1
    text: str = ""

    def line_count(self) -> int:
        return self.text.count("\n")


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    meta: dict = {}
    key = None
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            meta[key] = [] if val == "" else val
        elif key and re.match(r"^\s+-\s+", line):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(re.sub(r"^\s+-\s+", "", line).strip().strip("`"))
    return meta


def load_areas(ctx: Context) -> list[Area]:
    cfg = ctx.config
    d = ctx.root / cfg.docs_dir
    out: list[Area] = []
    if not d.is_dir():
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md") or name.lower() == "readme.md" or name.startswith("_"):
            continue
        path = f"{cfg.docs_dir}/{name}"
        text = ctx.read(path)
        meta = parse_frontmatter(text) or {}
        scope = meta.get("scope") or []
        if isinstance(scope, str):
            scope = [scope]
        gran = str(meta.get("granularity", "file")).strip() or "file"
        try:
            depth = int(str(meta.get("depth", "1")))
        except ValueError:
            depth = 1
        out.append(Area(name=str(meta.get("area", name[:-3])), file=path, title=str(meta.get("title", "")),
                        summary=str(meta.get("summary", "")), scope=list(scope), granularity=gran,
                        depth=max(1, depth), text=text))
    return out


def owner_of(path: str, areas: list[Area]) -> tuple[Area | None, list[Area]]:
    best: Area | None = None
    best_len = -1
    ties: list[Area] = []
    for a in areas:
        for s in a.scope:
            hit = path == s or (s.endswith("/") and path.startswith(s))
            if not hit:
                continue
            if len(s) > best_len:
                best, best_len, ties = a, len(s), [a]
            elif len(s) == best_len and a is not best and a not in ties:
                ties.append(a)
    return best, ties


def scope_root(path: str, area: Area) -> str:
    best = ""
    for s in area.scope:
        if (path == s or (s.endswith("/") and path.startswith(s))) and len(s) > len(best):
            best = s
    return best


def unit_of(path: str, area: Area) -> str:
    """The thing that needs a row: the file itself, or its directory truncated to ``depth``."""
    if area.granularity != "dir":
        return path
    root = scope_root(path, area)
    if not root.endswith("/"):
        return path
    rel = path[len(root):].split("/")
    dirs = rel[:-1][: area.depth]
    return root + ("/".join(dirs) + "/" if dirs else "")


def is_required(path: str, cfg: Config) -> bool:
    if path.startswith(cfg.docs_prefix):
        return False
    if any(path.startswith(r) for r in cfg.every_file_roots):
        return True
    roots = cfg.required_roots or [""]
    if not any(path.startswith(r) for r in roots):
        return False
    low = path.lower()
    return any(low.endswith(e) for e in cfg.required_ext)


def is_test(path: str, cfg: Config) -> bool:
    return matches_any(path, cfg.test_patterns)


def path_refs(text: str, top_dirs: set[str], top_files: set[str]) -> set[str]:
    out = set()
    for m in BACKTICK.finditer(text):
        s = m.group(1).strip()
        s = re.sub(r":\d+(-\d+)?$", "", s)
        if " " in s:
            continue
        first = s.split("/")[0]
        if "/" in s and first in top_dirs:
            out.add(s)
        elif "/" not in s and s in top_files:
            out.add(s)
    return out


def mentions(text: str, ref: str) -> bool:
    return f"`{ref}`" in text


UNIT_COUNT = re.compile(r"`([^`\n]+/)`\s*[（(]\s*(\d+)\s*(?:檔|files?|个文件|ファイル)")
