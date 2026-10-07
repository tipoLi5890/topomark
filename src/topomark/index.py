"""Per-file analysis with an on-disk cache outside the repo.

The cache lives in the user's cache directory (``$TOPOMARK_CACHE``, else
``$XDG_CACHE_HOME/topomark``, else ``~/.cache/topomark``), one folder per repo
root, so topomark never writes into the repositories it maps. Entries are keyed
by ``(mtime_ns, size)`` and spread over ``SHARDS`` ``marshal`` files by a hash of
the path: a single-file command (``outline``, ``symbol file#Name``) reads one small
shard whatever the size of the repo, and a save rewrites only the shards that
changed. The shard folder is named after a fingerprint of the adapters
(``topomark/lang/*.py``), topomark's version, the cache format and the Python
version (marshal's format is Python's own), so a change to any of them starts a
fresh cache; older folders are deleted.

``Index.derived`` stores data computed from every file at once (the reference
graph's tables, import edges, identifier counts, the search index) under a digest of
all ``(path, key)`` pairs plus a fingerprint of the modules that build them
(``DERIVED_MODULES``), so a warm run with no file changed skips that work too, and an
edit to that code never serves tables the old code built. ``graph.partial_names`` is
packed into each file's entry instead: a change to it needs a ``CACHE_FORMAT`` bump.

Files larger than ``MAX_BYTES`` are listed but not parsed (no symbols); their
surface is the SHA-256 of their content so stamps still notice changes.
"""

from __future__ import annotations

import hashlib
import marshal
import os
import shutil
import sys
import zlib
from pathlib import Path
from typing import Any, Callable

from . import __version__, repo
from .errors import TopomarkError
from .lang import registry
from .lang.base import FileInfo, Symbol

MAX_BYTES = 3 * 1024 * 1024
CACHE_FORMAT = 2
SHARDS = 256
DERIVED_MODULES = ("graph.py", "navigate.py", "search.py")  # what builds the tables Index.derived keeps


