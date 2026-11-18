"""Repository-wide contracts: every command is registered and described, every --json
output carries schema_version, text I/O in src/ is explicit about encoding and
newlines, docs only show commands the parser accepts, the translated READMEs have no dashes and link each other."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.harness import TempRepo, run_cli

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "topomark"
TRANSLATED_READMES = [ROOT / ".github" / f"README.{lang}.md" for lang in ("zh-Hant", "zh-Hans", "ja")]


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _registered() -> dict[str, argparse.ArgumentParser]:
    from topomark.cli import build_parser

    return _subparsers(build_parser())


class CommandRegistryTest(unittest.TestCase):
    def test_every_name_imports_and_registers_a_parser(self) -> None:
        from topomark.commands import _NAMES, COMMAND_MODULES

        modules = COMMAND_MODULES()
        self.assertEqual([m.__name__.rsplit(".", 1)[-1] for m in modules], _NAMES)
        on_disk = sorted(p.stem for p in (SRC / "commands").glob("*.py") if not p.stem.startswith("_"))
        self.assertEqual(sorted(_NAMES), on_disk, "a command module is missing from commands._NAMES (or the reverse)")
        subs = _registered()
        for name, mod in zip(_NAMES, modules, strict=True):
            with self.subTest(command=name):
                self.assertTrue(callable(getattr(mod, "register", None)), f"{name}: no register()")
                self.assertTrue(callable(getattr(mod, "run", None)), f"{name}: no run()")
                self.assertTrue(name in subs or name.replace("_", "-") in subs, f"{name}: no subparser")

    def test_capabilities_covers_every_subcommand(self) -> None:
        rc, out, _ = run_cli(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        caps = json.loads(out)
        self.assertEqual(set(caps["commands"]), set(_registered()))
        for name, desc in caps["commands"].items():
            self.assertTrue(desc["help"], f"{name} has no help text")

    def test_json_without_a_command_is_a_usage_envelope(self) -> None:
        rc, out, err = run_cli(["--json"])
        self.assertEqual((rc, err), (2, ""))
        payload = json.loads(out)
        self.assertEqual((payload["schema_version"], payload["error"]["code"]), ("topomark/1", "USAGE"))
        rc, out, err = run_cli([])
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("usage: topomark", err)

    @unittest.skipIf(os.name == "nt", "a closed pipe is reported differently on Windows")
    def test_a_reader_that_leaves_early_is_not_an_error(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
        p = subprocess.Popen([sys.executable, "-m", "topomark", "-C", str(ROOT), "outline", "src", "tests", "tools",
                              "--tokens", "400000", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        assert p.stdout is not None and p.stderr is not None
        p.stdout.read(10)
        p.stdout.close()  # like `| head -c 10`: the rest of the output has nowhere to go
        err = p.stderr.read().decode("utf-8", errors="replace")
        p.stderr.close()
        self.assertEqual((p.wait(), err), (0, ""))

    def test_doctor_reports_each_check_and_fails_only_on_a_real_problem(self) -> None:
        with TempRepo({"src/app.py": "X = 1\n", ".env": "TOKEN=1\n"}) as repo:
            d = repo.json("doctor")
            checks = {c["name"]: c for c in d["checks"]}
            self.assertTrue(d["ok"])
            self.assertEqual(set(checks), {"python", "git", "repo", "config", "secrets", "docs_dir", "files", "cache"})
            self.assertEqual(checks["secrets"]["status"], "warn")  # git tracks .env: said, not a failure
            self.assertIn("1 tracked by git: .env", checks["secrets"]["detail"])
            self.assertIn("no topomark.toml", checks["config"]["detail"])
            self.assertIn("WARN secrets", repo.cli("doctor")[1])
            repo.write({"topomark.toml": '[topomark]\nl0_max = "many"\n'})
            bad = repo.json("doctor", expect=1)  # a config it cannot read: exit 1, and it still answers
            self.assertFalse(bad["ok"])
            failed = [c for c in bad["checks"] if c["status"] == "fail"]
            self.assertEqual([c["name"] for c in failed], ["config"])
            self.assertIn("l0_max must be a positive integer", failed[0]["detail"])
        with tempfile.TemporaryDirectory() as plain:
            rc, out, _ = run_cli(["-C", plain, "doctor", "--json"])
            self.assertEqual(rc, 1)
            self.assertEqual([c["name"] for c in json.loads(out)["checks"] if c["status"] == "fail"], ["repo"])

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
    out = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "CONTRIBUTING.md", *TRANSLATED_READMES]
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


class OneCommandParserTest(unittest.TestCase):
    """The CLI builds the parser of the command it was given only (every plugin hook pays for the
    rest otherwise), and that must never change what a command line means."""

    def test_the_command_word_is_found_only_behind_spelled_out_global_flags(self) -> None:
        from topomark.cli import _command_in

        for argv, want in ((["check"], "check"), (["-C", "x", "--json", "-vv", "owner", "a.py"], "owner"),
                           (["--repo=x", "--config", "c.toml", "-q", "tests-for"], "tests-for"),
                           (["-Cx", "map"], "map"), (["--version"], None), ([], None),
                           (["--help", "check"], None), (["-h"], None), (["--", "check"], None),
                           (["--rep", "check", "outline"], None), (["--unknown", "check"], None)):
            with self.subTest(argv=argv):
                self.assertEqual(_command_in(argv), want)

    def test_one_command_parses_like_the_whole_parser(self) -> None:
        from topomark.cli import build_parser

        whole = build_parser()
        for name in _registered():
            with self.subTest(command=name):
                one = _subparsers(build_parser(name))
                self.assertEqual(list(one), [name])
                self.assertEqual(one[name].format_help(), _subparsers(whole)[name].format_help())
        for word in ("tests_for", "agent_hook", "nonsense", "_common"):
            with self.subTest(word=word):  # not a command as typed: argparse reports every choice
                self.assertEqual(list(_subparsers(build_parser(word))), list(_subparsers(whole)))

    def test_a_hook_call_imports_one_command_module(self) -> None:
        code = ("import sys; from topomark.cli import main; main(['agent-hook', 'pre-read']); "
                "print(sorted(m for m in sys.modules if m.startswith('topomark.commands.')))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                             input="{}", env={**os.environ, "PYTHONPATH": str(SRC.parent)}, check=True).stdout
        self.assertEqual(out.strip().splitlines()[-1], "['topomark.commands._common', 'topomark.commands.agent_hook']")


class TranslatedReadmeTest(unittest.TestCase):
    def test_no_dashes(self) -> None:
        for path in TRANSLATED_READMES:
            with self.subTest(path=path.name):
                self.assertNotIn("—", path.read_text(encoding="utf-8"))

    def test_each_links_the_others(self) -> None:
        names = ["README.md", *(p.name for p in TRANSLATED_READMES)]
        for path in [ROOT / "README.md", *TRANSLATED_READMES]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for other in names:
                    if other != path.name:
                        self.assertIn(f"{other})", text, f"{path.name} does not link {other}")


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
