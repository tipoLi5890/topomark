"""Reference graph: who mentions the names a file declares.

Approximate by design: a file *references* a declared name when the identifier
appears in its code (comments and strings masked out). Names shorter than
``min_name`` (unless listed in ``keep_short_names``) and names declared by more
than one file (unless every declaration is ``partial``) are ignored, because
they match too much. Tests only ever reference; they never declare for this
purpose, so a test's private ``Router`` stub can't inflate a real ``Router``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .config import Config
from .docs import Area, is_test, owner_of
from .lang.base import FileInfo


@dataclass
class FanIn:
    prod: set[str]
    test: set[str]


def partial_names(info: FileInfo) -> list[str]:
    """Top-level declarations marked ``partial`` (C#): spread over files on purpose."""
    cached = getattr(info, "partial_names", None)  # index.CachedInfo knows without decoding symbols
    if cached is not None:
        return cached
    return [s.name for s in info.symbols if not s.container and " partial " in f" {s.signature} "]


def build_tables(cfg: Config, infos: dict[str, FileInfo]) -> dict:
    """The graph's tables as plain lists (cacheable; see ``Index.derived``)."""
    tests = {p for p in infos if is_test(p, cfg)}
    declared: dict[str, set[str]] = defaultdict(set)
    partial: set[str] = set()
    for p, info in infos.items():
        if p in tests:
            continue
        for name in info.types:
            declared[name].add(p)
        partial.update(partial_names(info))
    short = {n for n in declared if len(n) < cfg.min_name and n not in cfg.keep_short_names}
    ambiguous = {n for n, fs in declared.items() if len(fs) > 1 and n not in partial}
    usable = {n for n in declared if n not in short and n not in ambiguous}
    ident_files: dict[str, list[str]] = defaultdict(list)
    for p, info in infos.items():
        for ident in info.idents & usable:
            ident_files[ident].append(p)
    return {"tests": sorted(tests), "declared": {n: sorted(fs) for n, fs in declared.items()},
            "short": sorted(short), "ambiguous": sorted(ambiguous), "usable": sorted(usable),
            "ident_files": dict(ident_files)}


def tables_key(cfg: Config) -> str:
    """The config inputs ``build_tables`` depends on, for the cache digest."""
    return repr((cfg.min_name, sorted(cfg.keep_short_names), list(cfg.test_patterns)))


class Graph:
    def __init__(self, cfg: Config, infos: dict[str, FileInfo], areas: list[Area], tables: dict | None = None) -> None:
        self.cfg = cfg
        self.infos = infos
        self.areas = areas
        t = tables if tables is not None else build_tables(cfg, infos)
        self.tests = set(t["tests"])
        self.declared: dict[str, set[str]] = defaultdict(set, {n: set(fs) for n, fs in t["declared"].items()})
        self.short = set(t["short"])
        self.ambiguous = set(t["ambiguous"])
        self.usable = set(t["usable"])
        self.ident_files: dict[str, set[str]] = defaultdict(set, {n: set(fs) for n, fs in t["ident_files"].items()})
        self._fanin: dict[str, FanIn] = {}

    def names_of(self, path: str) -> set[str]:
        info = self.infos.get(path)
        if info is None or path in self.tests:
            return set()
        return {n for n in info.types if n in self.usable}

    def fanin(self, path: str) -> FanIn:
        if path in self._fanin:
            return self._fanin[path]
        names = self.names_of(path)
        siblings = set().union(*(self.declared[n] for n in names)) if names else set()
        refs: set[str] = set()
        for n in names:
            refs |= self.ident_files.get(n, set())
        refs -= siblings
        refs.discard(path)
        fi = FanIn(prod={r for r in refs if r not in self.tests}, test={r for r in refs if r in self.tests})
        self._fanin[path] = fi
        return fi

    def area_of(self, path: str) -> str:
        a, _ = owner_of(path, self.areas)
        return a.name if a else ""

    def cross_areas(self, path: str) -> list[str]:
        mine = self.area_of(path)
        return sorted({self.area_of(r) or "?" for r in self.fanin(path).prod} - {mine})

    def edges(self) -> dict[str, dict[str, float]]:
        """referrer → {declaring file: weight}; weight = how many of its names are used."""
        out: dict[str, dict[str, float]] = defaultdict(dict)
        for path in self.infos:
            for n in self.names_of(path):
                for r in self.ident_files.get(n, ()):
                    if r != path and r not in self.declared[n]:
                        out[r][path] = out[r].get(path, 0.0) + 1.0
        return out

    def pagerank(self, personalization: dict[str, float] | None = None, iterations: int = 40,
                 damping: float = 0.85) -> dict[str, float]:
        nodes = list(self.infos)
        if not nodes:
            return {}
        edges = self.edges()
        n = len(nodes)
        if personalization:
            total = sum(personalization.values()) or 1.0
            teleport = {k: personalization.get(k, 0.0) / total for k in nodes}
        else:
            teleport = {k: 1.0 / n for k in nodes}
        rank = dict(teleport) if personalization else {k: 1.0 / n for k in nodes}
        out_weight = {src: sum(dst.values()) for src, dst in edges.items()}
        for _ in range(iterations):
            nxt = {k: (1 - damping) * teleport[k] for k in nodes}
            dangling = sum(rank[k] for k in nodes if k not in out_weight)
            for k in nodes:
                nxt[k] += damping * dangling * teleport[k]
            for src, dsts in edges.items():
                if src not in rank:
                    continue
                share = damping * rank[src] / out_weight[src]
                for dst, w in dsts.items():
                    if dst in nxt:
                        nxt[dst] += share * w
            diff = sum(abs(nxt[k] - rank[k]) for k in nodes)
            rank = nxt
            if diff < 1e-9 * n:
                break
        if not math.isfinite(sum(rank.values())):
            return {k: 0.0 for k in nodes}
        return rank
