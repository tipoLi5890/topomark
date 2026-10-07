"""agent-hook: the Claude Code plugin hooks read the hook JSON on stdin, answer in the hook
protocol (nothing, or one hookSpecificOutput object), and never fail or block."""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.harness import SRC, TempRepo, run_cli

ROOT = Path(__file__).resolve().parents[1]
EVENTS = {"session-start": "SessionStart", "pre-read": "PreToolUse", "post-edit": "PostToolUse"}


def hook(action: str, payload: dict | str, *extra: str) -> tuple[int, str, str]:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    with mock.patch("sys.stdin", io.StringIO(stdin)):
        return run_cli(["agent-hook", action, *extra])


def area(name: str, scope: str, title: str = "") -> str:
    return f"---\narea: {name}\ntitle: {title or name.title()}\nsummary: x\nscope:\n  - {scope}\n---\n\n# {name}\n"


BIG = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(160))  # 480 lines


def mapped_repo() -> TempRepo:
    return TempRepo({
        "docs/codemap/README.md": "# Code map\n",
        "docs/codemap/core.md": area("core", "src/core/", "Core logic"),
        "docs/codemap/web.md": area("web", "web/"),
        "src/core/big.py": BIG,
        "src/core/small.py": "def small():\n    return 1\n",
        "src/core/other.py": "def other():\n    return 2\n",
        "web/app.ts": "export function app() {\n  return 1;\n}\n",
        "notes.txt": "plain\n" * 500,
    })


class HookTest(unittest.TestCase):
    def context(self, rc: int, out: str, event: str) -> str:
        self.assertEqual(rc, 0, out)
        doc = json.loads(out)
        self.assertEqual(set(doc), {"hookSpecificOutput"})
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], event)
        return doc["hookSpecificOutput"]["additionalContext"]

    def silent(self, rc: int, out: str) -> None:
        self.assertEqual((rc, out), (0, ""))


class SessionStartTest(HookTest):
    def test_lists_l0_areas_commands_and_stamp_state(self) -> None:
        with mapped_repo() as repo:
            payload = {"session_id": "s", "cwd": str(repo.root), "source": "startup"}
            text = self.context(*hook("session-start", payload)[:2], "SessionStart")
            self.assertIn("docs/codemap/README.md", text)
            self.assertIn("- core: docs/codemap/core.md (Core logic)", text)
            self.assertIn("- web: docs/codemap/web.md", text)
            for cmd in ("topomark outline", "topomark symbol", "--skeleton", "topomark brief", "topomark locate",
                        "topomark search", "topomark syntax"):
                self.assertIn(cmd, text)
            self.assertIn("No review stamps", text)
            self.assertNotIn("# Code map", text)  # pointers only, no L0 prose
            repo.write({"docs/codemap/stamps.json": "{}\n"})
            text = self.context(*hook("session-start", payload)[:2], "SessionStart")
            self.assertIn("Review stamps are on", text)

    def test_caps_lines_and_bytes(self) -> None:
        files = {f"docs/codemap/a{i:02}.md": area(f"a{i:02}", f"pkg{i:02}/", "A very long area title " * 6)
                 for i in range(60)}
        files["docs/codemap/README.md"] = "# Code map\n"
        with TempRepo(files) as repo:
            text = self.context(*hook("session-start", {"cwd": str(repo.root)})[:2], "SessionStart")
            self.assertLessEqual(len(text.split("\n")), 40)
            self.assertLessEqual(len(text.encode("utf-8")), 4096)
            self.assertIn("more areas: see docs/codemap/README.md", text)

    def test_without_a_code_map_one_line(self) -> None:
        with TempRepo({"src/app.py": "x = 1\n"}) as repo:
            text = self.context(*hook("session-start", {"cwd": str(repo.root)})[:2], "SessionStart")
            self.assertEqual(text.count("\n"), 0)
            self.assertIn("topomark map --tokens 2000", text)

    def test_invalid_config_says_so(self) -> None:
        with TempRepo({"topomark.toml": "[nope]\n", "src/app.py": "x = 1\n"}) as repo:
            text = self.context(*hook("session-start", {"cwd": str(repo.root)})[:2], "SessionStart")
            self.assertIn("topomark doctor", text)


