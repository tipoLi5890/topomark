"""``topomark.toml``: per-repo settings. Areas are NOT configured here; each area
file's frontmatter (``scope``, ``granularity``) is the single source of truth.

Every key is optional; ``Config.defaults(root)`` is what a repo without the file
gets. Unknown keys are a CONFIG error so a typo can't silently do nothing.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import CONFIG_FILE
from .errors import TopomarkError
from .repo import DEFAULT_EXCLUDES, outside

# Extensions treated as code when no `required_ext` is configured. The language
# registry may support more; these are the ones that need a row in the code map.
DEFAULT_CODE_EXT: tuple[str, ...] = (
    ".cs", ".java", ".kt", ".kts", ".swift", ".dart", ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".m", ".mm", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".sh", ".bash", ".ps1", ".sql",
    ".gradle", ".asmdef", ".jsonc",
)

DEFAULT_TEST_PATTERNS: tuple[str, ...] = (
    "tests/", "test/", "__tests__/", "**/Tests/**", "test_*.py", "*_test.py", "*.test.ts", "*.test.tsx",
    "*.test.js", "*.test.mjs", "*.spec.ts", "*.spec.tsx", "*.spec.js", "*Tests.cs", "*Test.cs",
    "*_test.dart", "*Test.kt", "*Tests.swift", "*Test.java", "*_test.go",
)

_ALLOWED = {
    "topomark": {"docs_dir", "l0_max", "l1_max", "min_name"},
    "files": {"required_roots", "required_ext", "every_file_roots", "exclude", "include_default_excludes",
              "keep_short_names", "mention_roots"},
    "tests": {"patterns", "runner"},
}
_RUNNER_KEYS = {"match", "command", "names", "join", "max_names", "fallback", "suite"}
_IGNORED = "(ignored: this topomark does not know it; a newer one may)"


@dataclass
class TestRunner:
    """How to print a runnable command for the tests ``tests-for`` selected.

    ``match`` is a path prefix or glob. ``command`` may use ``{file}`` ``{files}``
    ``{class}`` ``{method}`` ``{names}``. ``names`` picks the granularity joined into
    ``{names}``: ``file``, ``class`` or ``method``; above ``max_names`` it falls back
    to ``fallback`` (``class`` or ``file``). ``suite`` (optional) runs every test this
    runner owns; it is printed when a changed file has no test to select."""

    match: str
    command: str
    names: str = "file"
    join: str = " "
    max_names: int = 20
    fallback: str = "file"
    suite: str = ""


@dataclass
class Config:
    root: Path
    path: Path | None = None
    docs_dir: str = "docs/codemap"
    l0_max: int = 160
    l1_max: int = 260
    min_name: int = 5
    required_roots: list[str] = field(default_factory=list)
    required_ext: tuple[str, ...] = DEFAULT_CODE_EXT
    every_file_roots: list[str] = field(default_factory=list)
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    keep_short_names: frozenset[str] = frozenset()
    mention_roots: list[str] = field(default_factory=lambda: ["docs/"])
    test_patterns: tuple[str, ...] = DEFAULT_TEST_PATTERNS
    runners: list[TestRunner] = field(default_factory=list)
    # what the file holds that this version does not know (a newer topomark's keys): ignored, and said once
    warnings: list[str] = field(default_factory=list)

    @property
    def docs_prefix(self) -> str:
        return self.docs_dir.rstrip("/") + "/"

    @classmethod
    def defaults(cls, root: Path) -> "Config":
        return cls(root=root)

    @classmethod
    def load(cls, root: Path, explicit: str | None = None) -> "Config":
        path = Path(explicit).resolve() if explicit else root / CONFIG_FILE
        if not path.is_file():
            if explicit:
                raise TopomarkError("NOT_FOUND", f"config file not found: {path}")
            return cls.defaults(root)
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as e:
            raise TopomarkError("CONFIG", f"{path.name}: {e}") from e
        return cls.from_dict(root, raw, path)

    @classmethod
    def from_dict(cls, root: Path, raw: dict[str, Any], path: Path | None = None) -> "Config":
        where = path.name if path else CONFIG_FILE
        top = raw.get("topomark", {})
        if isinstance(top, dict) and "lang" in top:
            raise TopomarkError("CONFIG", f"{where}: [topomark] lang was removed: topomark writes English only. "
                                          "Delete the `lang = ...` line.")
        cfg = cls(root=root, path=path)
        for section, keys in raw.items():
            if section not in _ALLOWED:
                cfg.warnings.append(f"{where}: unknown section [{section}] {_IGNORED}")
                continue
            if not isinstance(keys, dict):
                raise TopomarkError("CONFIG", f"{where}: [{section}] must be a table")
            for k in keys:
                if k not in _ALLOWED[section]:
                    cfg.warnings.append(f"{where}: unknown key {section}.{k} {_IGNORED}")
        cfg.docs_dir = _str(top, "docs_dir", cfg.docs_dir, where).strip("/")
        if outside(cfg.docs_dir):
            raise TopomarkError("CONFIG", f"{where}: docs_dir must be a folder inside the repository, "
                                          f"not {cfg.docs_dir!r}")
        cfg.l0_max = _int(top, "l0_max", cfg.l0_max, where)
        cfg.l1_max = _int(top, "l1_max", cfg.l1_max, where)
        cfg.min_name = _int(top, "min_name", cfg.min_name, where)
        files = raw.get("files", {})
        cfg.required_roots = _strs(files, "required_roots", [], where)
        if "required_ext" in files:
            cfg.required_ext = tuple(e if e.startswith(".") else "." + e for e in _strs(files, "required_ext", [], where))
        cfg.every_file_roots = _strs(files, "every_file_roots", [], where)
        extra = tuple(_strs(files, "exclude", [], where))
        defaults_too = files.get("include_default_excludes", True)
        if not isinstance(defaults_too, bool):
            raise TopomarkError("CONFIG", f"{where}: include_default_excludes must be true or false")
        if defaults_too is False:
            cfg.exclude = extra
        else:
            cfg.exclude = DEFAULT_EXCLUDES + extra
        cfg.keep_short_names = frozenset(_strs(files, "keep_short_names", [], where))
        if "mention_roots" in files:
            cfg.mention_roots = _strs(files, "mention_roots", [], where)
        tests = raw.get("tests", {})
        if "patterns" in tests:
            cfg.test_patterns = tuple(_strs(tests, "patterns", [], where))
        runners = tests.get("runner", [])
        if not isinstance(runners, list):
            raise TopomarkError("CONFIG", f"{where}: [[tests.runner]] must be an array of tables")
        for i, r in enumerate(runners):
            if not isinstance(r, dict) or "match" not in r or "command" not in r:
                raise TopomarkError("CONFIG", f"{where}: tests.runner[{i}] needs `match` and `command`")
            unknown = set(r) - _RUNNER_KEYS
            if unknown:
                cfg.warnings.append(f"{where}: tests.runner[{i}] unknown keys {sorted(unknown)} {_IGNORED}")
            at = f"{where}: tests.runner[{i}]"
            runner = TestRunner(match=_str(r, "match", "", at), command=_str(r, "command", "", at),
                                names=_str(r, "names", "file", at), join=_str(r, "join", " ", at),
                                max_names=_int(r, "max_names", 20, at), fallback=_str(r, "fallback", "file", at),
                                suite=_str(r, "suite", "", at))
            if runner.names not in ("file", "class", "method") or runner.fallback not in ("file", "class"):
                raise TopomarkError("CONFIG", f"{where}: tests.runner[{i}] names/fallback must be file|class|method")
            cfg.runners.append(runner)
        return cfg


_SEP = {False: ": ", True: " "}  # "topomark.toml: key ..." / "topomark.toml: tests.runner[0] key ..."


def _str(d: dict[str, Any], key: str, default: str, where: str) -> str:
    v = d.get(key, default)
    if not isinstance(v, str):
        raise TopomarkError("CONFIG", f"{where}{_SEP[where[-1:] == ']']}{key} must be a string")
    return v


def _int(d: dict[str, Any], key: str, default: int, where: str) -> int:
    v = d.get(key, default)
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise TopomarkError("CONFIG", f"{where}{_SEP[where[-1:] == ']']}{key} must be a positive integer")
    return v


def _strs(d: dict[str, Any], key: str, default: list[str], where: str) -> list[str]:
    v = d.get(key, default)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise TopomarkError("CONFIG", f"{where}: {key} must be a list of strings")
    return list(v)
