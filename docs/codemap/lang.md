---
area: lang
title: Language adapters
summary: Per-language lexical analysis of one file into a FileInfo: symbols, header, surface, identifiers, imports
granularity: file
scope:
  - src/topomark/lang/
---

# Language adapters

> One adapter per language family turns `(path, text)` into a `FileInfo`: declarations with line
> ranges, the header comment, the review *surface*, identifiers in code, top-level type names and
> import specifiers. Lexical on purpose: mask comments and strings, track scopes, read declarations;
> no parser, no type information. Everything else consumes `FileInfo` through the cache in
> [engine.md](engine.md); nothing here reads files or knows about the code map.

## Read these first
- `src/topomark/lang/base.py`: the `FileInfo` and `Symbol` contract every adapter fills.
- `src/topomark/lang/scan.py`: the masking every adapter (and `syntax`, `refs`) relies on.
- `src/topomark/lang/brace.py`: the shared walker behind ten languages.

## Data flow and entry points
```
registry.adapter_for(path)          extension -> adapter class (Plain for anything unknown)
  adapter.analyze(path, text)
    scan.mask(text, syntax)         comments and strings blanked, offsets kept
    python.py: indentation scopes   brace.py: scope stack, classify_block / classify_statement
    simple.py: shell (simple.mask_shell: Syntax can't express it), SQL, data keys, Markdown, text
  -> FileInfo(symbols, header, surface, idents, types, imports, line_count)
Index (engine) caches the FileInfo; its fingerprint hashes every lang/*.py, so editing an adapter
drops the cache.
```

## Files
| file | summary | impact |
|---|---|---|
| `src/topomark/lang/__init__.py` | Package marker | fan-in 0/0 |
| `src/topomark/lang/base.py` | `Symbol` and `FileInfo`, header comment, surface text, doc summaries, `DYNAMIC` imports | fan-in 9/0. Field changes reach the cache packing in `src/topomark/index.py` (bump `CACHE_FORMAT`) |
| `src/topomark/lang/brace.py` | Generic brace-language walker: headers to `classify_block`, statements to `classify_statement` | fan-in 3/1. Shared by C#, Java, JS/TS and `extra.py`: run `tests/test_lang.py` for every language |
| `src/topomark/lang/csharp.py` | C# and Java: visibility, attributes, constants with values, enum members, inactive `#else` branches | fan-in 1/1. Run `tests/test_lang.py` and `tests/test_regressions.py` (prototype parity) |
| `src/topomark/lang/extra.py` | Dart, Kotlin, Swift, Go, Rust and C/C++/Objective-C on the brace walker | fan-in 0/1. Run `tests/test_lang.py`; a new language here also goes into `BRACE_LANGS` in `src/topomark/syntax.py` |
| `src/topomark/lang/js_ts.py` | JS/TS/JSX/TSX: ESM and CommonJS exports, export-default expressions, import specifiers | fan-in 0/0. Run `tests/test_lang.py`; import specifiers feed `navigate.ImportResolver` |
| `src/topomark/lang/python.py` | Python by indentation: classes, functions, methods, UPPER constants, `__all__`, imports | fan-in 2/0. Run `tests/test_lang.py`; Python import specifiers feed `navigate.ImportResolver` too |
| `src/topomark/lang/registry.py` | Extension to adapter map, `supported_extensions`, `analyze` | fan-in 14/4. New extension: list it in README, `.github/README.zh-Hant.md`, `docs/concepts.md`, `skills/topomark/reference/commands.md`, and `DEFAULT_CODE_EXT` in `src/topomark/config.py` if its files need rows |
| `src/topomark/lang/scan.py` | Masking scanner per syntax: comments, strings, template literals, raw strings (Rust, C++, Swift `#"…"#`), offsets kept | fan-in 7/0. Run `tests/test_lang_scan.py`; a masking bug shows up as wrong refs and false syntax findings |
| `src/topomark/lang/simple.py` | Shell, SQL, data files (key skeleton), Markdown (headings), plain-text fallback | fan-in 1/1. Data and Markdown surfaces are what stamps hash for config and docs files |

## Interfaces and cross-area dependencies
- Used by: [engine.md](engine.md) (`index.py` analyzes and caches, `navigate.py` masks and reads
  imports, `syntax.py` masks for bracket checks through `navigate.mask_file`, `graph.py` reads
  `FileInfo`, `search.py` reads test bodies' identifiers with `base.IDENT`), `src/topomark/commands/outline.py`,
  `src/topomark/commands/agent_hook.py` (`registry.adapter_for`), `src/topomark/commands/draft.py`
  (`base.doc_summary`), `src/topomark/commands/diff.py` and `src/topomark/commands/changes.py` (old
  versions from git), `src/topomark/context.py` (`supported_extensions`).
- Depends on: the standard library only.

## Change checklist
- New language: an adapter (a `BraceLanguage` subclass in `src/topomark/lang/extra.py`, or a module
  registered in `registry._load`), fixtures under `tests/fixtures/lang/` with a `GOLDEN` entry in
  `tests/test_lang.py` (the fixture files and the `GOLDEN` keys must be the same set), the language lists in README, `.github/README.zh-Hant.md`, `docs/concepts.md`
  and `skills/topomark/reference/commands.md`, and `DEFAULT_CODE_EXT` in `src/topomark/config.py` if
  its files need rows by default.
- Changing what goes into a surface: every adopted code map reports `STAMP_CHANGED` for the files
  affected after the upgrade. Say so in CHANGELOG; re-run the parity checks in `docs/pilots.md`.
- Regenerate a `GOLDEN` only after reading the new outline (`tests/test_lang.py` docstring).

## Invariants and pitfalls
- A body edit must not change the surface; an interface edit (header, exported signature, constant
  value, enum member) must (`src/topomark/lang/base.py` docstring).
- `imports` are never part of the surface: adding an import asks for no review.
- Adapters are stateless; the registry makes one instance per call so nothing leaks between files.
- Function bodies are tracked for brace balance only, never classified, so locals and lambdas stay
  out of outlines (`src/topomark/lang/brace.py` docstring).
- `tests/fixtures/` holds deliberately odd sources and is excluded from this repo's own map and from
  ruff in CI.

## Further reading
- `CONTRIBUTING.md`, "Language adapters": what an adapter must and must not do.
- `docs/pilots.md`: the prototype surface-parity run that found the adapter regressions.
