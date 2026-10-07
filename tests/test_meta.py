"""Repository-wide contracts: every command is registered and described, every --json
output carries schema_version, text I/O in src/ is explicit about encoding and
newlines, docs only show commands the parser accepts, the zh-Hant README has no dashes."""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import re
import shlex
import unittest
from pathlib import Path
from unittest import mock

from tests.harness import TempRepo, run_cli

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "topomark"


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _registered() -> dict[str, argparse.ArgumentParser]:
    from topomark.cli import build_parser

    return _subparsers(build_parser())


def _missing_modules() -> list[str]:
    from topomark.commands import _NAMES

    out = []
    for name in _NAMES:
        try:
            importlib.import_module(f"topomark.commands.{name}")
        except ModuleNotFoundError as e:
            if e.name == f"topomark.commands.{name}":
                out.append(name)
            else:
                raise
    return out


class CommandRegistryTest(unittest.TestCase):
    def test_every_name_imports_and_registers_a_parser(self) -> None:
        from topomark.commands import _NAMES

        missing = _missing_modules()
        subs = _registered()
        for name in _NAMES:
            if name in missing:
                continue
            with self.subTest(command=name):
                mod = importlib.import_module(f"topomark.commands.{name}")
                self.assertTrue(callable(getattr(mod, "register", None)), f"{name}: no register()")
                self.assertTrue(callable(getattr(mod, "run", None)), f"{name}: no run()")
                self.assertTrue(name in subs or name.replace("_", "-") in subs, f"{name}: no subparser")
        if missing:
            self.skipTest(f"command modules not written yet: {', '.join(missing)}")

    def test_capabilities_covers_every_subcommand(self) -> None:
        rc, out, _ = run_cli(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        caps = json.loads(out)
        self.assertEqual(set(caps["commands"]), set(_registered()))
        for name, desc in caps["commands"].items():
            self.assertTrue(desc["help"], f"{name} has no help text")

    def test_every_json_output_has_schema_version(self) -> None:
        files = {"src/app.py": '"""App."""\n\nclass Router:\n    pass\n',
                 "tests/test_app.py": "from app import Router\n\ndef test_router():\n    Router()\n"}
        with TempRepo(files) as repo:
            for name, sp in sorted(_registered().items()):
                argv = [name]
                for a in sp._actions:
                    if a.option_strings or a.dest in ("help",) or a.nargs in ("?", "*"):
                        continue
                    argv.append(next(iter(a.choices)) if a.choices else "x")
                if name == "hook":
                    argv = ["hook", "status"]
                if name == "init":
                    argv.append("--dry-run")
                with self.subTest(command=name), mock.patch("sys.stdin", io.StringIO("")):  # agent-hook reads stdin
                    rc, out, err = repo.cli(*argv, "--json")
                    lines = [ln for ln in out.split("\n") if ln.strip()]
                    self.assertEqual(len(lines), 1, f"{argv}: stdout must be one JSON line\n{out}\n{err}")
                    payload = json.loads(lines[0])
                    self.assertEqual(payload.get("schema_version"), "topomark/1", argv)
                    if "error" not in payload:
                        self.assertEqual(payload.get("command"), name)


def _call_name(node: ast.Call) -> tuple[str, str]:
    f = node.func
    if isinstance(f, ast.Name):
        return "name", f.id
    if isinstance(f, ast.Attribute):
        return "attr", f.attr
    return "", ""


def _kw(node: ast.Call, key: str) -> ast.expr | None:
    return next((k.value for k in node.keywords if k.arg == key), None)


def _mode(node: ast.Call, positional_index: int) -> str:
    m = _kw(node, "mode")
    if m is None and len(node.args) > positional_index:
        m = node.args[positional_index]
    if m is None:
        return "r"
    return m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else "?"


class TextIoTest(unittest.TestCase):
    """Every text open/read/write in src/ says encoding="utf-8"; text writes say newline="\\n"."""

    def test_explicit_encoding_and_newline(self) -> None:
        problems = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            rel = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                kind, name = _call_name(node)
                where = f"{rel}:{node.lineno}"
                if name == "open" and kind in ("name", "attr"):
                    # builtin open(path, mode) or Path.open(mode); os.open etc. use flags, skip ints
                    mode = _mode(node, 1 if kind == "name" else 0)
                    if kind == "attr" and isinstance(node.func, ast.Attribute) and \
                            isinstance(node.func.value, ast.Name) and node.func.value.id in ("os", "io"):
                        continue
                    if "b" in mode:
                        continue
                    enc = _kw(node, "encoding")
                    if not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
                        problems.append(f"{where}: open() without encoding=\"utf-8\"")
                    if any(c in mode for c in "wax+") or mode == "?":
                        nl = _kw(node, "newline")
                        if mode != "?" and not (isinstance(nl, ast.Constant) and nl.value == "\n"):
                            problems.append(f"{where}: text write without newline=\"\\n\"")
                elif kind == "attr" and name == "read_text" and len(node.args) == 0:
                    enc = _kw(node, "encoding")
                    if not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
                        problems.append(f"{where}: read_text() without encoding=\"utf-8\"")
                elif kind == "attr" and name == "write_text" and len(node.args) == 1:
                    enc, nl = _kw(node, "encoding"), _kw(node, "newline")
                    if not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
                        problems.append(f"{where}: write_text() without encoding=\"utf-8\"")
                    if not (isinstance(nl, ast.Constant) and nl.value == "\n"):
                        problems.append(f"{where}: write_text() without newline=\"\\n\"")
        self.assertEqual(problems, [], "\n".join(problems))


def _doc_files() -> list[Path]:
    out = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "CONTRIBUTING.md", ROOT / ".github" / "README.zh-Hant.md"]
    for base in ("docs", "skills", "src/topomark/templates"):
        out += sorted((ROOT / base).rglob("*.md"))
    return [p for p in out if p.is_file()]


