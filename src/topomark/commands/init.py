"""``topomark init``: detect the stack, propose areas, write the code-map skeleton.

``--dry-run`` prints the plan and writes nothing; it is what runs against other
people's repositories, so it must never touch the work tree. Without it, init
writes ``topomark.toml``, ``<docs_dir>/README.md`` (L0), ``<docs_dir>/_TEMPLATE.md``
and one skeleton area file per proposed area, and refuses (all or nothing) when
any of them exists unless ``--force``.

How areas are proposed
----------------------
The unit of a proposal is a directory that holds a project manifest
(``pyproject.toml``, ``package.json``, ``*.asmdef``...). Starting from each
top-level directory:

* a directory with a manifest of its own is one area;
* a directory with two or more children that contain manifests is split into
  its children (``product/`` → ``product/backend``, ``product/frontend``...);
* a directory where one child with manifests holds nearly all of the code is
  replaced by that child (``mobile/`` → ``mobile/app``);
* anything else is one area.

Code left over by a split (a parent's own files, small siblings) becomes an
area of its own when it is big enough, otherwise it joins one ``other`` area
whose scope lists those paths exactly. Areas with more than ``DIR_THRESHOLD``
files get ``granularity: dir``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from . import Result
from ._common import add

# --------------------------------------------------------------------------- tunables
MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.py", "package.json", "pubspec.yaml", "go.mod", "Cargo.toml", "build.gradle",
    "build.gradle.kts", "wrangler.jsonc", "wrangler.json", "wrangler.toml", "pom.xml", "Package.swift",
})
MANIFEST_SUFFIXES = (".asmdef", ".csproj")
# A non-root directory is split into its children when at least this many children hold a manifest
# and the directory has at least MIN_SPLIT_FILES code files (tiny trees stay one area).
MIN_MANIFEST_CHILDREN = 2
MIN_SPLIT_FILES = 10
# One manifest child holding this share of a directory's code replaces the directory.
DOMINANT_SHARE = 0.8
# Leftover code below this count joins the shared `other` area instead of getting an area of its own.
RESIDUAL_MIN = 5
# Never split deeper than this many path segments.
MAX_SPLIT_DEPTH = 4
# A test tree is one area even when its suites have their own manifests (Unity EditMode/PlayMode asmdefs).
TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__", "spec", "specs", "e2e"})
# More required files than this → granularity: dir (one row per directory, not per file).
DIR_THRESHOLD = 60
# With dir granularity, go one level deeper when a depth-1 unit holds this many files and this share.
DEEPEN_FILES = 150
DEEPEN_SHARE = 0.5

LANGUAGES = {
    ".py": "Python", ".pyi": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".cs": "C#", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".swift": "Swift",
    ".dart": "Dart", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++ header", ".cc": "C++", ".cpp": "C++",
    ".hpp": "C/C++ header", ".m": "Objective-C", ".mm": "Objective-C", ".sh": "Shell", ".bash": "Shell",
    ".zsh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".gradle": "Gradle", ".rb": "Ruby", ".php": "PHP",
    ".lua": "Lua", ".vue": "Vue", ".svelte": "Svelte",
}

# Generated files that need no row. Each is suggested only when it matches a file in the repo.
GENERATED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("**/l10n/app_localizations*.dart", "Flutter gen-l10n output"),
    ("*.g.dart", "Dart build_runner output"),
    ("*.freezed.dart", "Dart freezed output"),
    ("*.mocks.dart", "Dart mockito output"),
    ("*.pb.dart", "protobuf (Dart)"),
    ("*.pbenum.dart", "protobuf (Dart)"),
    ("*.pbjson.dart", "protobuf (Dart)"),
    ("*.pbserver.dart", "protobuf (Dart)"),
    ("GeneratedPluginRegistrant.*", "Flutter plugin registrant"),
    ("*.pb.go", "protobuf (Go)"),
    ("*_pb2.py", "protobuf (Python)"),
    ("*_pb2_grpc.py", "protobuf (Python)"),
    ("*.Designer.cs", "Visual Studio designer output"),
    ("worker-configuration.d.ts", "wrangler types output"),
    ("*.gen.ts", "generated TypeScript"),
)

RULE_FILE_NAMES = frozenset({"CLAUDE.md", "AGENTS.md", "REPO_MAP.md", "CODE.md", "ARCHITECTURE.md", "GEMINI.md",
                             ".cursorrules"})
RULE_DIRS = ("docs/_overview/",)
MAX_RULE_FILES = 25          # listed in L0
MAX_AREA_RULE_FILES = 12     # listed in one area file

TEXT = {
    "rules_head": "Rules and decisions live in these files; the code map links them instead of restating them:",
    "rules_none": "No rule files (CLAUDE.md, AGENTS.md, ARCHITECTURE.md...) were found; link them here when "
                  "they exist instead of restating their content in area files.",
    "summary_todo": "TODO: one line on what this area owns",
    "unit_file": "file",
    "unit_dir": "unit",
    "reading_none": "- <docs that explain this area, one line each>",
    "rule_in_area": "rules for this area",
    "more_rules": "- … {n} more rule files deeper in {scope}",
    "other_title": "Other files",
    "other_summary": "top-level files and small leftovers that belong to no other area",
    "languages": "Languages (code files):",
    "manifests": "Project manifests:",
    "none": "(none)",
}


def register(sub, common) -> None:
    p = add(sub, common, "init", "detect the stack and write a code-map skeleton (use --dry-run first)",
            "Detects languages and project manifests, proposes areas (one per directory that holds a\n"
            "manifest, otherwise per top-level source directory), suggests excludes for generated files and\n"
            "links existing rule files (CLAUDE.md, AGENTS.md, ARCHITECTURE.md...) from L0 instead of copying\n"
            "them. Writes topomark.toml, <docs_dir>/README.md, <docs_dir>/_TEMPLATE.md and one skeleton file\n"
            "per area. --dry-run prints the plan and writes nothing.",
            "examples:\n"
            "  topomark init --dry-run                  # the plan, nothing written\n"
            "  topomark init                            # write it (refuses to overwrite)\n"
            "  topomark init --docs-dir docs/map        # somewhere other than docs/codemap\n"
            "  topomark draft backend --write           # then fill each area's file table")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    p.add_argument("--docs-dir", metavar="DIR", help="where the code map lives (default: config, else docs/codemap)")
    p.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p.set_defaults(handler=run)


# --------------------------------------------------------------------------- data model
@dataclass
class Proposal:
    path: str                       # directory with trailing "/", or "" for the `other` bucket
    files: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    name: str = ""
    title: str = ""
    summary: str = ""
    granularity: str = "file"
    depth: int = 1
    manifest: str = ""
    rules: list[str] = field(default_factory=list)
    more_rules: int = 0

    def to_json(self, docs_dir: str) -> dict:
        d = {"name": self.name, "file": f"{docs_dir}/{self.name}.md", "title": self.title, "summary": self.summary,
             "scope": self.scope, "files": len(self.files), "granularity": self.granularity}
        if self.granularity == "dir":
            d["depth"] = self.depth
        if self.manifest:
            d["manifest"] = self.manifest
        if self.rules:
            d["rules"] = self.rules
        return d


def is_manifest(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base in MANIFEST_NAMES or base.endswith(MANIFEST_SUFFIXES)


def parent_dir(path: str) -> str:
    return path.rsplit("/", 1)[0] + "/" if "/" in path else ""


# --------------------------------------------------------------------------- proposing areas
class Planner:
    def __init__(self, code: list[str], manifests: list[str]) -> None:
        self.code = sorted(code)
        self.manifest_dirs: dict[str, str] = {}
        for m in sorted(manifests, key=lambda x: (x.count("/"), x)):
            self.manifest_dirs.setdefault(parent_dir(m), m)
        self.areas: list[Proposal] = []
        self.other: list[str] = []          # scope entries for the `other` area
        self.other_files: list[str] = []

    def under(self, d: str) -> list[str]:
        return [f for f in self.code if f.startswith(d)]

    def children(self, d: str, files: list[str]) -> dict[str, list[str]]:
        kids: dict[str, list[str]] = {}
        for f in files:
            rest = f[len(d):]
            if "/" in rest:
                kids.setdefault(d + rest.split("/", 1)[0] + "/", []).append(f)
        return kids

    def contains_manifest(self, d: str) -> bool:
        return any(m.startswith(d) for m in self.manifest_dirs)

    def run(self) -> None:
        kids = self.children("", self.code)
        for kid in sorted(kids):
            self.propose(kid)
        self.residual([f for f in self.code if "/" not in f], {})

    def propose(self, d: str) -> None:
        files = self.under(d)
        if not files:
            return
        if (d in self.manifest_dirs or d.count("/") >= MAX_SPLIT_DEPTH
                or d.rstrip("/").rsplit("/", 1)[-1].lower() in TEST_DIR_NAMES):
            self.area(d, files)
            return
        kids = self.children(d, files)
        mkids = [k for k in sorted(kids) if self.contains_manifest(k)]
        if len(mkids) >= MIN_MANIFEST_CHILDREN and len(files) >= MIN_SPLIT_FILES:
            for kid in sorted(kids):
                self.propose(kid)
            self.residual([f for f in files if "/" not in f[len(d):]], {}, parent=d)
            return
        if len(mkids) == 1 and len(kids[mkids[0]]) >= DOMINANT_SHARE * len(files):
            self.propose(mkids[0])
            rest = [f for f in files if not f.startswith(mkids[0])]
            self.residual(rest, {k: v for k, v in kids.items() if k != mkids[0]}, parent=d)
            return
        self.area(d, files)

    def residual(self, files: list[str], kid_dirs: dict[str, list[str]], parent: str = "") -> None:
        """Code a split left behind: an area of its own if big enough, else the `other` bucket."""
        if not files:
            return
        if parent and len(files) >= RESIDUAL_MIN:
            self.area(parent, files)
            return
        covered = set()
        for kd, kf in sorted(kid_dirs.items()):
            self.other.append(kd)
            covered |= set(kf)
        for f in files:
            if f not in covered:
                self.other.append(f)
        self.other_files += files

    def area(self, d: str, files: list[str]) -> None:
        p = Proposal(path=d, files=files, scope=[d], manifest=self.manifest_dirs.get(d, ""))
        self.areas.append(p)

    def proposals(self) -> list[Proposal]:
        out = list(self.areas)
        if self.other_files:
            out.append(Proposal(path="", files=sorted(self.other_files), scope=sorted(set(self.other))))
        return out


def choose_granularity(p: Proposal) -> None:
    n = len(p.files)
    if n <= DIR_THRESHOLD or not p.path:
        return
    p.granularity, p.depth = "dir", 1
    root = p.path
    units = Counter()
    for f in p.files:
        dirs = f[len(root):].split("/")[:-1]
        units["/".join(dirs[:1])] += 1
    biggest, count = units.most_common(1)[0]
    if biggest and count >= DEEPEN_FILES and count >= DEEPEN_SHARE * n:
        p.depth = 2


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "area"


def name_areas(props: list[Proposal]) -> None:
    taken: set[str] = {"readme"}
    for p in props:
        if not p.path:
            continue
        parts = p.path.rstrip("/").split("/")
        name = slug(parts[-1])
        k = 2
        while name in taken and k <= len(parts):
            name = slug("-".join(parts[-k:]))
            k += 1
        base, n = name, 2
        while name in taken:
            name, n = f"{base}-{n}", n + 1
        taken.add(name)
        p.name = name
    for p in props:
        if not p.path:
            name, n = "other", 2
            while name in taken:
                name, n = f"other-{n}", n + 1
            taken.add(name)
            p.name = name


# --------------------------------------------------------------------------- summaries
# Descriptions that tools write by default and that say nothing about the project.
_BOILERPLATE = re.compile(r"^(a new flutter (project|module|package|plugin)\.?|todo|description|"
                          r"add your description here)$", re.I)


def _clean(s: str, limit: int = 160) -> str:
    s = re.sub(r"\s+", " ", s.replace("|", "/")).strip()
    s = s.strip("#>*-_ `").replace("`", "'")
    if _BOILERPLATE.match(s):
        return ""
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def manifest_summary(ctx, path: str) -> str:
    try:
        text = ctx.read(path)
    except Exception:  # noqa: BLE001 - a broken manifest must never stop init
        return ""
    base = path.rsplit("/", 1)[-1]
    try:
        if base == "package.json":
            d = json.loads(text)
            return _clean(str(d.get("description") or "")) if isinstance(d, dict) else ""
        if base == "pyproject.toml":
            import tomllib

            d = tomllib.loads(text)
            proj = d.get("project") or d.get("tool", {}).get("poetry") or {}
            return _clean(str(proj.get("description") or ""))
        if base == "Cargo.toml":
            import tomllib

            return _clean(str(tomllib.loads(text).get("package", {}).get("description") or ""))
        if base == "pubspec.yaml":
            m = re.search(r"^description:\s*[\"']?(.+?)[\"']?\s*$", text, re.M)
            return _clean(m.group(1)) if m else ""
    except (ValueError, AttributeError, TypeError):
        return ""
    return ""


def readme_summary(ctx, d: str, files_all: set[str]) -> str:
    for name in ("README.md", "readme.md", "README.markdown", "README"):
        path = d + name
        if path not in files_all:
            continue
        try:
            text = ctx.read(path)
        except Exception:  # noqa: BLE001
            return ""
        if text.startswith("---\n"):
            end = text.find("\n---", 4)
            text = text[end + 4:] if end > 0 else text
        in_code = in_comment = False
        for line in text.split("\n"):
            st = line.strip()
            if st.startswith("```"):
                in_code = not in_code
                continue
            if in_comment:
                in_comment = "-->" not in st
                continue
            if st.startswith("<!--"):
                in_comment = "-->" not in st
                continue
            if in_code or not st or st.startswith(("#", "<", "!", "[!", "|", "---", "===", ">")):
                continue
            if re.match(r"^[A-Za-z_][\w-]*:(\s|$)", st):
                continue  # metadata such as `last_audited: 2026-09-12`
            if st.startswith("[") and "](" in st and st.endswith(")"):
                continue  # a badge or a lone link
            st = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", st)
            return _clean(re.sub(r"[*`]", "", st))
    return ""


# --------------------------------------------------------------------------- rendering
def template(name: str) -> str:
    from importlib import resources

    return resources.files("topomark.templates").joinpath(name).read_text(encoding="utf-8")


def render(text: str, **values: str) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def frontmatter(p: Proposal) -> str:
    lines = ["---", f"area: {p.name}", f"title: {p.title}", f"summary: {p.summary}", f"granularity: {p.granularity}"]
    if p.granularity == "dir":
        lines.append(f"depth: {p.depth}")
    lines.append("scope:")
    lines += [f"  - {s}" for s in p.scope]
    lines.append("---")
    return "\n".join(lines) + "\n"


def toml_config(docs_dir: str, excludes: list[tuple[str, str]]) -> str:
    out = ["# topomark configuration (https://github.com/tipoLi5890/topomark).",
           "# Areas are not configured here: each area file's frontmatter (scope, granularity) is the",
           "# single source of truth. Every key is optional; see docs/config.md in the topomark repo.",
           "", "[topomark]", f"docs_dir = {json.dumps(docs_dir)}"]
    if excludes:
        out += ["", "[files]", "# Added to the built-in excludes (node_modules/, build/, dist/, *.min.js, ...).",
                "exclude = ["]
        out += [f"  {json.dumps(pat)},  # {why}" for pat, why in excludes]
        out.append("]")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- the command
def build_plan(ctx, docs_dir: str) -> dict:
    from ..config import Config
    from ..docs import is_required, owner_of, Area
    from ..repo import matches_any

    cfg = ctx.config
    files = ctx.files
    all_set = set(files)
    # 1. excludes: generated files and code inside dot-directories (agent tooling, CI glue)
    excludes: list[tuple[str, str]] = []
    have = set(cfg.exclude)
    for pat, why in GENERATED_PATTERNS:
        if pat not in have and any(matches_any(f, (pat,)) for f in files):
            excludes.append((pat, why))
    probe = Config(root=ctx.root, docs_dir=docs_dir, required_roots=cfg.required_roots,
                   required_ext=cfg.required_ext, every_file_roots=cfg.every_file_roots)
    required = [f for f in files if is_required(f, probe)]
    dot_dirs = sorted({f.split("/", 1)[0] + "/" for f in required if f.startswith(".") and "/" in f})
    for d in dot_dirs:
        if d not in have:
            excludes.append((d, "tooling in a dot-directory, not product code"))
    ex = tuple(p for p, _ in excludes)
    required = [f for f in required if not matches_any(f, ex)]
    kept = [f for f in files if not matches_any(f, ex)]

    # 2. stack
    langs: Counter = Counter()
    for f in required:
        low = f.lower()
        dot = low.rfind(".")
        if dot > low.rfind("/"):
            langs[LANGUAGES.get(low[dot:], low[dot:])] += 1
    manifests = [f for f in kept if is_manifest(f)]

    # 3. rule files to link
    rules = [f for f in kept if f.rsplit("/", 1)[-1] in RULE_FILE_NAMES]
    for d in RULE_DIRS:
        if any(f.startswith(d) for f in kept):
            rules.append(d)
    rules.sort(key=lambda x: (x.count("/"), x))

    # 4. areas
    planner = Planner(required, manifests)
    planner.run()
    props = planner.proposals()
    name_areas(props)
    T = TEXT
    for p in props:
        choose_granularity(p)
        if p.path:
            p.title = p.path.rstrip("/")
            p.summary = ((manifest_summary(ctx, p.manifest) if p.manifest else "")
                         or readme_summary(ctx, p.path, all_set) or T["summary_todo"])
            inside = [r for r in rules if r.startswith(p.path) and not r.endswith("/")]
            p.rules = inside[:MAX_AREA_RULE_FILES]
            p.more_rules = len(inside) - len(p.rules)
        else:
            p.title, p.summary = T["other_title"], T["other_summary"]
    # self-check: every required file has exactly one owner
    areas = [Area(name=p.name, file="", scope=p.scope) for p in props]
    unowned = [f for f in required if owner_of(f, areas)[0] is None]
    conflicts = [f for f in required if len(owner_of(f, areas)[1]) > 1]
    roots = {p.path for p in props if p.path}
    l0_rules = [r for r in rules if r.endswith("/") or parent_dir(r).count("/") <= 1 or parent_dir(r) in roots
                or any(r.startswith(d) for d in RULE_DIRS)]
    return {"files": files, "required": required, "l0_rules": l0_rules, "excludes": excludes, "langs": langs, "manifests": manifests,
            "rules": rules, "props": props, "unowned": unowned, "conflicts": conflicts}


def render_docs(plan: dict, docs_dir: str, cfg) -> dict[str, str]:
    """Render every file; shorten L0's lists until it fits `l0_max` (it never starts over its cap)."""
    out: dict[str, str] = {}
    for caps in ((MAX_RULE_FILES, 20, 12), (12, 8, 8), (6, 4, 5), (3, 0, 3)):
        out = _render_docs(plan, docs_dir, cfg, *caps)
        if out[f"{docs_dir}/README.md"].count("\n") <= cfg.l0_max:
            break
    return out


