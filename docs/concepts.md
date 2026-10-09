# Concepts

## Three layers of progressive disclosure

An agent (or a new colleague) should read only as deep as the task needs:

| Layer | What | Budget |
|---|---|---|
| **L0** | `<docs_dir>/README.md`: the area table, "to change X, read this first", the highest-impact files, coupling between areas, links to the repo's rule files | `l0_max` lines (160) |
| **L1** | `<docs_dir>/<area>.md`: one row per unit (file or directory) with a one-line summary and its impact, plus data flow, change checklist and pitfalls | `l1_max` lines (260) each |
| **L2** | the code, read by symbol: `outline`, `symbol`, `search`, `refs`, `impact`, `brief` | as little as possible |

The code map links the repo's existing rule files (CLAUDE.md, AGENTS.md, ADRs, architecture docs)
instead of restating them. A summary that copies a design reason goes stale twice as fast as one
that links it.

## Areas, scopes and units

An area is one Markdown file with frontmatter:

```yaml
---
area: core
title: Core
summary: routing and storage
granularity: file
scope:
  - src/core/
---
```

- **Ownership:** a file belongs to the area whose `scope` entry is the longest prefix of its path. A
  scope entry is a directory (trailing `/`) or one file. Two areas claiming the same longest prefix
  is an `OWNER_CONFLICT`.
- **Units:** with `granularity: file` every required file is a unit and needs its own row. With
  `granularity: dir` the unit is the file's directory truncated to `depth` levels below the scope
  root, written `` `path/` ``. A count right after the backticks (`` `path/` (12 files) ``) is
  verified by `check`.
- **Required files:** code files (by extension) outside `docs_dir`, after excludes; see
  [config.md](config.md).

## Review stamps, not timestamps

A modification time or a "last reviewed" date says nothing about whether a summary is still true.
topomark records, per unit, what the row was written against:

- the **surface hash**: SHA-256 of the file's header comment and public interface (exported
  signatures, constant values, enum members; for data files the key skeleton), and
- the **git blob** of the content at review time, so `topomark diff` can show what changed since.

A stamp records the surface hash and the git blob of each file as it was reviewed. When the hash no
longer matches, `check` reads those blobs again with the adapters it has today and compares that
with the files as they are now, so a topomark upgrade that reads a declaration differently does not
ask for every row to be reviewed again, and nothing but a real difference between the reviewed code
and today's code counts. Without the blobs (git pruned them) the hashes decide.

`check` fails when a unit's surface changed since its stamp (`STAMP_CHANGED`), when a unit was never
stamped (`STAMP_MISSING`) and when a stamp's unit is gone (`STAMP_ORPHAN`). A body-only change does
not fail `check`; `topomark stale` lists it as advisory. Each area also stamps its set of cross-area
callers (`EDGES_CHANGED`), because a new caller from another area is exactly when the data-flow
section goes stale.

Stamps live in `<docs_dir>/stamps.json` and are written only by `topomark stamp`. Editing an area
file never blesses other rows. The workflow is always:

```bash
topomark diff src/core/router.py
topomark stamp src/core/router.py
```

with the row updated in between if the summary or impact changed.

## Fan-in

`fan-in P/T` is the number of production (P) and test (T) files that mention a name the unit
declares at the top level. It is approximate on purpose: names shorter than `min_name`, and names
declared in more than one file, are ignored. The number says how careful to be; the row's sentence
says what to update. `topomark sync` rewrites the numbers in area files, `topomark gen` regenerates
`_generated/fanin.md` (and `_generated/modules.md`, the module graph from `.asmdef` and
`package.json` manifests).

Import statements are a second signal: `impact <file>` lists the files whose Python or JS/TS
imports resolve to it, and `tests-for` follows them to the tests of a file that no test mentions.
Between two Python files they also decide fan-in: a mention counts only when the file imports the
declaring module (directly, or through a module that imports it and mentions the name), so a
function named `search` is not credited with every `re.search` in the repository. Other languages
are counted by name alone.

## Navigation without a code map

`outline`, `symbol`, `find`, `search`, `locate`, `refs`, `impact`, `brief`, `tests-for`, `syntax`,
`changes` and `map` work in any git repo. They parse files with built-in language adapters: Python,
JavaScript and TypeScript (JSX and TSX included), C#, Java, Kotlin, Swift, Dart, Go, Rust, C, C++ and
Objective-C, shell, SQL, data files (JSON, JSONC, JSON5, TOML, YAML, Unity `.asmdef`) and Markdown. A file without an adapter that `required_ext` or
`every_file_roots` still asks for is read as plain text: no symbols, the whole text is the surface.
Results are cached per file, keyed by modification time and size, in the user's cache directory,
never in the repository.

## What topomark writes

| Command | Writes |
|---|---|
| `init` | `topomark.toml`, `<docs_dir>/README.md`, `_TEMPLATE.md`, one file per area (refuses to overwrite without `--force`; nothing with `--dry-run`) |
| `draft --write` | the area file it names |
| `gen` | `<docs_dir>/_generated/` |
| `sync` | the fan-in numbers in area files |
| `stamp` | `<docs_dir>/stamps.json` (and stores reviewed blobs in the git object store) |
| `hook install` | `.git/hooks/pre-commit` (an existing hook is kept as `pre-commit.local`) |
| everything else | nothing in the repository |

Outside the repository, every command may write to the user cache directory: the analysis cache,
and for `agent-hook` the markers that keep each plugin-hook hint to once per session.
