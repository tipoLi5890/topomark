"""Per-file analysis with an on-disk cache outside the repo.

The cache lives in the user's cache directory (``$TOPOMARK_CACHE``, else
``$XDG_CACHE_HOME/topomark``, on Windows ``%LOCALAPPDATA%/topomark/Cache``, else
``~/.cache/topomark``), one folder per repo
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

A whole-repo command that finds ``PARALLEL_MIN`` or more files to parse (a first run, or the
run after an upgrade) parses them in worker processes (``$TOPOMARK_JOBS``; 1 means in this
process), and in this process when workers cannot be started. A single file never starts one.

Files larger than ``MAX_BYTES`` are listed but not parsed (no symbols); their
surface is the SHA-256 of their content so stamps still notice changes.
"""

from __future__ import annotations

import hashlib
import marshal
import os
import re
import shutil
import sys
import time
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__, repo
from .errors import TopomarkError
from .lang import registry
from .lang.base import FileInfo, Symbol

if TYPE_CHECKING:
    from .context import Context

MAX_BYTES = 3 * 1024 * 1024
CACHE_FORMAT = 3
SHARDS = 256
PARALLEL_MIN = 600    # files to parse before worker processes pay for starting (each imports the adapters)
MAX_JOBS = 8
KEEP_DAYS = 14        # an index another version or interpreter wrote stays this long after its last use
KEEP_REPO_DAYS = 90   # a repository's whole cache folder, after the last use of any index in it
_DAY = 86400.0
_REPO_DIR = re.compile(r"[0-9a-f]{16}")
_INDEX_DIR = re.compile(r"index-[0-9a-f]{16}")
# What builds the tables Index.derived keeps: the graph, Nav's identifier counts, import edges, and the
# search index with the masking and test-method detection it reads. Not runners.py or ranking.py.
DERIVED_MODULES = ("graph.py", "navigate.py", "imports.py", "masking.py", "testsel.py", "search.py")


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


def cache_base(env: Mapping[str, str], windows: bool) -> str:
    """Where the cache folders of all repositories live, as the first of these that is set:
    ``$TOPOMARK_CACHE``, ``$XDG_CACHE_HOME/topomark``, on Windows ``%LOCALAPPDATA%/topomark/Cache``
    (where Windows keeps data a program can rebuild), else ``~/.cache/topomark``."""
    if env.get("TOPOMARK_CACHE"):
        return env["TOPOMARK_CACHE"]
    if env.get("XDG_CACHE_HOME"):
        return os.path.join(env["XDG_CACHE_HOME"], "topomark")
    if windows and env.get("LOCALAPPDATA"):
        return os.path.join(env["LOCALAPPDATA"], "topomark", "Cache")
    return os.path.join(os.path.expanduser("~"), ".cache", "topomark")


def cache_dir(root: Path) -> Path:
    d = Path(cache_base(os.environ, os.name == "nt"))
    return d / hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def shard_of(path: str) -> int:
    return zlib.crc32(path.encode("utf-8")) % SHARDS


_SYMBOL_FIELDS = ("kind", "name", "qualname", "start", "end", "signature", "exported", "container", "attrs", "doc",
                  "line")


def _pack(info: FileInfo) -> tuple:
    from .graph import partial_names

    syms = [tuple(getattr(s, f) for f in _SYMBOL_FIELDS) for s in info.symbols]
    return (info.lang, info.line_count, info.header, marshal.dumps(syms), info.types, info.imports,
            " ".join(sorted(info.idents)), info.surface, partial_names(info), info.degraded)


def _jobs() -> int:
    """Worker processes for a cold whole-repo parse: ``$TOPOMARK_JOBS``, else the CPUs up to ``MAX_JOBS``."""
    raw = os.environ.get("TOPOMARK_JOBS", "")
    if raw.isdigit():
        return max(1, int(raw))
    return max(1, min(MAX_JOBS, os.cpu_count() or 1))


