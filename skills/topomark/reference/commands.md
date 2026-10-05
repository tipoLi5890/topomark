# Navigation commands in depth

All of these are read-only and work in any git repo, with or without a code map. They parse files
with built-in language adapters (C#, Java, JavaScript/TypeScript, Python, shell, SQL, data files,
Markdown; plain text otherwise) and cache the results outside the repo (`$TOPOMARK_CACHE`, else
`$XDG_CACHE_HOME/topomark`, else `~/.cache/topomark`).

## Which one?

| Question | Command |
|---|---|
| "What is in this file?" | `outline` |
| "Show me just this function / class" | `symbol` |
| "Where is X defined?" | `find` |
| "Who uses X?" | `refs` |
| "What breaks if I change X?" | `impact` |
| "Which tests does my change need?" | `tests-for` |
| "Give me the shape of the repo in N tokens" | `map` |
| "Which area file documents this path?" | `owner` |

## outline

```bash
topomark outline src/app/server.py
topomark outline src/app/server.py --kinds class,method --depth 2
topomark outline src/app/server.py --exported-only --json
```

Every declaration a reader navigates to (types, members, top-level functions, constants), nested by
container, with 1-based inclusive line ranges. A range includes leading doc comments and attributes,
so it can feed a ranged read directly. `--depth 1` shows top-level declarations only.

## symbol

```bash
topomark symbol src/app/server.py#Server.start
topomark symbol Server --signature
topomark symbol src/app/server.py#Server --context 3
```

Prints the symbol's lines with line numbers. `file#Outer.Inner` selects a nested member. A bare
name searches the repo; a name declared in several files lists the candidates and exits 4, so add
the file. Overloads in one file are all printed. `--signature` prints the signature and doc summary
only: the cheapest way to learn how to call something.

## find

```bash
topomark find router
topomark find Router.add --exact
topomark find Pad --kind class
```

Substring, case-insensitive by default; `--exact` matches the whole name (or a `Qual.Name` suffix),
case-sensitive. Exact matches sort first, then production code before tests.

## refs

```bash
topomark refs Router
topomark refs Router.add --no-tests
topomark refs Router --area core --limit 20
```

An identifier match in code with comments and strings masked out, not a resolved binding: treat it
as a superset. The declaration line itself is excluded. `Type.Member` lists `Member` lines in files
that mention or declare `Type`. Results are grouped production then tests, then by area (or by
top-level directory when there is no code map).

## impact

```bash
topomark impact src/core/router.py
topomark impact Router
topomark impact Router.add --top 20
```

For a file: what it declares, fan-in (production and test files that mention those names),
cross-area callers, owning area, review-stamp state, tests that mention it, and docs that mention
its path. For a symbol: definitions, references by area, tests that use it, and mentions in docs.
Run it before editing anything with a fan-in above a handful.

## tests-for

```bash
topomark tests-for
topomark tests-for --staged
topomark tests-for --since main
topomark tests-for src/core/router.py
```

Changed files (the paths given, else working tree vs HEAD including untracked files) → names they
declare → test files that mention those names → the test methods whose bodies use them. Changed test
files are selected whole. It prints runnable commands from `[[tests.runner]]` in `topomark.toml`
(see the config reference); without a runner it lists the test files. Selection is name-based, so
when it selects nothing for a change that clearly matters, run the wider suite.

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