def _fingerprint() -> str:
    h = hashlib.sha256(f"{CACHE_FORMAT}:{__version__}:{sys.version_info[:2]}:{marshal.version}".encode())
    lang_dir = Path(__file__).parent / "lang"
    for p in sorted(lang_dir.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


_DERIVED_FP: list[str] = []


def _derived_fingerprint() -> str:
    """A digest of the code that builds derived tables (read once per process); without the
    sources (a bytecode-only install) the version stands in for them."""
    if not _DERIVED_FP:
        h = hashlib.sha256()
        here = Path(__file__).parent
        for name in DERIVED_MODULES:
            try:
                h.update(name.encode() + b"\0" + (here / name).read_bytes())
            except OSError:
                h.update(f"{name}\0{__version__}".encode())
        _DERIVED_FP.append(h.hexdigest()[:16])
    return _DERIVED_FP[0]


def cache_dir(root: Path) -> Path:
    base = os.environ.get("TOPOMARK_CACHE")
    if base:
        d = Path(base)
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        d = Path(xdg) / "topomark" if xdg else Path.home() / ".cache" / "topomark"
    return d / hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def shard_of(path: str) -> int:
    return zlib.crc32(path.encode("utf-8")) % SHARDS


_SYMBOL_FIELDS = ("kind", "name", "qualname", "start", "end", "signature", "exported", "container", "attrs", "doc",
                  "line")


def _pack(info: FileInfo) -> tuple:
    from .graph import partial_names

    syms = [tuple(getattr(s, f) for f in _SYMBOL_FIELDS) for s in info.symbols]
    return (info.lang, info.line_count, info.header, marshal.dumps(syms), info.types, info.imports,
            " ".join(sorted(info.idents)), info.surface, partial_names(info))


def _symbol(t: tuple) -> Symbol:
    s = object.__new__(Symbol)
    s.__dict__.update(zip(_SYMBOL_FIELDS, t))
    return s


class CachedInfo(FileInfo):
    """A ``FileInfo`` read back from the cache. Symbols and identifiers are decoded on
    first use: whole-repo commands read every file's types and imports but only some
    files' symbols, and loading 50,000 symbols costs more than everything else."""

    def __init__(self, path: str, packed: tuple) -> None:  # not the dataclass __init__: fields are set here
        lang, line_count, header, blob, types, imports, idents, surface, partial = packed
        self.path, self.lang, self.header, self.surface = path, lang, header, surface
        self.partial_names: list[str] = partial
        self.types, self.line_count, self.imports = types, line_count, imports
        self._blob: bytes = blob
        self._tuples: list[tuple] | None = None
        self._symbols: list[Symbol] | None = None
        self._ident_text: str = idents
        self._idents: set[str] | None = None

    @property
    def symbol_tuples(self) -> list[tuple]:
        """The symbols as raw field tuples (``kind`` first), cheaper than ``Symbol`` objects."""
        if self._tuples is None:
            self._tuples = marshal.loads(self._blob)
        return self._tuples

    @property  # type: ignore[override]
    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            self._symbols = [_symbol(t) for t in self.symbol_tuples]
        return self._symbols

    @symbols.setter
    def symbols(self, value: list[Symbol]) -> None:
        self._symbols = value

    @property  # type: ignore[override]
    def idents(self) -> set[str]:
        if self._idents is None:
            self._idents = set(self._ident_text.split())
        return self._idents

    @idents.setter
    def idents(self, value: set[str]) -> None:
        self._idents = value


def _read(path: Path) -> Any:
    try:
        with open(path, "rb") as fh:
            return marshal.load(fh)
    except (OSError, ValueError, EOFError, TypeError):
        return None


def _write(path: Path, data: Any) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        marshal.dump(data, fh)
    os.replace(tmp, path)


class Index:
    def __init__(self, ctx, use_cache: bool = True) -> None:
        self.ctx = ctx
        self.root: Path = ctx.root
        self._base = cache_dir(self.root)
        self._dir = self._base / f"index-{_fingerprint()}"
        self._use_cache = use_cache
        self._infos: dict[str, FileInfo] = {}
        self._keys: dict[str, tuple[int, int]] = {}
        self._shards: dict[int, dict] = {}
        self._dirty: set[int] = set()

    def _shard(self, k: int) -> dict:
        sh = self._shards.get(k)
        if sh is None:
            data = _read(self._dir / f"{k:02x}.bin") if self._use_cache else None
            sh = data if isinstance(data, dict) else {}
            self._shards[k] = sh
        return sh

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            fresh = not self._dir.is_dir()
            self._dir.mkdir(parents=True, exist_ok=True)
            for k in sorted(self._dirty):
                _write(self._dir / f"{k:02x}.bin", self._shards[k])
            self._dirty.clear()
            if fresh:  # a new fingerprint: drop caches older adapters or formats wrote
                for old in self._base.iterdir():
                    if old.name.startswith("index-") and old != self._dir:
                        shutil.rmtree(old, ignore_errors=True)
                (self._base / "index.json").unlink(missing_ok=True)
        except OSError:
            pass  # a read-only home must not break the tool

    def info(self, path: str) -> FileInfo:
        """The analysis of one repo file, from the cache when its key still matches.
        A secret-looking path is REFUSED before anything about it is read or cached."""
        if path in self._infos:
            return self._infos[path]
        if repo.is_secret(path):
            raise TopomarkError("REFUSED", f"refusing to read a secret-looking file: {path}")
        full = self.root / path
        st = full.stat()
        key = (st.st_mtime_ns, st.st_size)
        k = shard_of(path)
        sh = self._shard(k)
        hit = sh.get(path)
        info: FileInfo
        if hit is not None and hit[0] == key[0] and hit[1] == key[1]:
            info = CachedInfo(path, hit[2])
        else:
            if st.st_size > MAX_BYTES:
                data = repo.safe_path(self.root, path).read_bytes()
                info = FileInfo(path=path, lang="large", line_count=0,
                                surface="sha256:" + hashlib.sha256(data).hexdigest())
            else:
                info = registry.analyze(path, self.ctx.read(path))
            sh[path] = (key[0], key[1], _pack(info))
            self._dirty.add(k)
        self._infos[path] = info
        self._keys[path] = key
        return info

    def all(self, paths: list[str] | None = None) -> dict[str, FileInfo]:
        full_scan = paths is None
        out = {}
        for p in paths if paths is not None else self.ctx.code_files:
            try:
                out[p] = self.info(p)
            except (OSError, TopomarkError):  # gone since git listed it, or refused
                continue
        if full_scan:
            for k in range(SHARDS):
                sh = self._shard(k)
                stale = [p for p in sh if p not in out]
                for p in stale:
                    del sh[p]
                if stale:
                    self._dirty.add(k)
        self.save()
        return out

    def digest(self, paths: list[str], extra: str = "") -> str:
        """A digest of these files' cache keys (and ``extra``): equal digests, equal analyses."""
        h = hashlib.sha256(extra.encode("utf-8"))
        for p in sorted(paths):
            key = self._keys.get(p)
            h.update(f"{p}\0{key}\n".encode("utf-8", "surrogatepass"))
        return h.hexdigest()[:24]

    def derived(self, name: str, digest: str, build: Callable[[], Any]) -> Any:
        """``build()``'s value, cached under ``name`` while ``digest`` and the code that builds
        derived tables (``_derived_fingerprint``) stay the same. Values must be marshal-able
        (dicts, lists, tuples, sets, strings, numbers)."""
        path = self._dir / f"derived-{name}.bin"
        key = f"{_derived_fingerprint()}:{digest}"
        data = _read(path) if self._use_cache else None
        if isinstance(data, tuple) and len(data) == 2 and data[0] == key:
            return data[1]
        value = build()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            _write(path, (key, value))
        except (OSError, ValueError):
            pass
        return value