def _parse_packed(job: tuple[str, str]) -> tuple[str, int, int, tuple] | None:
    """In a worker: one file's cache entry, or None for a file the parent should look at itself
    (unreadable, refused, or too large to parse)."""
    root, path = job
    try:
        st = (Path(root) / path).stat()
        if st.st_size > MAX_BYTES:
            return None
        return path, st.st_mtime_ns, st.st_size, _pack(registry.analyze(path, repo.read_text(Path(root), path)))
    except (OSError, TopomarkError):
        return None


def _symbol(t: tuple) -> Symbol:
    s = object.__new__(Symbol)
    s.__dict__.update(zip(_SYMBOL_FIELDS, t, strict=False))
    return s


class CachedInfo(FileInfo):
    """A ``FileInfo`` read back from the cache. Symbols and identifiers are decoded on
    first use: whole-repo commands read every file's types and imports but only some
    files' symbols, and loading 50,000 symbols costs more than everything else."""

    def __init__(self, path: str, packed: tuple) -> None:  # not the dataclass __init__: fields are set here
        lang, line_count, header, blob, types, imports, idents, surface, partial, degraded = packed
        self.path, self.lang, self.header, self.surface, self.degraded = path, lang, header, surface, degraded
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

    @property
    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            self._symbols = [_symbol(t) for t in self.symbol_tuples]
        return self._symbols

    @symbols.setter
    def symbols(self, value: list[Symbol]) -> None:
        self._symbols = value

    @property
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


def _mark_used(index_dir: Path) -> None:
    """Note that this index was read today (its folder's mtime), so the sweep keeps it."""
    try:
        if time.time() - index_dir.stat().st_mtime > _DAY:
            os.utime(index_dir)
    except OSError:
        pass


def _sweep(base: Path, keep: Path) -> None:
    """Remove what nothing has used for a while: other indexes of this repository (two versions or
    interpreters used in turn each keep theirs for ``KEEP_DAYS``), temporary files a killed run left,
    and the cache folders of repositories not opened for ``KEEP_REPO_DAYS``. Only folders named the
    way this module names them, holding nothing else, are ever removed."""
    now = time.time()
    for old in base.iterdir():
        if _INDEX_DIR.fullmatch(old.name) and old != keep and now - old.stat().st_mtime > KEEP_DAYS * _DAY:
            shutil.rmtree(old, ignore_errors=True)
    (base / "index.json").unlink(missing_ok=True)
    for tmp in keep.glob("*.tmp"):
        if now - tmp.stat().st_mtime > 3600:
            tmp.unlink(missing_ok=True)
    for repo_dir in base.parent.iterdir():
        if repo_dir == base or not _REPO_DIR.fullmatch(repo_dir.name) or not repo_dir.is_dir():
            continue
        inside = list(repo_dir.iterdir())
        if inside and all(_INDEX_DIR.fullmatch(d.name) and d.is_dir() for d in inside) \
                and all(now - d.stat().st_mtime > KEEP_REPO_DAYS * _DAY for d in inside):
            shutil.rmtree(repo_dir, ignore_errors=True)


