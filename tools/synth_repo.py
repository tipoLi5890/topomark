#!/usr/bin/env python3
"""Generate a deterministic synthetic multi-language git repository for benchmarks and evals.

    python3 tools/synth_repo.py OUT_DIR [--files 3000] [--seed 1]

The repo imitates a mid-size product monorepo (Pilot B in docs/pilots.md: Python plus
TS/TSX, a little JS, Go and C#, Markdown docs): modules of ~150-250 lines that
import a few earlier modules (biased toward hubs, so fan-in is skewed), with a
test file for about one module in four. Same ``--files`` and ``--seed`` → same
repo, byte for byte.

Fixed files exist at every size; ``tools/eval/tasks.toml`` and
``tools/bench_nav.py`` refer to them:

* ``py/chain/leaf.py`` → ``mid.py`` → ``top.py``; only ``tests/py/test_chain.py``
  tests them, through ``ChainTop`` (an import chain for ``tests-for``).
* ``ts/chain/leaf.ts`` → ``mid.ts`` → ``top.ts`` → ``index.ts`` (barrel);
  ``tests/ts/chain.test.ts`` imports the barrel.
* ``py/plugins/loader.py`` (``importlib.import_module``) and
  ``ts/lazy/routes.ts`` (``import(`./pages/${name}`)``): dynamic loading.
* ``py/core/hub.py`` (``CoreHub``) and ``ts/core/hub.ts`` (``CoreHubStore``):
  imported by many modules.
* ``py/big/monolith.py`` (~3,600 lines) and ``ts/big/monolith.ts`` (~3,000 lines).

The commit runs none of the user's git hooks (``core.hooksPath`` is pointed at
``/dev/null`` and ``--no-verify`` is passed) and names the branch ``main`` without
``git init -b``, which needs git 2.28. Stdlib only; writes nothing outside OUT_DIR.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

NOUNS = ["Invoice", "User", "Order", "Payment", "Session", "Photo", "Album", "Report", "Token", "Device",
         "Camera", "Model", "Queue", "Upload", "Billing", "Account", "Profile", "Search", "Index", "Cache",
         "Route", "Config", "Metric", "Alert", "Job", "Worker", "Stream", "Frame", "Label", "Batch",
         "Ledger", "Tenant", "Webhook", "Quota", "Thumbnail", "Asset", "Schedule", "Printer", "Coupon", "Locale"]
SUFFIXES = ["Service", "Repository", "Manager", "Controller", "Handler", "Store", "Client", "Builder",
            "Parser", "Validator", "Mapper", "Adapter"]
VERBS = ["load", "save", "process", "render", "validate", "compute", "update", "fetch", "handle", "transform",
         "build", "parse", "apply", "resolve", "merge", "filter", "export", "refresh", "archive", "notify"]
# One slot per 5%: py 45, ts 30, tsx 10, js 5, go 5, cs 5.
SCHEDULE = ["py"] * 9 + ["ts"] * 6 + ["tsx"] * 2 + ["js", "go", "cs"]


def snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def camel(name: str) -> str:
    return name[:1].lower() + name[1:]


class Module:
    def __init__(self, lang: str, path: str, cls: str, func: str, const: str, import_path: str) -> None:
        self.lang = lang
        self.path = path
        self.cls = cls          # main type
        self.func = func        # top-level helper
        self.const = const
        self.import_path = import_path  # dotted (py) or path without extension (ts/js)
        self.methods: list[str] = []


class Generator:
    def __init__(self, files: int, seed: int) -> None:
        self.target = files
        self.rng = random.Random(seed)
        self.out: dict[str, str] = {}
        self.used: set[str] = set()
        self.mods: dict[str, list[Module]] = {k: [] for k in ("py", "ts", "js", "go", "cs")}

    # ------------------------------------------------------------ names
    def unique(self, base: str) -> str:
        name, k = base, 2
        while name in self.used:
            name, k = f"{base}{k}", k + 1
        self.used.add(name)
        return name

    def type_name(self) -> str:
        return self.unique(self.rng.choice(NOUNS) + self.rng.choice(SUFFIXES))

    def pick_imports(self, pool: list[Module], n: int) -> list[Module]:
        """Earlier modules, biased toward low indices (hubs get most of the fan-in)."""
        if not pool:
            return []
        out: list[Module] = []
        for _ in range(n):
            k = int(len(pool) * (self.rng.random() ** 2.5))
            m = pool[min(k, len(pool) - 1)]
            if m not in out:
                out.append(m)
        return out

    def methods(self, n: int, noun: str) -> list[str]:
        names: list[str] = []
        while len(names) < n:
            v = self.rng.choice(VERBS)
            o = self.rng.choice(NOUNS)
            name = f"{v}_{snake(o)}" if self.rng.random() < 0.7 else f"{v}_{snake(noun)}_{snake(o)}"
            if name not in names:
                names.append(name)
        return names

    # ------------------------------------------------------------ python
    def py_module(self, j: int) -> None:
        pkg = j // 25
        cls = self.type_name()
        func = self.unique(snake(cls) + "_factory")
        const = self.unique(snake(cls).upper() + "_LIMIT")
        dotted = f"py.pkg{pkg:02d}.mod_{j:03d}"
        m = Module("py", f"py/pkg{pkg:02d}/mod_{j:03d}.py", cls, func, const, dotted)
        deps = self.pick_imports(self.mods["py"], self.rng.randint(2, 4))
        hub = self.rng.random() < 0.35
        lines = [f'"""{cls}: synthetic module {j} in package {pkg}.', "",
                 f"Coordinates {snake(cls).replace('_', ' ')} work for the pipeline.", '"""', "",
                 "from __future__ import annotations", "", "import os", "from dataclasses import dataclass"]
        if hub:
            lines.append("from py.core.hub import CoreHub")
        for d in deps:
            lines.append(f"from {d.import_path} import {d.cls}, {d.func}")
        lines += ["", f"{const} = {self.rng.randint(5, 500)}", f"_PRIVATE_{j} = {j}", "", "",
                  "@dataclass", f"class {cls}Options:", f'    """Options for {cls}."""', "",
                  "    name: str = \"default\"", "    limit: int = 10", "    verbose: bool = False", "", ""]
        lines += [f"class {cls}:", f'    """{cls} keeps state for one request."""', "",
                  "    def __init__(self, options=None) -> None:",
                  f"        self.options = options or {cls}Options()", "        self._seen: set[str] = set()",
                  "        self._cache: dict[str, int] = {}"]
        if hub:
            lines.append("        self.hub = CoreHub()")
        lines.append("")
        m.methods = self.methods(self.rng.randint(10, 17), cls)
        for k, meth in enumerate(m.methods):
            dep = deps[k % len(deps)] if deps else None
            call = f"{dep.cls}().{dep.methods[k % len(dep.methods)]}(items)" if dep and dep.methods else "len(items)"
            lines += [f"    def {meth}(self, items: list[dict], limit: int = {k + 3}) -> dict:",
                      f'        """{meth.replace("_", " ").capitalize()} for the current batch."""',
                      "        result: dict = {}",
                      "        for idx, item in enumerate(items[:limit]):",
                      "            key = str(item.get(\"id\", idx))",
                      "            if key in self._seen:",
                      "                continue",
                      "            self._seen.add(key)",
                      f"            result[key] = idx * {k + 1}",
                      f"        if len(result) > {const}:",
                      f"            result[\"overflow\"] = {call}",
                      "        return result", ""]
        lines += ["    def _private_reset(self) -> None:", "        self._seen.clear()", "        self._cache.clear()",
                  "", ""]
        lines += [f"def {func}(path: str = \"\") -> {cls}:", f'    """Build a {cls} from the environment."""',
                  f"    opts = {cls}Options(name=os.environ.get(\"APP_NAME\", path or \"x\"))"]
        for d in deps[:2]:
            lines.append(f"    {d.func}(path)")
        lines += [f"    return {cls}(opts)", ""]
        self.out[m.path] = "\n".join(lines)
        self.mods["py"].append(m)
        if j % 4 == 0:
            self.py_test(m)

    def py_test(self, m: Module) -> None:
        name = m.path.split("/")[-1]
        pkg = m.path.split("/")[1]
        lines = ["import unittest", "", f"from {m.import_path} import {m.cls}, {m.func}", "", "",
                 f"class Test{m.cls}(unittest.TestCase):"]
        for meth in m.methods[:4]:
            lines += [f"    def test_{meth}(self):", f"        obj = {m.cls}()",
                      f"        self.assertEqual(obj.{meth}([]), {{}})", ""]
        lines += ["    def test_factory(self):", f"        self.assertIsNotNone({m.func}())", ""]
        self.out[f"tests/py/{pkg}/test_{name}"] = "\n".join(lines)

    # ------------------------------------------------------------ typescript
    def ts_module(self, j: int, tsx: bool) -> None:
        feat = j // 20
        cls = self.type_name()
        base = camel(cls)
        func = self.unique(f"create{cls}")
        const = self.unique(snake(cls).upper() + "_MAX")
        rel = f"ts/feat{feat:02d}/{base}"
        m = Module("ts", rel + (".tsx" if tsx else ".ts"), cls, func, const, rel)
        deps = self.pick_imports(self.mods["ts"], self.rng.randint(2, 4))
        hub = self.rng.random() < 0.35
        lines = [f"// {cls}: synthetic feature module {j}.", f"// Keeps {base} state for the dashboard.", ""]
        if tsx:
            lines.append('import React from "react";')
        if hub:
            lines.append('import { CoreHubStore } from "../core/hub";')
        for d in deps:
            up = "../" + d.import_path.split("/", 1)[1]
            lines.append(f'import {{ {d.cls}, {d.func} }} from "{up}";')
        lines += ["", f"export const {const} = {self.rng.randint(5, 500)};", "",
                  f"export interface {cls}Props {{", "  id: string;", "  count: number;", "  label?: string;", "}", "",
                  f"export class {cls} {{", "  private items: Map<string, number> = new Map();",
                  "  private seen = new Set<string>();", ""]
        m.methods = [camel("".join(p.capitalize() for p in s.split("_"))) for s in self.methods(self.rng.randint(9, 15), cls)]
        for k, meth in enumerate(m.methods):
            dep = deps[k % len(deps)] if deps else None
            call = f"new {dep.cls}().{dep.methods[k % len(dep.methods)]}(values)" if dep and dep.methods else "values.length"
            lines += [f"  {meth}(values: number[], limit = {k + 3}): number {{",
                      "    let total = 0;",
                      "    for (let i = 0; i < Math.min(limit, values.length); i++) {",
                      "      const key = String(values[i]);",
                      "      if (this.seen.has(key)) {",
                      "        continue;",
                      "      }",
                      "      this.seen.add(key);",
                      f"      total += values[i] * {k + 1};",
                      "    }",
                      f"    if (total > {const}) {{",
                      f"      return {call};",
                      "    }",
                      "    return total;",
                      "  }", ""]
        lines += ["}", "", f"export function {func}(props: {cls}Props): {cls} {{",
                  f"  const out = new {cls}();"]
        for d in deps[:2]:
            lines.append(f"  {d.func}({{ id: props.id, count: props.count }});")
        if hub:
            lines.append("  new CoreHubStore().register(props.id);")
        lines += ["  return out;", "}", ""]
        if tsx:
            lines += [f"export function {cls}View(props: {cls}Props) {{",
                      f"  const store = {func}(props);",
                      "  return (",
                      '    <div className="panel">',
                      "      <span>{props.label ?? props.id}</span>",
                      f"      <b>{{store.{m.methods[0]}([props.count])}}</b>",
                      "    </div>",
                      "  );", "}", ""]
        self.out[m.path] = "\n".join(lines)
        self.mods["ts"].append(m)
        if j % 4 == 0:
            self.ts_test(m)

    def ts_test(self, m: Module) -> None:
        feat = m.path.split("/")[1]
        stem = m.path.split("/")[-1].rsplit(".", 1)[0]
        lines = [f'import {{ {m.cls}, {m.func} }} from "../../../{m.import_path}";', "",
                 f'describe("{m.cls}", () => {{']
        for meth in m.methods[:3]:
            lines += [f'  it("{meth}", () => {{', f"    expect(new {m.cls}().{meth}([])).toBe(0);", "  });"]
        lines += ['  it("creates", () => {', f'    expect({m.func}({{ id: "a", count: 1 }})).toBeTruthy();', "  });",
                  "});", ""]
        self.out[f"tests/ts/{feat}/{stem}.test.ts"] = "\n".join(lines)

    # ------------------------------------------------------------ js, go, c#, docs
    def js_module(self, j: int) -> None:
        cls = self.type_name()
        func = self.unique(f"make{cls}")
        path = f"js/legacy{j // 15:02d}/{camel(cls)}.js"
        lines = ["// Legacy CommonJS helper.", "'use strict';", "", "const path = require('path');", "",
                 f"class {cls} {{", "  constructor(root) {", "    this.root = root;", "    this.items = [];", "  }", ""]
        for meth in self.methods(self.rng.randint(5, 9), cls):
            name = camel("".join(p.capitalize() for p in meth.split("_")))
            lines += [f"  {name}(value) {{", "    const out = [];", "    for (const item of this.items) {",
                      "      if (item && item.value === value) {", "        out.push(path.join(this.root, String(item.id)));",
                      "      }", "    }", "    return out;", "  }", ""]
        lines += ["}", "", f"function {func}(root) {{", f"  return new {cls}(root);", "}", "",
                  f"module.exports = {{ {cls}, {func} }};", ""]
        self.out[path] = "\n".join(lines)

    def go_module(self, j: int) -> None:
        cls = self.type_name()
        pkg = f"svc{j // 10:02d}"
        lines = [f"// Package {pkg} serves {cls}.", f"package {pkg}", "", "import (", '\t"fmt"', '\t"strings"', ")", "",
                 f"// {cls} handles one request.", f"type {cls} struct {{", "\tName  string", "\tCount int",
                 "\tparts []string", "}", ""]
        for meth in self.methods(self.rng.randint(5, 9), cls):
            name = "".join(p.capitalize() for p in meth.split("_"))
            lines += [f"// {name} joins the parts.", f"func (h *{cls}) {name}(items []string) string {{",
                      "\tvar b strings.Builder", "\tfor i, it := range items {", "\t\tif i > h.Count {", "\t\t\tbreak",
                      "\t\t}", '\t\tb.WriteString(fmt.Sprintf("%s:%d", it, i))', "\t}", "\treturn b.String()", "}", ""]
        lines += [f"// New{cls} builds a {cls}.", f"func New{cls}(name string) *{cls} {{",
                  f"\treturn &{cls}{{Name: name}}", "}", ""]
        self.out[f"go/{pkg}/{snake(cls)}.go"] = "\n".join(lines)

    def cs_module(self, j: int) -> None:
        cls = self.type_name()
        ns = f"Game.Module{j // 10:02d}"
        lines = ["using System;", "using System.Collections.Generic;", "", f"namespace {ns}", "{",
                 f"    /// <summary>{cls} for the game loop.</summary>", f"    public class {cls}", "    {",
                 f"        public const int Limit = {self.rng.randint(2, 99)};",
                 "        private readonly List<int> _items = new List<int>();", ""]
        for meth in self.methods(self.rng.randint(5, 9), cls):
            name = "".join(p.capitalize() for p in meth.split("_"))
            lines += [f"        public int {name}(IList<int> values)", "        {", "            var total = 0;",
                      "            foreach (var v in values)", "            {", "                if (v > Limit) continue;",
                      "                total += v;", "            }", "            return total;", "        }", ""]
        lines += ["    }", "}", ""]
        self.out[f"cs/Module{j // 10:02d}/{cls}.cs"] = "\n".join(lines)

    def doc(self, j: int) -> None:
        picks = self.rng.sample(self.mods["py"] + self.mods["ts"], min(4, len(self.mods["py"]) + len(self.mods["ts"])))
        lines = [f"# Topic {j}", "", "How the pieces fit together.", ""]
        for m in picks:
            lines += [f"## {m.cls}", "", f"`{m.cls}` lives in `{m.path}`; call `{m.func}` to build one.", ""]
        self.out[f"docs/topic_{j:03d}.md"] = "\n".join(lines)

    # ------------------------------------------------------------ fixed files
    def fixed(self) -> None:
        self.used.update({"CoreHub", "CoreHubStore", "ChainTop", "MonolithEngine", "MonolithBoard"})
        self.out["README.md"] = "# Synthetic repo\n\nGenerated by topomark's tools/synth_repo.py.\n"
        self.out["py/__init__.py"] = ""
        self.out["py/core/hub.py"] = "\n".join([
            '"""Core hub: shared registry every service reports to."""', "", "",
            "class CoreHub:", '    """Process-wide registry of named counters."""', "",
            "    def __init__(self) -> None:", "        self.counters: dict[str, int] = {}", "",
            "    def register(self, name: str) -> int:", "        self.counters[name] = self.counters.get(name, 0) + 1",
            "        return self.counters[name]", "",
            "    def snapshot(self) -> dict[str, int]:", "        return dict(self.counters)", ""])
        self.out["ts/core/hub.ts"] = "\n".join([
            "// Core hub store: shared registry every feature reports to.", "",
            "export class CoreHubStore {", "  private counters = new Map<string, number>();", "",
            "  register(name: string): number {", "    const n = (this.counters.get(name) ?? 0) + 1;",
            "    this.counters.set(name, n);", "    return n;", "  }", "}", ""])
        self.out["py/chain/__init__.py"] = ""
        self.out["py/chain/leaf.py"] = "\n".join([
            '"""Chain leaf: one function, reached by tests only through mid and top."""', "", "",
            "def chain_leaf_value(x: int) -> int:", "    return x * 2", ""])
        self.out["py/chain/mid.py"] = "\n".join([
            '"""Chain middle."""', "", "from py.chain.leaf import chain_leaf_value", "", "",
            "def chain_mid_value(x: int) -> int:", "    return chain_leaf_value(x) + 1", ""])
        self.out["py/chain/top.py"] = "\n".join([
            '"""Chain top: the only part the tests call."""', "", "from .mid import chain_mid_value", "", "",
            "class ChainTop:", "    def total(self, x: int) -> int:", "        return chain_mid_value(x) * 3", ""])
        self.out["tests/py/test_chain.py"] = "\n".join([
            "import unittest", "", "from py.chain.top import ChainTop", "", "",
            "class TestChainTop(unittest.TestCase):", "    def test_total(self):",
            "        self.assertEqual(ChainTop().total(1), 9)", ""])
        self.out["ts/chain/leaf.ts"] = "\n".join([
            "// Chain leaf: one function, reached by tests only through mid and top.", "",
            "export function chainLeafValue(x: number): number {", "  return x * 2;", "}", ""])
        self.out["ts/chain/mid.ts"] = "\n".join([
            'import { chainLeafValue } from "./leaf";', "",
            "export function chainMidValue(x: number): number {", "  return chainLeafValue(x) + 1;", "}", ""])
        self.out["ts/chain/top.ts"] = "\n".join([
            'import { chainMidValue } from "./mid.js";', "",
            "export class ChainTop {", "  total(x: number): number {", "    return chainMidValue(x) * 3;", "  }", "}", ""])
        self.out["ts/chain/index.ts"] = 'export * from "./top";\n'
        self.out["tests/ts/chain.test.ts"] = "\n".join([
            'import { ChainTop } from "../../ts/chain";', "",
            'describe("ChainTop", () => {', '  it("totals", () => {', "    expect(new ChainTop().total(1)).toBe(9);",
            "  });", "});", ""])
        self.out["py/plugins/__init__.py"] = ""
        self.out["py/plugins/loader.py"] = "\n".join([
            '"""Plugin loader: modules are found by name at run time."""', "", "import importlib", "", "",
            "def load_plugin(name: str):", '    return importlib.import_module(f"py.plugins.{name}")', ""])
        self.out["ts/lazy/routes.ts"] = "\n".join([
            "// Lazy routes: pages are loaded by name at run time.", "",
            "export const loadPage = (name: string) => import(`./pages/${name}`);", ""])
        big = ['"""Monolith: one very large module (outline benchmark)."""', "", "", "class MonolithEngine:",
               '    """Everything in one place."""', ""]
        for k in range(400):
            big += [f"    def step_{k:03d}(self, value: int) -> int:", f'        """Step {k}."""', "        total = value",
                    f"        for i in range({k % 7 + 2}):", "            total += i", "        if total % 2:",
                    "            total -= 1", "        return total", ""]
        self.out["py/big/monolith.py"] = "\n".join(big) + "\n"
        tsb = ["// Monolith board: one very large module (outline benchmark).", "", "export class MonolithBoard {"]
        for k in range(270):
            tsb += [f"  step{k:03d}(value: number): number {{", "    let total = value;",
                    f"    for (let i = 0; i < {k % 7 + 2}; i++) {{", "      total += i;", "    }",
                    "    if (total % 2) {", "      total -= 1;", "    }", "    return total;", "  }", ""]
        tsb += ["}", ""]
        self.out["ts/big/monolith.ts"] = "\n".join(tsb)

    # ------------------------------------------------------------ driver
    def run(self) -> dict[str, str]:
        self.fixed()
        counters = {k: 0 for k in ("py", "ts", "tsx", "js", "go", "cs")}
        i = 0
        while len(self.out) < self.target:
            lang = SCHEDULE[i % len(SCHEDULE)]
            n = counters[lang]
            counters[lang] += 1
            if lang == "py":
                self.py_module(n)
            elif lang in ("ts", "tsx"):
                self.ts_module(counters["ts"] + counters["tsx"] - 1, tsx=lang == "tsx")
            elif lang == "js":
                self.js_module(n)
            elif lang == "go":
                self.go_module(n)
            else:
                self.cs_module(n)
            i += 1
            if i % 30 == 0:
                self.doc(i // 30)
        return self.out


def generate(out_dir: Path, files: int = 3000, seed: int = 1, commit: bool = True) -> dict[str, int]:
    """Write the repo into ``out_dir`` (created; must be empty or absent) and commit it."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"synth_repo: {out_dir} is not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    content = Generator(files, seed).run()
    lines = 0
    for rel, text in sorted(content.items()):
        full = out_dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        lines += text.count("\n")
    if commit:
        commit_all(out_dir, "synthetic repo")
    return {"files": len(content), "lines": lines}


def commit_all(root: Path, message: str) -> None:
    """``git init`` ``root`` on branch ``main`` and commit every file in it, with a local identity,
    no signing and none of the user's hooks (``tools/bench_nav.py`` builds a scratch repo this way too)."""
    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], check=True,
                       capture_output=True)

    git("init", "-q")
    git("symbolic-ref", "HEAD", "refs/heads/main")  # not `init -b main`: that needs git 2.28
    git("config", "user.name", "Synth")
    git("config", "user.email", "synth@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-q", "--no-verify", "-m", message)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="directory to create (must be empty or absent)")
    ap.add_argument("--files", type=int, default=3000, help="approximate number of files (default 3000)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-commit", action="store_true", help="write files only, no git init/commit")
    args = ap.parse_args(argv)
    stats = generate(Path(args.out), args.files, args.seed, commit=not args.no_commit)
    print(f"{args.out}: {stats['files']} files, {stats['lines']} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
