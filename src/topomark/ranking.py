"""Ranking for ``map``: personalised PageRank over the reference graph, and the
weights that decide which of a file's symbols are worth a line in the map.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from .lang.base import FileInfo, Symbol
from .navigate import is_type_kind

if TYPE_CHECKING:
    from .navigate import Nav

def _name_edge_weight(name: str, referrers: int, focus_names: set[str]) -> float:
    """Aider-style edge weight: rare, distinctive names count more than common words."""
    w = 1.0 / math.sqrt(max(1, referrers))
    if re.fullmatch(r"[a-z][a-z0-9]*", name):  # `fetch`, `sha256`: plain words match everywhere
        w *= 0.1
    if name.startswith("_"):
        w *= 0.1
    if name in focus_names:
        w *= 10.0
    return w


USERS_SHARE = 0.5  # of a focus file's teleport weight, shared by the files that use it


def pagerank_files(nav: Nav, focus_files: set[str], candidates: set[str], focus_names: set[str] | None = None,
                   iterations: int = 40, damping: float = 0.85) -> dict[str, float]:
    """Personalised PageRank over the reference graph with IDF-weighted edges.

    Weighting every usable name the same lets a file of generic helpers (``fetch``,
    ``report``) outrank the real hubs; here a name used by N files contributes
    1/sqrt(N) per edge and plain lowercase words 10x less.
    Edges only join files of the same language: a Python ``re.compile`` is not a
    reference to a TypeScript ``compile``."""
    g = nav.graph
    infos = nav.infos
    focus_names = focus_names or set()
    nodes = [p for p in infos if p in candidates or p in focus_files]
    if not nodes:
        return {}
    index = {p: i for i, p in enumerate(nodes)}
    lang = [infos[p].lang for p in nodes]
    edges: dict[int, dict[int, float]] = {}  # referrer → {declaring file: weight}, by node index
    n: str | int  # a declared name here, the node count below
    for d, path in enumerate(nodes):
        for n in g.names_of(path):
            refs = g.ident_files.get(n, ())
            w = _name_edge_weight(n, len(refs), focus_names)
            decl = g.declared.get(n, ())
            for r in refs:
                ri = index.get(r)
                if ri is not None and ri != d and r not in decl and lang[ri] == lang[d]:
                    e = edges.setdefault(ri, {})
                    e[d] = e.get(d, 0.0) + w
    pers = {f: 1.0 for f in focus_files if f in index}
    # Rank flows from a file to what it uses, so a focus file that uses nothing (a leaf) would
    # centre the map on itself alone. Its users get half a focus file's weight between them, by
    # how much of it they use: the map then shows what a change to the focus reaches as well.
    for f in list(pers):
        d = index[f]
        users = {ri: e[d] for ri, e in edges.items() if d in e and nodes[ri] not in focus_files}
        total_use = sum(users.values())
        for ri, w in users.items():
            pers[nodes[ri]] = pers.get(nodes[ri], 0.0) + USERS_SHARE * w / total_use
    total = sum(pers.values()) or len(nodes)
    teleport = [(pers.get(k, 0.0) if pers else 1.0) / total for k in nodes]
    rank = list(teleport)
    adj = [(src, sum(dst.values()), list(dst.items())) for src, dst in edges.items()]
    dangling_nodes = [i for i in range(len(nodes)) if i not in edges]
    n = len(nodes)
    for _ in range(iterations):
        dangling = sum(rank[i] for i in dangling_nodes)
        base = 1 - damping + damping * dangling
        nxt = [base * t for t in teleport]
        for src, out_weight, dsts in adj:
            share = damping * rank[src] / out_weight
            for dst, w in dsts:
                nxt[dst] += share * w
        diff = sum(abs(a - b) for a, b in zip(nxt, rank, strict=True))
        rank = nxt
        if diff < 1e-9 * n:
            break
    return dict(zip(nodes, rank, strict=True))


def outline_size(info: FileInfo) -> int:
    """How many declarations an outline lists (namespaces aside), without building symbols
    for a cached file."""
    raw = getattr(info, "symbol_tuples", None)
    if raw is not None:
        return sum(1 for t in raw if t[0] != "namespace")
    return sum(1 for s in info.symbols if s.kind != "namespace")


def name_weight_bound(nav: Nav) -> float:
    """An upper bound of ``name_weight`` over every symbol (same arithmetic, the largest count)."""
    w = 1.0 + math.log1p(max(nav.ident_counts.values(), default=0))
    return w * 2.0 * 3.0


def name_weight(nav: Nav, sym: Symbol) -> float:
    w = 1.0 + math.log1p(nav.ident_counts.get(sym.name, 0))
    if sym.exported:
        w *= 2.0
    if is_type_kind(sym.kind):
        w *= 3.0
    if sym.name.startswith("_"):
        w *= 0.3
    return w