class Index:
    def __init__(self, ctx: Context, use_cache: bool = True) -> None:
        self.ctx = ctx
        self.root: Path = ctx.root
        self._base = cache_dir(self.root)
        self._dir = self._base / f"index-{_fingerprint()}"
        self._use_cache = use_cache
        self._infos: dict[str, FileInfo] = {}
        self._keys: dict[str, tuple[int, int]] = {}
        self._stats: dict[str, os.stat_result] = {}  # read by `_missing`, used once by `info`
        self._shards: dict[int, dict] = {}
        self._dirty: set[int] = set()
        # what this process changed in each dirty shard: save() merges only that into the file, so
        # two runs at once (the hooks start one per tool call) do not undo each other's entries
        self._written: dict[int, set[str]] = {}
        self._removed: dict[int, set[str]] = {}
        self._used = False

    def _shard(self, k: int) -> dict:
        sh = self._shards.get(k)
        if sh is None:
            data = _read(self._dir / f"{k:02x}.bin") if self._use_cache else None
            sh = data if isinstance(data, dict) else {}
            self._shards[k] = sh
            if data is not None and not self._used:
                self._used = True
                _mark_used(self._dir)
        return sh

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            fresh = not self._dir.is_dir()
            self._dir.mkdir(parents=True, exist_ok=True)
            for k in sorted(self._dirty):
                path = self._dir / f"{k:02x}.bin"
                mine = self._shards[k]
                disk = _read(path) if self._use_cache and not fresh else None
                if isinstance(disk, dict) and disk is not mine:
                    for p in self._removed.get(k, ()):
                        disk.pop(p, None)
                    for p in self._written.get(k, ()):
                        if p in mine:
                            disk[p] = mine[p]
                    mine = self._shards[k] = disk
                _write(path, mine)
            self._dirty.clear()
            self._written.clear()
            self._removed.clear()
            if fresh:  # a new fingerprint (another version, interpreter or adapter code)
                _sweep(self._base, self._dir)
        except OSError:
            pass  # a read-only home must not break the tool

    def info(self, path: str) -> FileInfo:
        """The analysis of one repo file, from the cache when its key still matches.
        A secret-looking path is REFUSED before anything about it is read or cached."""
        if path in self._infos:
            return self._infos[path]
        if repo.is_secret(path):
            raise TopomarkError("REFUSED", f"refusing to read a secret-looking file: {path}")
        st = self._stats.pop(path, None) or (self.root / path).stat()
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
            self._written.setdefault(k, set()).add(path)
        self._infos[path] = info
        self._keys[path] = key
        return info

    def _missing(self, paths: list[str]) -> list[str]:
        """The files of ``paths`` that have no current cache entry (what a serial run would parse)."""
        todo = []
        for p in paths:
            if p in self._infos or repo.is_secret(p):
                continue
            try:
                st = (self.root / p).stat()
            except OSError:
                continue
            self._stats[p] = st  # a whole-repo run stats each file once, not twice
            hit = self._shard(shard_of(p)).get(p)
            if (hit is None or hit[0] != st.st_mtime_ns or hit[1] != st.st_size) and st.st_size <= MAX_BYTES:
                todo.append(p)
        return todo

    def _parse_in_workers(self, paths: list[str]) -> None:
        """Fill the shards for ``paths`` from worker processes; ``info`` then finds them cached.
        Whatever keeps workers from starting (no semaphores in a sandbox, a frozen interpreter)
        leaves the shards as they were, and the files are parsed in this process as before."""
        jobs = min(_jobs(), len(paths) // (PARALLEL_MIN // 4) or 1)
        if jobs < 2:
            return
        try:
            from concurrent.futures import ProcessPoolExecutor
            from concurrent.futures.process import BrokenProcessPool
        except ImportError:
            return
        root = str(self.root)
        try:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                done = list(pool.map(_parse_packed, [(root, p) for p in paths],
                                     chunksize=max(1, len(paths) // (jobs * 8))))
        except (OSError, ImportError, NotImplementedError, BrokenProcessPool):
            return
        for entry in done:
            if entry is None:
                continue
            path, mtime, size, packed = entry
            k = shard_of(path)
            self._shard(k)[path] = (mtime, size, packed)
            self._dirty.add(k)
            self._written.setdefault(k, set()).add(path)

    def all(self, paths: list[str] | None = None) -> dict[str, FileInfo]:
        full_scan = paths is None
        out = {}
        wanted = paths if paths is not None else self.ctx.code_files
        if len(wanted) >= PARALLEL_MIN and _jobs() > 1:
            todo = self._missing(wanted)
            if len(todo) >= PARALLEL_MIN:
                self._parse_in_workers(todo)
        for p in wanted:
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
                    self._removed.setdefault(k, set()).update(stale)
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
