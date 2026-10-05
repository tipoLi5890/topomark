"""Per-file analysis with an on-disk cache outside the repo.

The cache lives in the user's cache directory (``$TOPOMARK_CACHE``, else
``$XDG_CACHE_HOME/topomark``, else ``~/.cache/topomark``), one folder per repo
root, so topomark never writes into the repositories it maps. Entries are keyed
by ``(mtime_ns, size)`` and the whole cache is dropped when the adapters change
(a fingerprint of ``topomark/lang/*.py``) or topomark's version changes.

Files larger than ``MAX_BYTES`` are listed but not parsed (no symbols); their
surface is the SHA-256 of their content so stamps still notice changes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import __version__
from .lang import registry
from .lang.base import FileInfo

MAX_BYTES = 3 * 1024 * 1024
CACHE_FORMAT = 1


def _fingerprint() -> str:
    h = hashlib.sha256(f"{CACHE_FORMAT}:{__version__}".encode())
    lang_dir = Path(__file__).parent / "lang"
    for p in sorted(lang_dir.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def cache_dir(root: Path) -> Path:
    base = os.environ.get("TOPOMARK_CACHE")
    if base:
        d = Path(base)
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        d = Path(xdg) / "topomark" if xdg else Path.home() / ".cache" / "topomark"
    return d / hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


class Index:
    def __init__(self, ctx, use_cache: bool = True) -> None:
        self.ctx = ctx
        self.root: Path = ctx.root
        self._infos: dict[str, FileInfo] = {}
        self._cache_path = cache_dir(self.root) / "index.json"
        self._fp = _fingerprint()
        self._cache: dict = {}
        self._dirty = False
        if use_cache:
            self._load()

    def _load(self) -> None:
        try:
            with open(self._cache_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("fingerprint") == self._fp:
                self._cache = data.get("files", {})
        except (OSError, ValueError):
            self._cache = {}

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump({"fingerprint": self._fp, "root": str(self.root), "files": self._cache}, fh,
                          ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self._cache_path)
            self._dirty = False
        except OSError:
            pass  # a read-only home must not break the tool

    def info(self, path: str) -> FileInfo:
        if path in self._infos:
            return self._infos[path]
        full = self.root / path
        st = full.stat()
        key = [st.st_mtime_ns, st.st_size]
        hit = self._cache.get(path)
        if hit and hit.get("key") == key:
            info = FileInfo.from_json(hit["info"], hit["idents"], hit["surface"])
        else:
            if st.st_size > MAX_BYTES:
                info = FileInfo(path=path, lang="large", line_count=0,
                                surface="sha256:" + hashlib.sha256(full.read_bytes()).hexdigest())
            else:
                info = registry.analyze(path, self.ctx.read(path))
            self._cache[path] = {"key": key, "info": info.to_json(), "idents": sorted(info.idents),
                                 "surface": info.surface}
            self._dirty = True
        self._infos[path] = info
        return info

    def all(self, paths: list[str] | None = None) -> dict[str, FileInfo]:
        full_scan = paths is None
        out = {}
        for p in paths if paths is not None else self.ctx.code_files:
            try:
                out[p] = self.info(p)
            except OSError:
                continue
        if full_scan:
            stale = set(self._cache) - set(out)
            for p in stale:
                del self._cache[p]
            self._dirty = self._dirty or bool(stale)
        self.save()
        return out
