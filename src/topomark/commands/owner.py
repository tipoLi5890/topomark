"""``topomark owner <path>``: which area owns a path, its unit, fan-in and stamp state."""

from __future__ import annotations

from . import Result
from ._common import add, rel


def register(sub, common) -> None:
    p = add(sub, common, "owner", "which area owns a path, plus its fan-in and review-stamp state")
    p.add_argument("path")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    from .. import docs as D
    from ..workspace import Workspace

    ws = Workspace(ctx)
    path = rel(ctx, args.path)
    a, ties = D.owner_of(path, ws.areas)
    unit = D.unit_of(path, a) if a else None
    data = {"path": path, "area": a.name if a else None, "area_file": a.file if a else None, "unit": unit,
            "conflict": [x.name for x in ties] if len(ties) > 1 else [], "required": D.is_required(path, ws.cfg)}
    lines = [f"{path} -> {a.file if a else '(no area)'}" + (f"  unit {unit}" if unit and unit != path else "")]
    if len(ties) > 1:
        lines.append("conflict: " + ", ".join(x.name for x in ties))
    if path in ws.infos:
        p, t = ws.unit_fanin(path)
        data["fanin"] = {"prod": p, "test": t, "cross_areas": ws.graph.cross_areas(path)}
        lines.append(f"fan-in {p}/{t}" + (f"  cross-area: {', '.join(ws.graph.cross_areas(path))}"
                                          if ws.graph.cross_areas(path) else ""))
    if unit and unit in ws.units:
        rec = ws.stamps.units.get(unit)
        state = "none" if not rec else ("current" if rec.get("surface") == ws.unit_hash(unit) else "changed")
        data["stamp"] = state
        lines.append(f"review stamp: {state}")
    return Result(data, "\n".join(lines))