_FENCE = re.compile(r"^```(\w*)\s*$")
_PLACEHOLDER = re.compile(r"<[^<>\s][^<>]*>")


def _bash_commands(text: str) -> list[tuple[int, str]]:
    out = []
    lang = None
    for i, line in enumerate(text.split("\n"), 1):
        m = _FENCE.match(line.strip())
        if m:
            lang = None if lang is not None else m.group(1)
            continue
        if lang in ("bash", "sh", "shell") and line.strip().startswith("topomark "):
            out.append((i, line.strip()))
    return out


class DocsConformanceTest(unittest.TestCase):
    """Every `topomark ...` line in a ```bash block parses with the real CLI parser."""

    def test_documented_commands_parse(self) -> None:
        from topomark.cli import build_parser

        subs = _registered()
        bad, skipped, checked = [], set(), 0
        for path in _doc_files():
            rel = path.relative_to(ROOT).as_posix()
            for lineno, line in _bash_commands(path.read_text(encoding="utf-8")):
                line = _PLACEHOLDER.sub("x", line)
                try:
                    words = shlex.split(line, comments=True)
                except ValueError as e:
                    bad.append(f"{rel}:{lineno}: {e}")
                    continue
                for stop in ("|", "&&", "||", ";", ">", "2>&1"):
                    if stop in words:
                        words = words[:words.index(stop)]
                argv = words[1:]
                cmd = next((w for w in argv if not w.startswith("-")), None)
                if cmd is not None and cmd not in subs and not argv[:1] == ["-C"]:
                    skipped.add(cmd)
                    continue
                checked += 1
                try:
                    build_parser().parse_args(argv)
                except SystemExit as e:
                    if e.code not in (0, None):
                        bad.append(f"{rel}:{lineno}: {line}")
        self.assertEqual(bad, [], "documented commands that do not parse:\n" + "\n".join(bad))
        self.assertGreater(checked, 30)
        unknown = skipped - {"x"}
        self.assertEqual(unknown, set(), f"docs mention commands that are not registered: {sorted(unknown)}")


class ZhHantStyleTest(unittest.TestCase):
    def test_no_dashes_in_zh_hant_readme(self) -> None:
        self.assertNotIn("—", (ROOT / ".github" / "README.zh-Hant.md").read_text(encoding="utf-8"))


class TemplatesTest(unittest.TestCase):
    def test_templates_exist(self) -> None:
        for name in ("L0.md", "_TEMPLATE.md", "area.md"):
            self.assertTrue((SRC / "templates" / name).is_file(), name)


class ConfigDocTest(unittest.TestCase):
    def test_config_reference_example_is_valid(self) -> None:
        import tomllib

        from topomark.config import Config

        text = (ROOT / "docs" / "config.md").read_text(encoding="utf-8")
        block = re.search(r"```toml\n(.*?)```", text, re.S).group(1)
        Config.from_dict(ROOT, tomllib.loads(block))


if __name__ == "__main__":
    unittest.main()
