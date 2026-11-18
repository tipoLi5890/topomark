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
| `src/topomark/lang/_decl.py` | What the adapters below share: `_sig` (signature up to the body), balanced skips, top-level splits, annotations, enum entries | fan-in 4/0. Used by `cfamily`, `dart`, `go`, `kotlin`, `rust`, `swift`: run `tests/test_lang.py` for all of them |
| `src/topomark/lang/_imports.py` | Import specifiers as written, for the brace languages whose imports name repo files: C-family quoted includes, Dart URIs, Go paths, Rust `mod` and `use crate::`, Java and Kotlin imports; keyword found in the masked text, specifier read from the original | fan-in 6/0. Each adapter's `imports_of` calls one function; what a specifier resolves to is `src/topomark/imports.py`. Run `tests/test_navigation.py` (`OtherLanguageImportTests`) |
| `src/topomark/lang/base.py` | `Symbol` and `FileInfo` (`degraded`: why an outline may be incomplete), header comment, surface text, `count_lines` (lines as an editor numbers them: every adapter's `line_count`), `clip_signature` (what an outline shows of a long signature; the surface keeps all of it), doc summaries, `DYNAMIC` imports | fan-in 24/0. Field changes reach the cache packing in `src/topomark/index.py` (bump `CACHE_FORMAT`) |
| `src/topomark/lang/brace.py` | Generic brace-language walker: headers to `classify_block`, statements to `classify_statement` | fan-in 8/1. Shared by C#, Java, JS/TS and the six adapter modules next to it: run `tests/test_lang.py` for every language |
| `src/topomark/lang/cfamily.py` | C, C++ and Objective-C: types, functions and prototypes, macros, members by access label, `@interface` containers, quoted `#include`/`#import` specifiers | fan-in 1/1. Run `tests/test_lang.py`; its patterns run on every header of a C repository: time them on real files (a nested quantifier once took seconds per file) |
| `src/topomark/lang/csharp.py` | C# and Java: visibility, attributes, constants with values, fields named by their first declarator (commas inside type arguments belong to the type), tuple types and lambda-valued fields, enum members, inactive `#else` branches; Java `import` specifiers | fan-in 1/1. Run `tests/test_lang.py` and `tests/test_regressions.py` (prototype parity) |
| `src/topomark/lang/dart.py` | Dart: classes, mixins, extensions, enums, getters and setters; exported unless the name starts with `_`; `import`, `export` and `part` URIs | fan-in 0/0. Run `tests/test_lang.py` |
| `src/topomark/lang/go.py` | Go: functions, methods by receiver, struct and interface types, const and var groups; exported by capital letter; import paths | fan-in 0/0. Run `tests/test_lang.py` |
| `src/topomark/lang/js_ts.py` | JS/TS/JSX/TSX: ESM and CommonJS exports, export-default expressions, import specifiers | fan-in 0/0. Run `tests/test_lang.py`; import specifiers feed `imports.ImportResolver` |
| `src/topomark/lang/kotlin.py` | Kotlin: classes, objects, interfaces, functions with receivers, properties, `import` specifiers | fan-in 1/1. Run `tests/test_lang.py` |
| `src/topomark/lang/python.py` | Python by indentation: classes, functions, methods, UPPER constants, `__all__`, imports | fan-in 2/0. Run `tests/test_lang.py`; Python import specifiers feed `imports.ImportResolver` too |
| `src/topomark/lang/registry.py` | Extension to adapter map, `supported_extensions`, `analyze` | fan-in 10/4. New extension: list it in README and the translated READMEs in `.github/`, `docs/concepts.md`, `skills/topomark/reference/commands.md`, and `DEFAULT_CODE_EXT` in `src/topomark/config.py` if its files need rows |
| `src/topomark/lang/rust.py` | Rust: functions, structs, enums, traits, modules, `impl` blocks, macros; exported by `pub`; `mod name;` and `use crate::`/`super::`/`self::` paths | fan-in 0/0. Run `tests/test_lang.py` |
| `src/topomark/lang/scan.py` | Masking scanner per syntax: comments, strings, template literals, raw strings (Rust, C++, Swift `#"…"#`), offsets kept | fan-in 13/0. Run `tests/test_lang_scan.py`; a masking bug shows up as wrong refs and false syntax findings |
| `src/topomark/lang/simple.py` | Shell, SQL, data files (key skeleton), Markdown (headings), plain-text fallback | fan-in 1/1. Data and Markdown surfaces are what stamps hash for config and docs files |
| `src/topomark/lang/swift.py` | Swift: types, extensions, functions, initialisers, properties, type aliases | fan-in 1/1. Run `tests/test_lang.py` |

## Interfaces and cross-area dependencies
- Used by: [engine.md](engine.md) (`index.py` analyzes and caches, `navigate.py` masks and reads
  imports, `syntax.py` masks for bracket checks through `masking.mask_file`, `graph.py` reads
  `FileInfo`, `search.py` reads test bodies' identifiers with `base.IDENT`), `src/topomark/commands/outline.py`,
  `src/topomark/commands/agent_hook.py` (`registry.adapter_for`), `src/topomark/commands/draft.py`
  (`base.doc_summary`), `src/topomark/commands/diff.py` and `src/topomark/commands/changes.py` (old
  versions from git), `src/topomark/context.py` (`supported_extensions`).
- Depends on: the standard library only.

## Change checklist
- New language: an adapter module of its own (a `BraceLanguage` subclass when the language has
  braces) registered in `registry._load`, its name in `BRACE_LANGS` (`src/topomark/syntax.py`) for the
  bracket check, fixtures under `tests/fixtures/lang/` with a `GOLDEN` entry in
  `tests/test_lang.py` (the fixture files and the `GOLDEN` keys must be the same set), the language lists in README and the translated READMEs in `.github/`, `docs/concepts.md`
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