def _render_docs(plan: dict, docs_dir: str, cfg, max_rules: int, max_manifests: int,
                 max_langs: int) -> dict[str, str]:
    T = TEXT
    props: list[Proposal] = plan["props"]
    rules: list[str] = plan["l0_rules"]
    out: dict[str, str] = {}
    if rules:
        shown = rules[:max_rules]
        rule_text = T["rules_head"] + "\n\n" + "\n".join(f"- `{r}`" for r in shown)
        if len(rules) > len(shown):
            rule_text += f"\n- … {len(rules) - len(shown)}"
    else:
        rule_text = T["rules_none"]
    rows = []
    for p in props:
        scope = ", ".join(f"`{s}`" for s in p.scope[:4]) + (" …" if len(p.scope) > 4 else "")
        rows.append(f"| {p.name} | [{p.name}.md]({p.name}.md) | {p.summary} | {scope} |")
    langs = plan["langs"]
    stack = [T["languages"], ""]
    stack += [f"- {k}: {v}" for k, v in langs.most_common(max_langs)] or [f"- {T['none']}"]
    stack += ["", T["manifests"], ""]
    mans = plan["manifests"]
    stack += [f"- `{m}`" for m in mans[:max_manifests]] or [f"- {T['none']}"]
    if len(mans) > max_manifests:
        stack.append(f"- … {len(mans) - max_manifests}")
    values = {"docs_dir": docs_dir, "l0_max": str(cfg.l0_max), "l1_max": str(cfg.l1_max)}
    out[f"{docs_dir}/README.md"] = render(template("L0.md"), rule_sources=rule_text,
                                          areas_table="\n".join(rows), stack="\n".join(stack), **values)
    out[f"{docs_dir}/_TEMPLATE.md"] = render(template("_TEMPLATE.md"), **values)
    area_t = template("area.md")
    for p in props:
        reading = "\n".join(f"- `{r}`: {T['rule_in_area']}" for r in p.rules) or T["reading_none"]
        if p.more_rules:
            reading += "\n" + T["more_rules"].format(n=p.more_rules, scope=p.path)
        out[f"{docs_dir}/{p.name}.md"] = render(area_t, frontmatter=frontmatter(p), title=p.title,
                                                summary=p.summary, reading=reading,
                                                unit_header=T["unit_dir" if p.granularity == "dir" else "unit_file"],
                                                **values)
    return out


