# topomark

**Your agent reads a 2,000-line file to find one function. Give it a map instead.**

topomark is a zero-dependency code map for AI coding agents: layered docs that say where to look,
review stamps that fail CI when a summary goes stale, and fast symbol, impact and test navigation
for any git repository. Python 3.11+ standard library only; offline; read-only on your code.

![license: MIT](https://img.shields.io/badge/license-MIT-blue)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

[繁體中文](.github/README.zh-Hant.md) · [简体中文](.github/README.zh-Hans.md) · [日本語](.github/README.ja.md)

## Let your agent install it

Paste this into Claude Code, Codex or any coding agent with a terminal, from inside your repository:

```text
Install topomark (https://github.com/tipoLi5890/topomark), a zero-dependency code map and
navigation CLI, and set this repository up to use it:

1. Clone it: git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
   (if that directory exists, run git -C ~/tools/topomark pull instead).
2. Put it on PATH: ln -sf ~/tools/topomark/bin/topomark ~/.local/bin/topomark, and make sure
   ~/.local/bin is on PATH. Check with topomark --version (it needs Python 3.11+ and git).
3. Run topomark doctor in this repository and tell me about any problem it reports.
4. Read ~/tools/topomark/skills/topomark/SKILL.md and follow it from now on.
5. Add this line to AGENTS.md, or to CLAUDE.md if that is what the repository uses:
   "Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
   `topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before
   an edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and
   keep `topomark check` green."
6. Run topomark init --dry-run and show me the proposed areas. Write nothing else until I agree;
   then run topomark init and topomark draft <area> --write for each area, and fill in the rows.
```

Until a code map exists, `topomark map --tokens 2000` and the other navigation commands already
work; step 6 is what makes `check` and review stamps possible.

## Try it in 30 seconds

Navigation needs no setup, no config and no index to build. Clone, then point it at any git repo:

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
cd your-repo
~/tools/topomark/bin/topomark map --tokens 2000      # a ranked map of the repo, within a token budget
```

Nothing is installed and nothing is written to your repository.

## Why topomark

### A ladder, not a haystack

Agents spend much of their context reading whole files to find one function. topomark gives them
rungs, each small enough to read in full:

```text
L0  docs/codemap/README.md     one index: the areas of the repo and what each owns
L1  docs/codemap/<area>.md     one row per file: what it does, how many files depend on it,
                               what to update when it changes
L2  the code, by symbol        topomark outline / symbol / refs: one function, not the file
```

### Review stamps, not timestamps

Hand-written maps rot silently. So topomark stores, per file, a hash of its *interface* (header
comment, public signatures, constants) at the moment its row was reviewed.

- Change an interface without reviewing the row: `topomark check` fails.
- Change only a function body: it stays quiet.

A "last updated" date can't tell those two apart. A stamp can, so the map is either current or CI
says exactly which rows are not.

### Zero dependencies, really

No tree-sitter, no language servers, no network. One `git clone` and a Python 3.11 interpreter; it
runs the same in CI, in a pre-commit hook and inside an agent sandbox.

### Fast enough to run on every step

On a 3,000-file synthetic repo with a warm cache, `outline` and `symbol` take about 0.05 s of CPU
and `map`, `search`, `impact` and `brief` between 0.16 and 0.28 s (an Apple-silicon laptop;
[docs/pilots.md](docs/pilots.md) has the tables and how they were measured).

### Link, don't restate

`init` finds the repo's existing rule files (CLAUDE.md, AGENTS.md, ARCHITECTURE.md,
REPO_MAP.md...) and links them instead of copying their content.

## Install

Either of these works:

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
~/tools/topomark/bin/topomark --version     # self-locating launcher, no install step
```

Put `~/tools/topomark/bin` on your `PATH` (e.g. `ln -s ~/tools/topomark/bin/topomark ~/.local/bin/topomark`).
If you already use pipx, it can install the command instead (pipx is not required):

```bash
pipx install git+https://github.com/tipoLi5890/topomark
```

`bin/topomark` finds a Python 3.11+ interpreter itself (`python3.14` down to `python3`). It needs
`git` on `PATH`.

**As an agent plugin.** The repo is a Claude Code plugin and marketplace (`.claude-plugin/`) and a
Codex plugin (`.codex-plugin/`), bundling one skill, [`skills/topomark`](skills/topomark/SKILL.md).
In Claude Code: `/plugin marketplace add tipoLi5890/topomark`, then `/plugin install
topomark@topomark`. The plugin also brings three hooks: a short code-map pointer at session start, a
hint before reading a large file or a new area, and a syntax check after each edit (see
[Using it from an agent](#using-it-from-an-agent)).

## Quickstart

**Navigate** (no setup at all):

```bash
topomark map --tokens 2000
topomark outline src/core/router.py --exported-only
topomark symbol src/core/router.py#Router.add
topomark symbol src/core/router.py#Router --skeleton
topomark outline src/core/ --tokens 1200
topomark find Router --exact
topomark search route handler registration
topomark locate "no such file: src/app.py"
topomark locate --trace crash.txt
topomark refs Router --no-tests
topomark impact Router
topomark brief src/core/router.py
topomark tests-for --since main
topomark syntax
topomark changes --staged
```

**Build a code map** that stays honest:

```bash
cd your-repo
topomark doctor                 # Python, git, config, tracked secrets
topomark init --dry-run         # the proposed areas, excludes and files; writes nothing
topomark init                   # write topomark.toml and the code-map skeleton
topomark draft backend --write  # rows for one area, summary and fan-in prefilled; then edit them
topomark gen                    # generated fan-in table and module graph
topomark stamp --baseline       # once, after the rows were read
topomark check                  # from now on: is the map in sync with the code?
topomark hook install           # optional pre-commit gate
```

## Using it from an agent

The bundled skill teaches the loop: read L0, read one area file, `outline`, `symbol`; `brief` before
an edit, `syntax` after it; run what `tests-for` prints; `changes` before committing; then `check` /
`diff` / `stamp`. It works without slash commands or a plugin runtime: every step is a shell
command, so the same instructions work in Claude Code, Codex or any agent with a terminal. An
`AGENTS.md` or `CLAUDE.md` line is enough:

```text
Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
`topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before an
edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and keep
`topomark check` green.
```

