"""``topomark diff <unit>``: what changed since the unit's review stamp."""

from __future__ import annotations

import argparse
import difflib
from typing import TYPE_CHECKING, Any

from . import Result
from ._common import add, rel

if TYPE_CHECKING:
    from ..context import Context


def register(sub: Any, common: argparse.ArgumentParser) -> None:
    p = add(sub, common, "diff", "show what changed in a unit since its review stamp (interface first)")
    p.add_argument("unit", help="a file path, or a directory unit ending in /")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace, ctx: Context) -> Result:
    from ..errors import TopomarkError
    from ..lang import registry
    from ..repo import git, git_objects
    from ..stamps import blob_ids
    from ..workspace import Workspace

    ws = Workspace(ctx)
    unit = rel(ctx, args.unit)
    if unit not in ws.units and unit.rstrip("/") + "/" in ws.units:
        unit = unit.rstrip("/") + "/"
    if unit not in ws.units:
        raise TopomarkError("NOT_FOUND", f"{unit} is not a code-map unit")
    rec = ws.stamps.units.get(unit)
    if not rec:
        raise TopomarkError("NOT_FOUND", f"{unit} has no review stamp yet")
    old_blobs: dict[str, str] = rec.get("blobs", {})
    files = ws.units[unit]["files"]
    new_blobs = blob_ids(ctx.root, files)
    out_lines = []
    report = []
    differing = [f for f in sorted(set(files) | set(old_blobs)) if old_blobs.get(f) != new_blobs.get(f)]
    # every reviewed version in one git process, not one `cat-file` per file of a directory unit
    reviewed = git_objects(ctx.root, sorted({old_blobs[f] for f in differing if old_blobs.get(f)}))
    for f in differing:
        old_b, new_b = old_blobs.get(f), new_blobs.get(f)
        entry: dict = {"file": f, "status": "added" if not old_b else "removed" if not new_b else "modified"}
        old_surface = []
        if old_b:
            old_text = reviewed.get(old_b)
            if old_text is None:
                entry["note"] = "reviewed content no longer in the object store (gc); only hashes compared"
            else:
                old_surface = registry.analyze(f, old_text).surface.split("\n")
        new_surface = ws.infos[f].surface.split("\n") if f in ws.infos else []
        d = list(difflib.unified_diff(old_surface, new_surface, "reviewed", "now", lineterm="", n=1))[2:]
        entry["interface_diff"] = d
        if old_b and new_b:
            stat = git(ctx.root, "diff", "--numstat", "--no-ext-diff", "--no-textconv", old_b, new_b,
                       check=False).split()
            if len(stat) >= 2:
                entry["added"], entry["removed"] = int(stat[0]), int(stat[1])
            entry["git_diff"] = f"git diff {old_b[:12]} {new_b[:12]}"
        report.append(entry)
        out_lines.append(f"{f}: {entry['status']}" + (f" (+{entry.get('added', 0)} -{entry.get('removed', 0)} lines)"
                                                      if "added" in entry else ""))
        if d:
            out_lines.append("  interface:")
            out_lines += ["    " + x for x in d]
        elif entry["status"] == "modified":
            out_lines.append("  interface unchanged (body only)")
        if "git_diff" in entry:
            out_lines.append(f"  full: {entry['git_diff']}")
        if "note" in entry:
            out_lines.append(f"  note: {entry['note']}")
    changed = ws.interface_changed(unit)
    head = f"{unit}: interface {'CHANGED' if changed else 'unchanged'} since review"
    if not report:
        head += "; content identical"
    return Result({"unit": unit, "interface_changed": changed, "files": report}, "\n".join([head] + out_lines))