class SilenceTest(HookTest):
    def test_outside_git_broken_payload_and_unknown_action_are_silent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for action in EVENTS:
                payload = {"session_id": "s", "cwd": d, "tool_input": {"file_path": os.path.join(d, "a.py")}}
                with self.subTest(action=action):
                    self.silent(*hook(action, payload)[:2])
                    rc, out, _ = hook(action, payload, "--json")
                    self.assertEqual(rc, 0)
                    self.assertNotIn("error", json.loads(out))
        with mapped_repo() as repo:
            for action in EVENTS:
                for bad in ("{not json", "[1, 2]", "\x00\xff", "null"):
                    with self.subTest(action=action, payload=bad):
                        self.silent(*hook(action, bad)[:2])
                        rc, out, _ = hook(action, bad, "--json")
                        self.assertEqual(rc, 0)
                        self.assertNotIn("error", json.loads(out))
            self.silent(*hook("bogus", {"cwd": str(repo.root)})[:2])
            with mock.patch("sys.stdin", io.StringIO("")):
                self.silent(*run_cli(["agent-hook"])[:2])

    def test_real_stdin_bytes_in_a_subprocess(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONUTF8="1")
        with mapped_repo() as repo:
            payload = {"session_id": "sub", "cwd": str(repo.root), "tool_name": "Read",
                       "tool_input": {"file_path": str(repo.root / "src/core/big.py")}}
            for data, speaks in ((json.dumps(payload).encode("utf-8"), True), (b"\xff\xfe{", False)):
                p = subprocess.run([sys.executable, "-m", "topomark", "agent-hook", "pre-read"], input=data,
                                   capture_output=True, env=env, cwd=str(repo.root), timeout=60)
                self.assertEqual(p.returncode, 0, p.stderr)
                if speaks:
                    self.assertIn("topomark outline src/core/big.py", self.context(0, p.stdout.decode(), "PreToolUse"))
                else:
                    self.assertEqual(p.stdout, b"")


class PreReadTest(HookTest):
    def read(self, repo: TempRepo, path: str, session: str = "s1", **extra) -> tuple[int, str]:
        payload = {"session_id": session, "cwd": str(repo.root), "hook_event_name": "PreToolUse",
                   "tool_name": "Read", "tool_input": {"file_path": str(repo.root / path), **extra}}
        return hook("pre-read", payload)[:2]

    def test_large_file_hint_once_per_session(self) -> None:
        with mapped_repo() as repo:
            text = self.context(*self.read(repo, "src/core/big.py"), "PreToolUse")
            self.assertIn("src/core/big.py has 480 lines", text)
            self.assertIn("topomark outline src/core/big.py", text)
            self.assertIn("--skeleton", text)
            self.assertIn("area `core`; docs/codemap/core.md", text)
            self.silent(*self.read(repo, "src/core/big.py"))
            text = self.context(*self.read(repo, "src/core/big.py", session="s2"), "PreToolUse")
            self.assertIn("480 lines", text)

    def test_area_hint_once_per_area(self) -> None:
        with mapped_repo() as repo:
            text = self.context(*self.read(repo, "src/core/small.py"), "PreToolUse")
            self.assertNotIn("lines", text)
            self.assertIn("docs/codemap/core.md", text)
            self.silent(*self.read(repo, "src/core/other.py"))
            self.assertIn("docs/codemap/web.md", self.context(*self.read(repo, "web/app.ts"), "PreToolUse"))

    def test_reading_the_area_file_counts_as_the_hint(self) -> None:
        with mapped_repo() as repo:
            self.silent(*self.read(repo, "docs/codemap/core.md"))
            self.silent(*self.read(repo, "src/core/small.py"))

    def test_silent_cases(self) -> None:
        with mapped_repo() as repo:
            self.silent(*self.read(repo, "src/core/big.py", offset=1, limit=50))
            self.silent(*self.read(repo, "src/core/big.py", limit=50))
            self.silent(*self.read(repo, "notes.txt"))              # no language adapter
            self.silent(*self.read(repo, "src/core/missing.py"))
            payload = {"session_id": "s1", "cwd": str(repo.root), "tool_input": {"file_path": "/etc/hosts.py"}}
            self.silent(*hook("pre-read", payload)[:2])            # outside the repo
            payload = {"cwd": str(repo.root), "tool_input": {"file_path": str(repo.root / "src/core/big.py")}}
            self.silent(*hook("pre-read", payload)[:2])            # no session id: can't promise "once"

    def test_relative_path_resolves_against_cwd(self) -> None:
        with mapped_repo() as repo:
            payload = {"session_id": "rel", "cwd": str(repo.root / "src"), "tool_input": {"file_path": "core/big.py"}}
            self.assertIn("src/core/big.py has 480 lines", self.context(*hook("pre-read", payload)[:2], "PreToolUse"))

    def test_compact_forgets_the_session_hints(self) -> None:
        with mapped_repo() as repo:
            self.context(*self.read(repo, "src/core/big.py"), "PreToolUse")
            self.silent(*self.read(repo, "src/core/big.py"))
            hook("session-start", {"session_id": "s1", "cwd": str(repo.root), "source": "compact"})
            self.assertIn("480 lines", self.context(*self.read(repo, "src/core/big.py"), "PreToolUse"))


