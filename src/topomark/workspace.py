"""Everything a doc-system command needs, loaded once: areas, index, graph,
required units, stamps, generated reports, and the problem list ``check`` prints.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Callable

from . import docs as D
from .context import Context
from .graph import Graph, build_tables, tables_key
from .index import Index
from .stamps import Stamps, h16, unit_surface_hash

FAN_RX = re.compile(r"fan-in\s*(\d+)\s*/\s*(\d+)", re.I)
ROW_RX = re.compile(r"^\|\s*`([^`]+)`[^|`]*\|")


@dataclass
class Problem:
    code: str
    file: str
    message: str
    subject: str = ""

    def to_json(self) -> dict:
        d = {"code": self.code, "file": self.file, "message": self.message}
        if self.subject:
            d["subject"] = self.subject
        return d


class Workspace:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.cfg = ctx.config

    # ---------------------------------------------------------------- loading
    @cached_property
    def areas(self) -> list[D.Area]:
        return D.load_areas(self.ctx)

    @cached_property
    def index(self) -> Index:
        return Index(self.ctx)

    @cached_property
    def infos(self):
        return self.index.all()

    @cached_property
    def graph(self) -> Graph:
        infos = self.infos
        tables = self.derived("graph", tables_key(self.cfg), lambda: build_tables(self.cfg, infos))
        return Graph(self.cfg, infos, self.areas, tables)

    def derived(self, name: str, inputs: str, build: Callable[[], Any]) -> Any:
        """Whole-repo data cached until a parsed file (or ``inputs``) changes."""
        infos = self.infos
        return self.index.derived(name, self.index.digest(list(infos), inputs), build)

    @cached_property
    def stamps(self) -> Stamps:
        return Stamps(f"{self.cfg.docs_dir}/stamps.json", self.ctx.root)

    @cached_property
    def required(self) -> list[str]:
        return [f for f in self.ctx.files if D.is_required(f, self.cfg)]

    @cached_property
    def units(self) -> dict[str, dict]:
        """unit → {"area": name, "files": [...]} for every required file with an owner."""
        out: dict[str, dict] = {}
        for f in self.required:
            a, _ = D.owner_of(f, self.areas)
            if a is None:
                continue
            u = D.unit_of(f, a)
            out.setdefault(u, {"area": a.name, "files": []})["files"].append(f)
        return out

    def surface_hash(self, path: str) -> str:
        return h16(self.infos[path].surface) if path in self.infos else h16("")

    def unit_hash(self, unit: str) -> str:
        files = self.units[unit]["files"]
        return unit_surface_hash({f: self.surface_hash(f) for f in files})

    def unit_fanin(self, unit: str) -> tuple[int, int]:
        prod: set[str] = set()
        test: set[str] = set()
        files = set(self.units[unit]["files"]) if unit in self.units else {unit}
        for f in files:
            fi = self.graph.fanin(f)
            prod |= fi.prod
            test |= fi.test
        return len(prod - files), len(test - files)

    def edges(self, area: str) -> list[str]:
        rows = []
        for f in self.ctx.code_files:
            if f in self.graph.tests:
                continue
            if self.graph.area_of(f) != area:
                continue
            cross = self.graph.cross_areas(f)
            if cross:
                rows.append(f"{f} <- {', '.join(cross)}")
        return sorted(rows)

    def edges_hash(self, area: str) -> str:
        return h16("\n".join(self.edges(area)))

    # ---------------------------------------------------------------- generated reports
    def generated(self) -> dict[str, str]:
        base = f"{self.cfg.docs_dir}/_generated"
        return {f"{base}/fanin.md": self._fanin_report(), f"{base}/modules.md": self._modules_report()}

    def _fanin_report(self) -> str:
        g = self.graph
        rows = []
        for f in self.ctx.code_files:
            if f in g.tests or not g.names_of(f):
                continue
            fi = g.fanin(f)
            rows.append((len(fi.prod), len(fi.test), f, g.area_of(f) or "-", g.cross_areas(f)))
        rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
        keep = ", ".join(sorted(self.cfg.keep_short_names)) or "-"
        out = ["# Fan-in (generated, do not edit; approximate)", "",
               "Production fan-in = how many non-test files mention a name this file declares (coupling: "
               "the callers to check when you change it). Test fan-in = how many test files mention it "
               "(guard rails). Cross-area = which other code-map areas the production callers live in.",
               f"Only top-level declarations count. Names shorter than {self.cfg.min_name} characters (except "
               f"{keep}) and names declared in more than one file (unless partial) are ignored; see the end of "
               "this file. Test files only ever reference.", "",
               "| prod | test | file | area | cross-area callers |", "|---:|---:|---|---|---|"]
        for p, tt, f, a, cross in rows:
            out.append(f"| {p} | {tt} | `{f}` | {a} | {', '.join(cross)} |")
        out += ["", f"Names not counted ({len(g.short)} short, {len(g.ambiguous)} declared in several files):",
                "", "```",
                "short: " + ", ".join(sorted(g.short)), "ambiguous: " + ", ".join(sorted(g.ambiguous)), "```"]
        order = {r[2]: k for k, r in enumerate(rows)}
        guard: dict[str, list[str]] = defaultdict(list)
        for _, _, f, _, _ in rows:
            for tf in g.fanin(f).test:
                guard[tf].append(f)
        if guard:
            out += ["", "## Test file → production files it mentions", "",
                    "| test file | count | production files (by fan-in) |", "|---|---:|---|"]
            for tf in sorted(guard):
                fs = sorted(guard[tf], key=lambda x: order[x])
                shown = ", ".join(f"`{x}`" for x in fs[:12])
                if len(fs) > 12:
                    shown += f" … {len(fs) - 12} more"
                out.append(f"| `{tf}` | {len(fs)} | {shown} |")
        return "\n".join(out) + "\n"

    def _modules_report(self) -> str:
        out = ["# Module graph (generated, do not edit)", ""]
        asm = {}
        for f in self.ctx.files:
            if f.endswith(".asmdef"):
                try:
                    d = json.loads(self.ctx.read(f))
                except ValueError:
                    continue
                asm[d.get("name", f)] = {"file": f, "refs": d.get("references", []),
                                         "noEngine": bool(d.get("noEngineReferences")),
                                         "platforms": d.get("includePlatforms", [])}
        npm = {}
        for f in self.ctx.files:
            if f.endswith("package.json") and "/node_modules/" not in f:
                try:
                    d = json.loads(self.ctx.read(f))
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("name"):
                    deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
                    npm[d["name"]] = {"file": f, "deps": sorted(deps)}
        if not asm and not npm:
            return "\n".join(out + ["(no module manifests found)"]) + "\n"
        if asm:
            rev = defaultdict(list)
            for n, d in asm.items():
                for r in d["refs"]:
                    rev[r].append(n)
            out += ["## Unity assembly definitions", "", "| assembly | file | depends on | used by | notes |",
                    "|---|---|---|---|---|"]
            for n in sorted(asm):
                d = asm[n]
                note = []
                if d["noEngine"]:
                    note.append("pure C#")
                if d["platforms"]:
                    note.append("only " + "/".join(d["platforms"]))
                out.append(f"| {n} | `{d['file']}` | {', '.join(d['refs']) or '-'} | "
                           f"{', '.join(sorted(rev.get(n, []))) or '-'} | {'; '.join(note)} |")
            out.append("")
        if npm:
            local = set(npm)
            rev = defaultdict(list)
            for n, d in npm.items():
                for r in d["deps"]:
                    if r in local:
                        rev[r].append(n)
            out += ["## npm packages in this repo", "", "| package | file | depends on (in repo) | used by (in repo) |",
                    "|---|---|---|---|"]
            for n in sorted(npm):
                d = npm[n]
                inner = [x for x in d["deps"] if x in local]
                out.append(f"| {n} | `{d['file']}` | {', '.join(inner) or '-'} | {', '.join(sorted(rev.get(n, []))) or '-'} |")
        return "\n".join(out).rstrip() + "\n"

    # ---------------------------------------------------------------- problems
    def fan_mismatches(self, text: str) -> list[tuple[int, str, tuple[int, int], tuple[int, int]]]:
        out = []
        for i, line in enumerate(text.split("\n")):
            m = ROW_RX.match(line)
            if not m:
                continue
            subject = m.group(1)
            if subject not in self.units and subject not in self.infos:
                continue
            f = FAN_RX.search(line)
            if not f:
                continue
            now = self.unit_fanin(subject)
            old = (int(f.group(1)), int(f.group(2)))
            if old != now:
                out.append((i, subject, old, now))
        return out

    def problems(self, only_area: str | None = None, include_stamps: bool = True) -> list[Problem]:
        cfg = self.cfg
        P: list[Problem] = []
        by_name = {a.name: a for a in self.areas}
        targets = [a for a in self.areas if not only_area or a.name == only_area]
        all_set = set(self.ctx.all_files)
        top_dirs = {f.split("/")[0] for f in self.ctx.all_files if "/" in f}
        top_files = {f for f in self.ctx.all_files if "/" not in f}
        l0 = f"{cfg.docs_dir}/README.md"

        for a in targets:
            for k in ("title", "summary"):
                if not getattr(a, k):
                    P.append(Problem("FRONTMATTER", a.file, f"frontmatter is missing `{k}`"))
            if not a.scope:
                P.append(Problem("FRONTMATTER", a.file, "frontmatter is missing `scope`"))
            if a.granularity not in ("file", "dir"):
                P.append(Problem("FRONTMATTER", a.file, f"granularity must be file or dir, not {a.granularity!r}"))
            for s in a.scope:
                if s.endswith("/"):
                    if not any(f.startswith(s) for f in self.ctx.all_files):
                        P.append(Problem("FRONTMATTER", a.file, f"scope {s} contains no files"))
                elif s not in all_set:
                    P.append(Problem("FRONTMATTER", a.file, f"scope {s} does not exist"))

        for f in self.required:
            a, ties = D.owner_of(f, self.areas)
            if a is None:
                if not only_area:
                    P.append(Problem("UNOWNED", f, "no area's scope covers this file", f))
                continue
            if len(ties) > 1:
                P.append(Problem("OWNER_CONFLICT", f, "claimed equally by " + ", ".join(x.name for x in ties), f))
        for unit, u in sorted(self.units.items()):
            a = by_name[u["area"]]
            if only_area and a.name != only_area:
                continue
            if not D.mentions(a.text, unit):
                hint = f"`{unit}`" + (f" ({len(u['files'])} files)" if unit.endswith("/") else "")
                P.append(Problem("NOT_LISTED", a.file, f"no row for {hint}", unit))
        for a in targets:
            if a.granularity == "dir":
                for m in D.UNIT_COUNT.finditer(a.text):
                    unit, n = m.group(1), int(m.group(2))
                    if unit in self.units and len(self.units[unit]["files"]) != n:
                        P.append(Problem("UNIT_COUNT", a.file,
                                         f"`{unit}` says {n} files, has {len(self.units[unit]['files'])}", unit))

        docs = [(a.file, a.text) for a in targets]
        if not only_area and (cfg.root / l0).is_file():
            docs.append((l0, self.ctx.read(l0)))
        for path, text in docs:
            for ref in sorted(D.path_refs(text, top_dirs, top_files)):
                if any(ch in ref for ch in "*<{"):
                    continue
                if ref.endswith("/"):
                    if not any(f.startswith(ref) for f in self.ctx.all_files):
                        P.append(Problem("DEAD_PATH", path, f"directory `{ref}` does not exist", ref))
                elif ref not in all_set and not any(f.startswith(ref + "/") for f in self.ctx.all_files):
                    P.append(Problem("DEAD_PATH", path, f"path `{ref}` does not exist", ref))
            cap = cfg.l0_max if path == l0 else cfg.l1_max
            n = text.count("\n")
            if n > cap:
                P.append(Problem("LINE_CAP", path, f"{n} lines, over the cap of {cap}"))
            for i, subject, old, now in self.fan_mismatches(text):
                P.append(Problem("FANIN_STALE", path, f"`{subject}` says fan-in {old[0]}/{old[1]}, now "
                                                       f"{now[0]}/{now[1]} (run `topomark sync`)", subject))

        if not only_area:
            if not (cfg.root / l0).is_file():
                P.append(Problem("L0_MISSING", l0, "the L0 index does not exist (run `topomark init`)"))
            else:
                l0_text = self.ctx.read(l0)
                for a in self.areas:
                    if a.file.rsplit("/", 1)[-1] not in l0_text:
                        P.append(Problem("L0_LINK", l0, f"does not link to {a.file}"))
            for path, text in self.generated().items():
                full = cfg.root / path
                if not full.is_file() or self.ctx.read(path) != text:
                    P.append(Problem("GENERATED_STALE", path, "out of date (run `topomark gen`)"))

        if include_stamps:
            P += self.stamp_problems(only_area)
        return P

    def stamp_problems(self, only_area: str | None = None) -> list[Problem]:
        st = self.stamps
        P: list[Problem] = []
        if st.foreign_version is not None:
            P.append(Problem("STAMPS_FORMAT", st.path, f"stamps.json is format {st.foreign_version}; this topomark "
                                                       f"reads {st.version}. Review, then `topomark stamp --baseline --force`."))
            return P
        by_name = {a.name: a for a in self.areas}
        for unit, u in sorted(self.units.items()):
            if only_area and u["area"] != only_area:
                continue
            rec = st.units.get(unit)
            afile = by_name[u["area"]].file
            if not rec:
                P.append(Problem("STAMP_MISSING", afile, f"`{unit}` has no review stamp (write its row, then "
                                                         f"`topomark stamp {unit}`)", unit))
            elif rec.get("surface") != self.unit_hash(unit):
                P.append(Problem("STAMP_CHANGED", afile, f"`{unit}` changed its interface since review "
                                                         f"(`topomark diff {unit}`, update the row, `topomark stamp {unit}`)",
                                 unit))
        if not only_area:
            for unit in sorted(set(st.units) - set(self.units)):
                P.append(Problem("STAMP_ORPHAN", st.path, f"stamp for `{unit}` has no unit any more "
                                                          f"(`topomark stamp --prune`)", unit))
        for a in self.areas:
            if only_area and a.name != only_area:
                continue
            rec = st.areas.get(a.name)
            has_units = any(u["area"] == a.name for u in self.units.values())
            if rec and rec.get("edges") != self.edges_hash(a.name):
                P.append(Problem("EDGES_CHANGED", a.file, "cross-area callers changed since review (review the data "
                                                          f"flow and cross-area sections, then `topomark stamp --edges {a.name}`)"))
            elif not rec and has_units:
                P.append(Problem("EDGES_MISSING", a.file, f"no cross-area stamp (`topomark stamp --edges {a.name}`)"))
        return P
