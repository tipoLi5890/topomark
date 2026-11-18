"""``topomark stamp``: record that rows were reviewed (their units' surfaces now)."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add, rel

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "stamp", "record a review: these rows still describe their code",
            "A stamp says a human or agent looked at the row. Stamp a unit after reading `topomark diff` and\n"
            "updating its row; don't stamp to make `check` green.",
            "examples:\n"
            "  topomark stamp src/app/views.py           # one file unit\n"
            "  topomark stamp product/backend/services/  # one directory unit (granularity: dir)\n"
            "  topomark stamp --area pad                 # every unit in an area, plus its cross-area edges\n"
            "  topomark stamp --edges pad                # only the area's cross-area edges\n"
            "  topomark stamp --prune                    # drop stamps whose unit is gone\n"
            "  topomark stamp --baseline                 # first stamp of everything (refuses if stamps exist)")
    p.add_argument("paths", nargs="*", help="units to stamp (file paths, or directory units ending in /)")
    p.add_argument("--area", help="stamp every unit of this area and its edges")
    p.add_argument("--edges", metavar="AREA", help="stamp only this area's cross-area edges")
    p.add_argument("--prune", action="store_true", help="remove stamps whose unit no longer exists")
    p.add_argument("--baseline", action="store_true", help="stamp every unit and area (first adoption)")
    p.add_argument("--force", action="store_true", help="with --baseline: overwrite existing stamps")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError
    from ..stamps import blob_ids
    from ..workspace import Workspace

    ws = Workspace(ctx)
    st = ws.stamps
    names = {a.name for a in ws.areas}
    if args.prune:
        gone = sorted(set(st.units) - set(ws.units))
        for u in gone:
            del st.units[u]
        for a in sorted(set(st.areas) - names):
            del st.areas[a]
        st.save()
        return Result({"pruned": gone}, f"topomark stamp --prune: removed {len(gone)} stamp(s)")
    units: list[str] = []
    edge_areas: list[str] = []
    if args.baseline:
        if (st.units or st.areas) and not args.force and st.foreign_version is None:
            raise TopomarkError("REFUSED", "stamps already exist; --baseline would erase which rows were never "
                                           "reviewed. Add --force if that is intended.")
        if st.foreign_version is not None and not args.force:
            raise TopomarkError("REFUSED", f"stamps.json is format {st.foreign_version}; add --force to replace it")
        st.units, st.areas = {}, {}
        st.foreign_version = None
        units = sorted(ws.units)
        edge_areas = sorted(names)
    elif args.area:
        if args.area not in names:
            raise TopomarkError("NOT_FOUND", f"no area named {args.area!r}")
        units = sorted(u for u, d in ws.units.items() if d["area"] == args.area)
        edge_areas = [args.area]
    elif args.edges:
        if args.edges not in names:
            raise TopomarkError("NOT_FOUND", f"no area named {args.edges!r}")
        edge_areas = [args.edges]
    else:
        if not args.paths:
            raise TopomarkError("USAGE", "name the units to stamp, or use --area/--edges/--prune/--baseline")
        for raw in args.paths:
            u = rel(ctx, raw)
            if u not in ws.units and u.rstrip("/") + "/" in ws.units:
                u = u.rstrip("/") + "/"
            if u not in ws.units:
                raise TopomarkError("NOT_FOUND", f"{u} is not a code-map unit (see `topomark owner {u}`)")
            units.append(u)
    files = sorted({f for u in units for f in ws.units[u]["files"]})
    blobs = blob_ids(ctx.root, files)
    for u in units:
        st.units[u] = {"surface": ws.unit_hash(u),
                       "blobs": {f: blobs[f] for f in ws.units[u]["files"]}}
    for a in edge_areas:
        st.areas[a] = {"edges": ws.edges_hash(a)}
    st.save()
    return Result({"units": units, "areas": edge_areas},
                  f"topomark stamp: {len(units)} unit(s), {len(edge_areas)} area edge set(s)")