def run(args, ctx) -> Result:
    from ..contract import CONFIG_FILE
    from ..errors import TopomarkError
    from ..repo import outside, write_text

    cfg = ctx.config
    docs_dir = (args.docs_dir or cfg.docs_dir).strip("/").replace("\\", "/")
    if outside(docs_dir):
        raise TopomarkError("USAGE", f"--docs-dir must be a folder inside the repository, not {docs_dir!r}")
    plan = build_plan(ctx, docs_dir)
    writes = {CONFIG_FILE: toml_config(docs_dir, plan["excludes"])}
    writes.update(render_docs(plan, docs_dir, cfg))
    existing = [p for p in writes if (ctx.root / p).exists()]
    l0_lines = writes[f"{docs_dir}/README.md"].count("\n")
    props: list[Proposal] = plan["props"]

    data = {
        "dry_run": bool(args.dry_run), "root": str(ctx.root), "lang": "en", "docs_dir": docs_dir,
        "stack": {"languages": dict(plan["langs"].most_common()), "manifests": plan["manifests"]},
        "rule_files": plan["rules"], "rule_files_l0": plan["l0_rules"], "excludes": [{"pattern": p, "reason": w} for p, w in plan["excludes"]],
        "areas": [p.to_json(docs_dir) for p in props], "required_files": len(plan["required"]),
        "unowned": plan["unowned"], "conflicts": plan["conflicts"],
        "writes": [{"path": p, "exists": p in existing} for p in writes], "written": [], "l0_lines": l0_lines,
    }
    lines = [f"topomark init{' --dry-run (nothing written)' if args.dry_run else ''}: {ctx.root}"]
    lines.append("stack: " + (", ".join(f"{k} {v}" for k, v in plan["langs"].most_common(8)) or "no code files"))
    if plan["manifests"]:
        shown = plan["manifests"][:8]
        lines.append(f"manifests ({len(plan['manifests'])}): " + ", ".join(shown)
                     + (" …" if len(plan["manifests"]) > len(shown) else ""))
    if plan["rules"]:
        l0r = plan["l0_rules"]
        lines.append(f"rule files: {len(plan['rules'])} found, {len(l0r)} linked from L0 (the rest from their "
                     f"area files): " + ", ".join(l0r[:8]) + (" …" if len(l0r) > 8 else ""))
    lines.append(f"proposed areas ({len(props)}, {len(plan['required'])} code files):")
    w = max([len(p.name) for p in props] + [4])
    for p in props:
        scope = p.scope[0] if len(p.scope) == 1 else f"{len(p.scope)} paths"
        gran = f"dir depth {p.depth}" if p.granularity == "dir" else "file"
        lines.append(f"  {p.name:<{w}}  {scope:<36} {len(p.files):>5} files  {gran:<11}  {p.summary[:60]}")
    if plan["excludes"]:
        lines.append("excludes to add:")
        lines += [f"  {p:<36} {why}" for p, why in plan["excludes"]]
    if l0_lines > cfg.l0_max:
        lines.append(f"warning: L0 is {l0_lines} lines, over l0_max {cfg.l0_max}: merge small areas or raise l0_max")
    if plan["unowned"] or plan["conflicts"]:
        lines.append(f"warning: {len(plan['unowned'])} unowned, {len(plan['conflicts'])} conflicting files")
    lines.append("would write:" if args.dry_run else "writes:")
    for p in writes:
        lines.append(f"  {p}" + ("  (exists: needs --force)" if p in existing and not args.force else
                                 "  (exists: overwrite)" if p in existing else ""))

    if args.dry_run:
        lines.append("dry run: nothing was written. Edit the plan by hand after `topomark init`, or rerun "
                     "with --docs-dir.")
        return Result(data, "\n".join(lines))
    if existing and not args.force:
        raise TopomarkError("REFUSED", "these files exist, nothing was written: " + ", ".join(existing)
                            + " (add --force to overwrite them)")
    # An existing topomark.toml is hand-tuned (test runners, excludes): --force never replaces it.
    if CONFIG_FILE in writes and (ctx.root / CONFIG_FILE).is_file():
        writes = {k: v for k, v in writes.items() if k != CONFIG_FILE}
        lines.append(f"kept the existing {CONFIG_FILE} (init never overwrites it; edit it by hand)")
    for path, text in writes.items():
        write_text(ctx.root, path, text)
    data["written"] = list(writes)
    first = props[0].name if props else "<area>"
    lines += ["next:",
              f"  topomark draft {first} --write   # per area: rows with summary and fan-in prefilled; then correct them",
              "  topomark gen                     # the generated fan-in table and module graph",
              "  topomark sync && topomark stamp --baseline   # after the rows are written and read",
              "  topomark check"]
    return Result(data, "\n".join(lines))
