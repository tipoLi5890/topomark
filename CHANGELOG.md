# Changelog

All notable changes to `topomark` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning policy

- **Package version (SemVer).** The single source of truth is `pyproject.toml`;
  `tools/sync_version.py` stamps it into `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json` and `.codex-plugin/plugin.json`, and CI fails on drift.
  MAJOR = a backwards-incompatible change to the CLI surface, the JSON output, the exit codes or the
  on-disk formats; MINOR = new commands, flags, adapters or checks; PATCH = fixes.
- **`schema_version`** (`topomark/1`, in every `--json` payload; `topomark.contract.SCHEMA_VERSION`).
  Fields may be added at any time; the major part is bumped only when a field is removed or changes
  meaning.
- **`stamps.json` format** (`version: 2`, `topomark.contract.STAMPS_VERSION`). A new format is read as
  foreign and reported as `STAMPS_FORMAT`; `topomark stamp --baseline --force` migrates after review.

## [Unreleased]

## [0.1.0] - 2026-10-05

### Added

- Navigation commands that work in any git repository: `outline`, `symbol`, `find`, `refs`,
  `impact`, `tests-for` and `map` (a ranked repo map within a token budget).
- Language adapters for C#, Java, JavaScript/TypeScript, Python, shell, SQL, data files (JSON,
  JSONC, TOML, YAML, asmdef) and Markdown, with a plain-text fallback; per-file analysis cache
  outside the repository.
- The code-map doc system: L0 index and L1 area files with frontmatter ownership (`scope`,
  `granularity`, `depth`), `check` (coverage, dead paths, ownership conflicts, line caps, fan-in,
  generated reports, unit counts), `gen`, `sync`, `owner`.
- Review stamps: per-unit interface hashes and content blobs in `stamps.json`; `stamp`, `diff`,
  `stale`; cross-area edge stamps per area.
- `init`: detects languages and project manifests, proposes areas from manifest directories,
  chooses file or directory granularity, suggests excludes for generated code, links existing rule
  files, writes `topomark.toml` and the code-map skeleton in English or Traditional Chinese;
  `--dry-run` writes nothing.
- `draft`: the rows an area file is missing, with summaries from header comments and docstrings and
  the current fan-in; `--write` appends them under the area's file table.
- `hook install|uninstall|status` (opt-in pre-commit gate), `doctor`, `capabilities`.
- Global `--json` with `schema_version`, stable exit codes 0 to 7, `-C/--repo`, `--config`.
- Agent skill `skills/topomark`, Claude Code plugin and marketplace manifests, Codex plugin manifest.
- CI: ruff, mypy, unittest on Linux and Windows, CLI smoke, manifest and skill gates.

[Unreleased]: https://github.com/tipoLi5890/topomark/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tipoLi5890/topomark/releases/tag/v0.1.0
