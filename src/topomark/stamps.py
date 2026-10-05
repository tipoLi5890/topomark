"""Review stamps: ``<docs_dir>/stamps.json``.

A stamp records, for each unit (a file, or a directory with ``granularity: dir``),
the SHA-256 of its *surface* at the moment someone reviewed its row, plus the git
blob ids of the file contents (so ``diff`` can show what changed since). Each area
also stamps the set of its files' cross-area callers ("edges").

``check`` fails when a unit's surface changed since its stamp, a required unit
has no stamp, a stamp's unit no longer exists, or an area's edges changed.
Only ``topomark stamp`` writes stamps; it is a statement that a human or an agent
looked at the row.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import STAMPS_VERSION
from .repo import git, write_text


def h16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def unit_surface_hash(file_hashes: dict[str, str]) -> str:
    """One file → its own hash. A directory unit → hash of ``path:hash`` lines."""
    if len(file_hashes) == 1:
        return next(iter(file_hashes.values()))
    return h16("\n".join(f"{p}:{h}" for p, h in sorted(file_hashes.items())))


def blob_ids(root: Path, paths: list[str]) -> dict[str, str]:
    """git object ids; ``-w`` stores the content so ``diff`` can show it later
    (unreferenced objects may be pruned by gc after ~2 weeks; hashes still work)."""
    if not paths:
        return {}
    out = git(root, "hash-object", "-w", "--stdin-paths", input_text="\n".join(paths) + "\n").split()
    return dict(zip(paths, out))


class Stamps:
    def __init__(self, path: str, root: Path) -> None:
        self.path = path
        self.root = root
        self.version = STAMPS_VERSION
        self.units: dict[str, dict] = {}
        self.areas: dict[str, dict] = {}
        self.foreign_version: int | None = None
        full = root / path
        if full.is_file():
            with open(full, encoding="utf-8") as fh:
                data = json.load(fh)
            v = data.get("version")
            if v == STAMPS_VERSION:
                self.units = data.get("units", {})
                self.areas = data.get("areas", {})
            else:
                self.foreign_version = v

    def save(self) -> None:
        lines = ["{", f' "version": {STAMPS_VERSION},', ' "areas": {']
        ar = sorted(self.areas.items())
        for i, (k, v) in enumerate(ar):
            lines.append(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, sort_keys=True)}"
                         + ("," if i < len(ar) - 1 else ""))
        lines += [" },", ' "units": {']
        us = sorted(self.units.items())
        for i, (k, v) in enumerate(us):
            lines.append(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}"
                         + ("," if i < len(us) - 1 else ""))
        lines += [" }", "}"]
        write_text(self.root, self.path, "\n".join(lines) + "\n")
