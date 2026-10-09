# Navigation commands in depth

All of these are read-only and work in any git repo, with or without a code map. They parse files
with built-in language adapters (Python, JavaScript and TypeScript with JSX/TSX, C#, Java, Kotlin,
Swift, Dart, Go, Rust, C, C++ and Objective-C, shell, SQL, data files such as JSON, TOML and YAML,
and Markdown; plain text otherwise) and cache the results outside the repo (`$TOPOMARK_CACHE`, else
`$XDG_CACHE_HOME/topomark`, else `~/.cache/topomark`).

## Which one?

| Question | Command |
|---|---|
| "What is in this file?" / "in this directory?" | `outline` |
| "Show me just this function / class" | `symbol` (`--skeleton` for a class's shape) |
| "Where is X defined?" | `find` |
| "Where is the code that does X?" (no name known) | `search` |
| "Which code printed this error?" / "Where is this stack trace?" | `locate` |
| "Who uses X?" | `refs` |
| "What breaks if I change X?" | `impact` |
| "Everything I need before editing X, in one answer" | `brief` |
| "Which tests does my change need?" | `tests-for` |
| "What did my diff change, and who still depends on it?" | `changes` |
| "Do the files I just edited still parse?" | `syntax` |
| "Give me the shape of the repo in N tokens" | `map` |
| "Which area file documents this path?" | `owner` |

## outline

```bash
topomark outline src/app/server.py
topomark outline src/app/server.py --kinds class,method --depth 2
topomark outline src/app/server.py --exported-only --json
topomark outline src/app/ --tokens 1200
topomark outline src/app/server.py src/app/router.py --depth 2
```

Every declaration a reader navigates to (types, members, top-level functions, constants), nested by
container, with 1-based inclusive line ranges. A range includes leading doc comments and attributes,
so it can feed a ranged read directly. `--depth 1` shows top-level declarations only.

The adapters read text; they do not parse. When a Python bracket never closes, or a JS/TS file's
braces do not balance, the outline says `warning: this outline may be incomplete: ...` (JSON:
`degraded`): read the file itself around that line instead of trusting the list.

Several paths, or a directory (its git code files, recursively; Markdown and data files left out),
are outlined together: top-level declarations unless `--depth` says otherwise, one header line per
file, files in path order until `--tokens` (default 2000) is spent, then a count of the files left
out. The JSON is then `{"files": [...], "total_files", "shown_files", "truncated", "depth", "budget",
"estimated_tokens"}`, each entry shaped like a single-file outline; one file keeps the single-file
shape.

## symbol

```bash
topomark symbol src/app/server.py#Server.start
topomark symbol Server --signature
topomark symbol src/app/server.py#Server --context 3
topomark symbol src/app/server.py#Server --skeleton
```

Prints the symbol's lines with line numbers. `file#Outer.Inner` selects a nested member. A bare
name searches the repo; a name declared in several files lists the candidates and exits 4, so add
the file. Overloads in one file are all printed. `--signature` prints the signature and doc summary
only: the cheapest way to learn how to call something.

`--skeleton` keeps every declaration line and replaces the bodies of the innermost members (or the
symbol's own body when it has no members) with `… (lines A-B)`, ready for a ranged read. A Python
docstring keeps its first line, a closing brace stays, a one-line body is printed as is, and a
multi-line constant keeps its first line. Fields, nested types and anything between members stay.
The JSON gives `skeleton` (the text) and `elided` (the left-out ranges) instead of `source`.

## find

```bash
topomark find router
topomark find Router.add --exact
topomark find Pad --kind class
```

Substring, case-insensitive by default; `--exact` matches the whole name (or a `Qual.Name` suffix),
case-sensitive. Exact matches sort first, then code before docs and data files (Markdown headings,
JSON/YAML keys), then production before tests.

## search

```bash
topomark search review stamp surface hash
topomark search cache directory --limit 5
topomark search token budget --area core --tokens 600
```

BM25 over what the code says about itself. Each symbol is a document of weighted fields: its name
split at case changes and underscores (`unit_surface_hash` → unit, surface, hash), its container,
signature, doc summary and path; a type also carries its members' names. Words are lowercased and
lightly stemmed (`stamps` → `stamp`, `directories` → `directory`), stop words dropped. A file's header
comment and its code-map row add to its symbols' scores, and a file can be a result on its own. A
test method whose name matches lends half its score to the production symbols its body uses
(`via` in the output and JSON): issue words often match a test's name better than the code's.

Ranking by weight, not strict tiers: production code above tests (a test counts less than the code it
leads to), code above Markdown and data files, symbols that match more of
the query's words above those that match fewer. No PageRank and no randomness: the same query on the
same tree gives the same list. Output is capped at `--limit` (default 15) or `--tokens`, with a count
of what was left out; there is no second page. **Give two to five keywords**, the words the code
would use, not a pasted issue: every extra word dilutes the ranking. For a name fragment, `find` is
faster and exact. JSON: `terms`, `total`, `files`, `shown`, `truncated`, `results` (`path`,
`qualname`, `kind`, `start`, `end`, `signature`, `score`, `group`, `matched`, `via`). The index is
cached and rebuilt when a parsed file or the code map changes.

## locate

```bash
topomark locate "error: NOT_FOUND: no such file: src/app.py"
topomark locate "unknown (section|key)" --regex
topomark locate --trace crash.txt
topomark locate --trace
```

**A message.** Paste it as printed. Values interpolated into it (`f"... {path}"`) and strings split
across lines would defeat a plain text search, so `locate` cuts the message into overlapping runs of
three words (and two, at half the weight), looks each up literally in every parsed file, weights a
run by how few files contain it, and sums the hits per enclosing symbol. A place reached only by a
common two-word run is dropped. Production code comes first, then tests, then docs and data files,
whatever the score: the goal is the code that printed the message, not a page that quotes it.
`--regex` matches one pattern per line instead. Capped at `--limit` (default 10) with a count.

**A trace.** `--trace FILE`, or `--trace` alone (or `--trace -`) to read stdin. Frames are recognised
in Python, Node/V8, Firefox/Safari, Java and Kotlin (the class name gives the package path), C#,
Dart (`package:name/x.dart` → `lib/x.dart`), Go and Rust traces, plus generic `path:line` and
`path(line,col)` (compiler errors, test failures). A frame's path maps to the git file sharing the
longest path suffix with it, so `/home/ci/build/src/app/store.py` finds `src/app/store.py`; a bare
file name matches every file of that name (`candidates`), ranked by whether the frame's function is
the enclosing symbol there. Frames outside the repo (the runtime, site-packages, node_modules) are
listed as `skipped`. Results come innermost first, each with the enclosing symbol and the source line.

JSON: `mode` (`text`, `regex` or `trace`), `total`, `results` (`path`, `line`, `qualname`, `kind`,
`start`, `end`, `text`, `group`; a trace frame adds `func`, `format`, `trace`), `skipped` for traces.
Files are read like every other command's: secret-looking paths never.

## refs

```bash
topomark refs Router
topomark refs Router.add --no-tests
topomark refs Router --area core --limit 20
```

An identifier match in code with comments and strings masked out, not a resolved binding: treat it
as a superset. The declaration line itself is excluded. `Type.Member` lists `Member` lines in files
that mention or declare `Type`. Results are grouped production then tests, then by area (or by
top-level directory when there is no code map). The text shows the counts of every group and the
first 20 sites, then how many were left out; `--limit N` lists N. The JSON lists up to `--limit`
(default 200) and always carries the counts.

## impact

```bash
topomark impact src/core/router.py
topomark impact Router
topomark impact Router.add --top 20
```

For a file: what it declares, fan-in (production and test files that mention those names), the
files that import it (`importers`: Python and JS/TS import statements resolved to repo files,
including relative imports, `src/` layouts, `.js` written for `.ts`, `index` files and `@/` or `~/`
aliases), cross-area callers, owning area, review-stamp state, tests that mention it, and docs that
mention its path. For a symbol: definitions, references by area, tests that use it, and mentions in
docs. Run it before editing anything with a fan-in above a handful.

## brief

```bash
topomark brief src/core/router.py
topomark brief Router
topomark brief src/core/router.py#Router.add --tokens 800
```

One answer before an edit, built from `owner`, `outline`, `impact` and `tests-for`:

- **File:** its area file, code-map row and review stamp; its exported outline (two levels);
  fan-in and importers; callers one hop away (files that use its names or import it), the ones that
  use the most of its names first; the tests `tests-for` would pick and the command from
  `[[tests.runner]]`; docs that mention it.
- **Name** (`Name`, `Type.Member`, `<file>#<Name>`): its definition, signature and doc, its exported
  members, reference counts, the callers with the most reference sites first, the tests whose
  bodies use it (else the tests for its file), the run command, and the same area and docs lines.
  A name declared in several files lists `topomark brief <file>#<Name>` candidates and exits 4.

`--tokens` (default 1500) caps the text: the outline's tail goes first, then the docs line, then the
caller and test lists shrink to three each, and each cut says how many were left out. The JSON
mirrors what the text shows (`trimmed` names what was cut; `outline_total`, `callers_total`,
`tests_total` give the full counts) and lists `related`: the callers, then the tests, in the order
shown. Over 30 callers it says the file is too central to pick tests by name: run the suite.

## tests-for

```bash
topomark tests-for
topomark tests-for --staged
topomark tests-for --since main
topomark tests-for src/core/router.py
topomark tests-for src/core/util.py --depth 3
```

Changed files (the paths given, else working tree vs HEAD including untracked files) → names they
declare → test files that mention those names → the test methods whose bodies use them. Changed test
files are selected whole.

A production file that no test mentions is followed to its callers, up to `--depth` hops (default
2; `0` turns this off): files that import it (Python and JS/TS import statements, transitively) and,
one hop only, files that use a distinctive name it declares. Test files that import a reached file
are selected whole; tests that mention a caller's names are selected by method. Either way the
result says `via <caller>` (JSON: `via`, the chain of files from the change to the test). Barrels
(`index.ts`, an `__init__.py` that only gathers names) and test helpers cost no hop.

It prints runnable commands from `[[tests.runner]]` in `topomark.toml` (see the config reference);
without a runner it lists the test files. When a file stays uncovered it says so, prints the
runner's `suite` command if one is configured (JSON: `suite_commands`), and lists files that load
modules by computed names (`importlib.import_module(f"...")`, `` import(`./${x}`) ``; JSON:
`dynamic_loaders`), which a static search cannot see through. A file with more than 30 callers is
not followed (JSON: `limited`): run the suite.

## syntax

```bash
topomark syntax
topomark syntax src/app.py web/main.ts
topomark syntax --diff --json
```

Run it after every edit. Without paths it checks the files changed vs HEAD (untracked included).
Python goes through `ast.parse`, JSON through `json.loads` (a file that parses once `//` and `/* */`
comments and trailing commas are dropped, such as `tsconfig.json`, passes; `.jsonc` is read that way,
`.json5` is not checked), TOML through `tomllib`. JS/TS, C#, Java, Kotlin, Swift, Dart, Go, Rust
and C-family files get a bracket-balance check on the text with comments and strings masked; since
the masker is lexical, a file is reported only when its HEAD version was balanced and the current
one is not, and a new file is not bracket-checked. Other files are listed as not checkable.

Each problem prints as `path:line:col: lang: message`; exit 1 when there is any. JSON: `ok`,
`checked`, `skipped` (`path`, `reason`) and `problems` (`path`, `line`, `col`, `lang`, `message`,
`preexisting`: the HEAD version does not parse either, so the edit did not cause it).

## changes

```bash
topomark changes
topomark changes --staged
topomark changes --since main --top 10
```

The diff (working tree vs HEAD with untracked files, `--staged` for the index vs HEAD, or
`--since REV` for the working tree vs REV) mapped to symbols. `git diff -U0` gives the changed
lines of each side; the old side is analyzed from `git show REV:path` with the same adapter, and
each changed line counts for the innermost declaration around it. By qualified name:

| change | means |
|---|---|
| `added` | declared now, not before (members of an added type fold into it in the text) |
| `removed` | declared before, not now; renames show as a removal plus an addition |
| `signature` | the signature, attributes, kind or exportedness differ (a constant's value is its signature) |
| `body` | same signature, edited lines inside |

A changed header comment is an interface change of the file (`header_changed`); edits outside any
declaration (imports, module code) are flagged as `outside_declarations`. For removed and
re-signed names (up to 12, removed first), `interface` lists the references left: sites, the
production callers (`--top`, default 5) and tests, from the same scan as `impact`; a removed name
that is still referenced is called out. `tests`, `commands` and `suite_commands` are what
`tests-for` would print for the changed files. `review` lists the code-map rows whose units had an
interface change, with their review-stamp state: update the row, then `topomark stamp <unit>`.
Markdown and data files are listed under `other` without symbols.

## map

```bash
topomark map
topomark map --tokens 2000
topomark map --focus src/core/router.py --tokens 1500
topomark map --focus Router --area core
```

Files ranked by PageRank over the reference graph (personalised toward `--focus` files, or files that
declare a focused name), each with its highest-weight declarations, until the token budget is spent
(`estimated_tokens` in the JSON: ASCII counts 1 token per 4 characters, other characters 1 each).
Tests and docs are left out. Use it on first contact with a repo that has no code map, or to get the
neighbourhood of a file before an edit.

## owner

```bash
topomark owner src/core/router.py
```

The area that owns a path (longest `scope` prefix), its unit, fan-in and review-stamp state. The area
file is where the row for that path lives.