class PostEditTest(HookTest):
    def edit(self, repo: TempRepo, path: str, tool: str = "Edit") -> tuple[int, str]:
        payload = {"session_id": "e", "cwd": str(repo.root), "hook_event_name": "PostToolUse", "tool_name": tool,
                   "tool_input": {"file_path": str(repo.root / path)}}
        return hook("post-edit", payload)[:2]

    def test_reports_only_errors_the_edit_caused(self) -> None:
        with TempRepo({"src/good.py": "def f():\n    return 1\n", "src/old_bad.py": "def f(:\n",
                       "conf/a.json": '{"a": 1}\n', "web/app.ts": "export function app() {\n  return 1;\n}\n",
                       "README.md": "# x\n"}) as repo:
            self.silent(*self.edit(repo, "src/good.py"))
            repo.write({"src/good.py": "def f(:\n    return 1\n"})
            text = self.context(*self.edit(repo, "src/good.py"), "PostToolUse")
            self.assertIn("src/good.py:1", text)
            self.assertIn("no longer parses", text)
            self.silent(*self.edit(repo, "src/old_bad.py"))            # HEAD did not parse either
            repo.write({"conf/a.json": '{"a": 1,,}\n', "web/app.ts": "export function app() {\n  return 1;\n"})
            self.assertIn("conf/a.json:1", self.context(*self.edit(repo, "conf/a.json", "Write"), "PostToolUse"))
            self.assertIn("web/app.ts", self.context(*self.edit(repo, "web/app.ts", "MultiEdit"), "PostToolUse"))
            self.silent(*self.edit(repo, "README.md"))
            repo.write({"src/new.py": "class (\n"})
            self.assertIn("src/new.py:1", self.context(*self.edit(repo, "src/new.py", "Write"), "PostToolUse"))

    def test_quiet_about_python_when_the_project_needs_a_newer_one(self) -> None:
        with TempRepo({"svc/pyproject.toml": '[project]\nname = "svc"\nrequires-python = ">=3.99"\n',
                       "svc/app.py": "def f():\n    return 1\n", "other/app.py": "def g():\n    return 1\n"}) as repo:
            repo.write({"svc/app.py": "def f(:\n", "other/app.py": "def g(:\n"})
            self.silent(*self.edit(repo, "svc/app.py"))  # may be valid for Python 3.99
            self.assertIn("other/app.py:1", self.context(*self.edit(repo, "other/app.py"), "PostToolUse"))

    def test_oversized_payload_is_silence(self) -> None:
        from topomark.commands.agent_hook import MAX_PAYLOAD

        with TempRepo({"src/good.py": "def f():\n    return 1\n"}) as repo:
            repo.write({"src/good.py": "def f(:\n"})
            payload = {"session_id": "e", "cwd": str(repo.root), "tool_name": "Write",
                       "tool_input": {"file_path": str(repo.root / "src/good.py"), "content": "x" * MAX_PAYLOAD}}
            self.silent(*hook("post-edit", payload)[:2])
            payload["tool_input"]["content"] = "x"
            self.assertIn("src/good.py:1", self.context(*hook("post-edit", payload)[:2], "PostToolUse"))


class HookStartupTest(unittest.TestCase):
    def test_cli_import_stays_light(self) -> None:
        code = (f"import sys; sys.path.insert(0, {str(SRC)!r}); import topomark.cli; "
                "print(sorted(m for m in ('traceback', 'inspect') if m in sys.modules))")
        out = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, encoding="utf-8",
                             check=True).stdout
        self.assertNotIn("traceback", out)  # ~20 ms of imports on every hook call; imported when needed


class HooksJsonTest(unittest.TestCase):
    def test_plugin_hooks_file(self) -> None:
        from topomark.cli import build_parser

        with open(ROOT / "hooks" / "hooks.json", encoding="utf-8") as fh:
            doc = json.load(fh)
        hooks = doc["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreToolUse", "PostToolUse"})
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|clear|compact")
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Read")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Edit|Write|MultiEdit")
        prefix = '"${CLAUDE_PLUGIN_ROOT}"/bin/topomark '
        for event, groups in hooks.items():
            for group in groups:
                for h in group["hooks"]:
                    with self.subTest(event=event):
                        self.assertEqual(h["type"], "command")
                        self.assertIsInstance(h["timeout"], int)   # seconds
                        self.assertLessEqual(h["timeout"], 10)
                        self.assertTrue(h["command"].startswith(prefix), h["command"])
                        argv = shlex.split(h["command"][len(prefix):])
                        self.assertNotIn("--json", argv)
                        args = build_parser().parse_args(argv)
                        self.assertEqual(args.command, "agent-hook")
                        self.assertEqual(EVENTS[args.action], event)


if __name__ == "__main__":
    unittest.main()