**Claude Code plugin hooks.** Installed as a plugin, topomark also registers three hooks
(`hooks/hooks.json`) that only add context and never block a tool call:

- **SessionStart** (startup, clear, compact): the L0 path, each area's name and file, one line of
  navigation commands and whether review stamps exist; at most 40 lines. Without a code map, one line
  suggesting `topomark map --tokens 2000`.
- **PreToolUse on Read**: a file over 400 lines gets a pointer to `outline` and `symbol --skeleton`;
  the first file read in an area, a pointer to its area file. Each hint once per session; ranged
  reads get none.
- **PostToolUse on Edit, Write, MultiEdit**: the `syntax` check of the edited file, reported only when
  the edit broke it.

Each costs one short process (about 0.15 to 0.3 s of CPU on a 3,000-file repo). topomark ships hooks for Claude Code
only; elsewhere the skill says to run `topomark syntax --diff` after every edit. Details:
[adoption.md](skills/topomark/reference/adoption.md#claude-code-plugin-hooks).

## Commands

**Navigation**: read-only, any git repo, no setup. In the order an agent meets them: orient, find,
look before an edit, check after it.

| Command | What it does |
|---|---|
| `map` | ranked repo map within a token budget, for a repo without a code map (`--focus`, `--tokens`, `--area`) |
| `outline <path>..` | symbols with line ranges, kinds, signatures, doc summaries; several files or a directory at once, top level within a token budget (`--exported-only`, `--kinds`, `--depth`, `--tokens`) |
| `symbol <file>#<Name>` / `symbol <Name>` | print one symbol's source (`--signature`, `--skeleton` for declarations with bodies elided, `--context N`) |
| `find <Name>` | definitions by name (`--kind`, `--exact`, `--limit`) |
| `search <keywords>` | code by what it is about: BM25 over symbol names, signatures, docs and paths; a matching test leads to the code it uses. Give keywords, not a pasted issue (`--limit`, `--area`, `--tokens`) |
| `locate "<message>"` / `locate --trace [FILE]` | the code behind an error message (literal word runs, so interpolated values still match) or a stack trace (Python, Node, Java/Kotlin, C#, Dart, Go, Rust, `path:line`), code before tests before docs (`--regex`, `--limit`) |
| `owner <path>` | the owning area, unit, fan-in and stamp state |
| `refs <Name>` | reference sites, comments and strings excluded; text shows group counts and the first 20 (`--area`, `--no-tests`, `--limit`) |
| `impact <Name or file>` | callers, importers, cross-area users, tests and docs a change reaches (`--top`) |
| `brief <file or Name>` | one briefing before an edit, within a token budget: area row, outline, most-coupled callers, tests and the command that runs them (`--tokens`) |
| `syntax [paths]` | do the edited files still parse: Python, JSON and TOML exactly, bracket balance in brace languages (only when HEAD was balanced); exit 1 on findings (`--diff`, the default) |
| `tests-for [paths]` | tests covering changed files, through their callers when no test names them, as runnable commands (`--diff`, `--staged`, `--since REV`, `--depth N`) |
| `changes` | the symbols a diff touches, interface (added, removed, new signature) or body, who still references the changed interfaces, tests to run, code-map rows to review (`--staged`, `--since REV`, `--top`) |

**Code map**: writes only `topomark.toml` and `docs_dir`.

| Command | What it does |
|---|---|
| `init` | detect the stack and write the code-map skeleton (`--dry-run`, `--docs-dir`, `--force`) |
| `draft <area>` | rows an area file is missing, prefilled (`--write`) |
| `check` | coverage, dead paths, ownership, line caps, fan-in, generated files, stamps (`--area`, `--no-stamps`) |
| `stale` | rows needing review (blocking) and body-only changes (advisory) (`--area`) |
| `diff <unit>` | what changed since the unit's review stamp, interface first |
| `stamp` | record a review (`<units>`, `--area`, `--edges`, `--prune`, `--baseline`, `--force` with it) |
| `gen` | regenerate `<docs_dir>/_generated/` |
| `sync` | rewrite the fan-in numbers written in area files |

**Hooks and tooling**

| Command | What it does |
|---|---|
| `hook install\|uninstall\|status` | opt-in git pre-commit gate running `check` |
| `agent-hook session-start\|pre-read\|post-edit` | what the Claude Code plugin's hooks run: reads the hook JSON on stdin, answers in the hook protocol, always exits 0 |
| `doctor` | environment and repository health |
| `capabilities` | every command and flag, from the live parser (use `--json`) |

Global flags work before or after the command: `--json`, `-C/--repo DIR`, `--config PATH`, `-q`,
`-v`, `--debug`.

## Languages

| | |
|---|---|
| **Symbols** (`outline`, `symbol`, `find`) | Python, JavaScript and TypeScript (JSX and TSX included), C#, Java, Kotlin, Swift, Dart, Go, Rust, C, C++ and Objective-C, shell, SQL, data files (JSON, JSONC, JSON5, TOML, YAML, Unity `.asmdef`) and Markdown |
| **Import edges** (who imports this file, and the walk from a changed file to its tests) | Python, JS/TS, C-family `#include "x.h"`, Dart, Go, Rust, Java and Kotlin. C# and Swift name namespaces and modules, not files, so there topomark has name references only |
| **Plain text** | other extensions named in `required_ext`: no symbols, and the whole text is the review surface |
| **No adapter** | Ruby, PHP, Scala, Lua or Elixir, among others: `outline`, `symbol` and `find` have nothing to show there, while `locate` and `search` over paths still work |

## Configuration

Everything is optional. `topomark.toml` at the repo root:

```toml
[topomark]
docs_dir = "docs/codemap"

[files]
exclude = ["**/l10n/app_localizations*.dart"]

[[tests.runner]]
match = "tests/"
command = "python3 -m unittest {names}"
names = "file"
```

Areas are not configured here: each area file's frontmatter (`scope`, `granularity`) is the single
source of truth. Full reference: [docs/config.md](docs/config.md). Concepts (layers, ownership,
units, stamps, fan-in): [docs/concepts.md](docs/concepts.md).

## Built for scripts: exit codes and JSON

| Exit | Meaning |
|---|---|
| 0 | ok |
| 1 | findings (`check`, `stale`, `doctor`, `syntax`): the tool worked and found problems |
| 2 | usage error, or a refused action that would lose information |
| 3 | invalid `topomark.toml` |
| 4 | path, symbol or area not found |
| 5 | no language adapter for the operation |
| 6 | not inside a git work tree |
| 7 | internal error (rerun with `--debug`) |

`--json` prints exactly one JSON object on stdout, stamped `"schema_version": "topomark/1"` and
`"command"`. Errors print `{"error": {"code", "message", "exit", "remediation"}}`, also on stdout.
`agent-hook` is the one exception: it answers in the Claude Code hook protocol and always exits 0.

## Design notes and honest limits

- **Files come from git**, never from a directory walk: what `.gitignore` excludes is already out.
- **Secret-looking paths are never read** (`.env`, `*.pem`, `keys/`, `credentials*`...), and the
  list cannot be switched off. `doctor` warns about secrets git tracks.
- **Parsing is lexical, not semantic.** Adapters mask comments and strings, track scopes and read
  declarations; references are identifier matches. That makes `refs` a superset and `fan-in`
  approximate, and keeps the tool fast, dependency-free and tolerant of code that doesn't compile.
- **The surface hash ignores bodies** so refactors inside a function don't demand a review, while a
  new public method, a changed constant or a rewritten header comment does.
- **The cache lives outside the repo** (`$TOPOMARK_CACHE`, `$XDG_CACHE_HOME/topomark`,
  on Windows `%LOCALAPPDATA%\topomark\Cache`, else `~/.cache/topomark`), keyed by file mtime and size and dropped when the adapters change. It is
  sharded, so a single-file `outline` costs the same in a 3,000-file repo as in a small one, and the
  first whole-repo command on a large repository parses in worker processes (`TOPOMARK_JOBS`). The
  plugin hooks keep their once-per-session markers there too.

## Acknowledgments

topomark borrows ideas, not code. The ranked repository map follows [Aider's repo
map](https://aider.chat/docs/repomap.html) (Apache-2.0); the symbol-level tools follow
[Serena](https://github.com/oraios/serena) (GPL-3.0-or-later); the impact summary was inspired by
[GitNexus](https://github.com/abhigyanpatwari/GitNexus)'s impact analysis (PolyForm Noncommercial:
concepts only). **topomark copies no code from any of them.** Details:
[ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

## Contributing, security, license

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) ·
MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Li, ching yu.
