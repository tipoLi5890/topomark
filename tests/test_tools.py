"""Smoke tests for the dev tools in tools/: the navigation eval runs end to end on a tiny
repo (scoring, skipped kinds and flags, errors apart from misses, controls, stale golds,
--compare with a config the other side rejects), the real task file has no stale gold,
the synthetic repo generator is deterministic, writes the fixed chain files the eval and
the bench rely on and runs no user git hook, and the bench's hook checks hold."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from tests.harness import TempRepo

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"topomark_tools_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


TASKS = '''
[[task]]
id = "find-router"
kind = "find"
query = "rout"
gold = "src/app.py#Router"

[[task]]
id = "search-router"
kind = "search"
query = "router paths"
gold = "src/app.py#Router"

[[task]]
id = "tests-app"
kind = "tests"
query = "src/app.py"
gold = "tests/test_app.py"

[[task]]
id = "find-unknown-flag"
kind = "find"
query = "Router"
args = ["--no-such-flag"]
gold = "src/app.py#Router"

[[task]]
id = "find-control"
kind = "find"
query = "make_router"
args = ["--exact"]
gold = "src/app.py#Router"
expect = "miss"
'''

FILES = {
    "src/app.py": '"""App."""\n\nclass Router:\n    def add(self, path):\n        return path\n\n\ndef make_router():\n    return Router()\n',
    "tests/test_app.py": "import unittest\nfrom app import Router\n\n\nclass TestRouter(unittest.TestCase):\n"
                         "    def test_add(self):\n        Router().add('/')\n",
}

# A runner key no topomark knows: 0.2.0 and older reject it, as a REV before `suite` rejected `suite`.
FUTURE_CONFIG = '[[tests.runner]]\nmatch = "tests/"\ncommand = "python3 -m unittest {names}"\nfrom_the_future = "x"\n'


def _row(id_: str, status: str = "ok", rank: int | None = None, expect: str = "hit", **extra) -> dict:
    row = {"id": id_, "kind": "find", "repo": "self", "gold": ["a.py"], "expect": expect, "rank": rank,
           "hit1": rank == 1, "hit5": rank is not None and rank <= 5, "tokens": 10, "ms": 5, "exit": 0,
           "status": status, **extra}
    if expect == "miss" and status == "ok":
        row["held"] = rank is None
    return row


class EvalNavTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ev = _load("eval_nav")
        cls.repo = TempRepo(FILES)
        cls.tmp = tempfile.TemporaryDirectory(prefix="topomark-eval-test-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()
        cls.tmp.cleanup()

    def run_eval(self, tasks: str, *extra: str, repo: Path | None = None) -> tuple[int, str]:
        path = Path(self.tmp.name) / "tasks.toml"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(tasks)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.ev.main(["--tasks", str(path), "--repo", str(repo or self.repo.root), *extra])
        return rc, out.getvalue() + err.getvalue()

    def test_runs_scores_and_skips(self) -> None:
        from topomark.cli import build_parser

        before = os.environ.get("TOPOMARK_CACHE")
        rc, out = self.run_eval(TASKS, "--json")
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.environ.get("TOPOMARK_CACHE"), before)  # the eval's temp cache is undone
        data = json.loads(out)
        rows = {r["id"]: r for r in data["tasks"]}
        self.assertEqual(rows["find-router"]["status"], "ok")
        self.assertTrue(rows["find-router"]["hit5"])
        self.assertGreater(rows["find-router"]["tokens"], 0)
        self.assertEqual(rows["tests-app"]["rank"], 1)
        have_search = "search" in self.ev._subcommands()
        self.assertEqual(rows["search-router"]["status"] == "skipped", not have_search)
        self.assertEqual(rows["find-unknown-flag"]["status"], "skipped")
        self.assertTrue(rows["find-unknown-flag"]["reason"].startswith("flag not available"))
        self.assertEqual(rows["find-control"]["status"], "ok")
        self.assertTrue(rows["find-control"]["held"])  # make_router --exact does not return Router
        s = data["summary"]["all"]
        self.assertEqual(s["tasks"], 5)
        self.assertEqual((s["controls"], s["controls_held"]), (1, 1))
        self.assertEqual(s["scored"], 3 if have_search else 2)  # the control and the skip are not scored
        self.assertIn("find", data["summary"]["by_kind"])
        self.assertTrue(build_parser())  # the eval leaves the CLI importable and usable
        rc, text = self.run_eval(TASKS)
        self.assertEqual(rc, 0)
        self.assertIn("hit@1", text)
        self.assertIn("controls held 1/1", text)
        self.assertIn("expected miss: held", text)

    def test_refs_impact_and_map_are_read_from_their_answers(self) -> None:
        tasks = '''
[[task]]
id = "impact-router"
kind = "impact"
query = "Router"
gold = "tests/test_app.py"

[[task]]
id = "impact-file"
kind = "impact"
query = "tests/test_app.py"
gold = "tests/test_app.py"
expect = "miss"

[[task]]
id = "refs-router"
kind = "refs"
query = "Router"
gold = "tests/test_app.py"

[[task]]
id = "map-focus"
kind = "map"
args = ["--focus", "tests/test_app.py", "--tokens", "300"]
gold = "src/app.py"

[[task]]
id = "map-focus-is-not-an-answer"
kind = "map"
args = ["--focus", "src/app.py", "--tokens", "300"]
gold = "src/app.py"
expect = "miss"
'''
        rc, out = self.run_eval(tasks, "--json")
        self.assertEqual(rc, 0, out)
        rows = {r["id"]: r for r in json.loads(out)["tasks"]}
        self.assertEqual({i: r["status"] for i, r in rows.items()}, dict.fromkeys(rows, "ok"))
        self.assertIsNotNone(rows["impact-router"]["rank"])
        self.assertTrue(rows["impact-file"]["held"])  # the file asked about is not among its own answers
        self.assertIsNotNone(rows["refs-router"]["rank"])
        self.assertEqual(rows["map-focus"]["rank"], 1)
        self.assertTrue(rows["map-focus-is-not-an-answer"]["held"])  # a file the task names is left out

    def test_stale_gold_exits_2(self) -> None:
        stale = TASKS.replace('gold = "src/app.py#Router"\n\n[[task]]\nid = "search-router"',
                              'gold = "src/app.py#Nope"\n\n[[task]]\nid = "search-router"')
        rc, out = self.run_eval(stale)
        self.assertEqual(rc, 2)
        self.assertIn("no symbol 'Nope'", out)

    def test_expect_must_be_hit_or_miss(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            self.run_eval(TASKS.replace('expect = "miss"', 'expect = "mis"'))
        self.assertIn("expect must be", str(cm.exception))

    def test_candidates_and_rank(self) -> None:
        payload = {"results": [{"path": "a.py", "qualname": "X"}, {"path": "a.py", "qualname": "Y"}],
                   "callers": ["b.py", "not/a/file.py", "c.py#Z"]}
        cands = self.ev.candidates(payload, {"a.py", "b.py", "c.py"})
        self.assertEqual(cands, [("a.py", "X"), ("a.py", "Y"), ("b.py", ""), ("c.py", "Z")])
        self.assertEqual(self.ev.gold_rank(cands, ["a.py#Y"]), 2)
        self.assertEqual(self.ev.gold_rank(cands, ["b.py"]), 2)  # files rank among distinct paths
        self.assertEqual(self.ev.gold_rank(cands, ["c.py#Z"]), 3)
        self.assertIsNone(self.ev.gold_rank(cands, ["d.py"]))

    def test_errors_are_not_misses(self) -> None:
        rows = [_row("hit", rank=1), _row("miss"), _row("bad-config", "error", reason="CONFIG: bad key"),
                _row("crash", "error", reason="crashed: KeyError: 'x'"), _row("skip", "skipped", reason="command not available"),
                _row("control", expect="miss"), _row("control-broken", rank=2, expect="miss")]
        s = self.ev.summarize(rows)["all"]
        self.assertEqual((s["tasks"], s["ran"], s["scored"], s["errors"], s["skipped"]), (7, 4, 2, 2, 1))
        self.assertEqual((s["hit1"], s["missed"], s["hit1_rate"], s["mrr"]), (1, 1, 0.5, 0.5))
        self.assertEqual((s["controls"], s["controls_held"]), (2, 1))
        other = {"rev": "abc1234567890", "tasks": [_row("hit", "error", reason="CONFIG: tests.runner[0] unknown keys"),
                                                   _row("miss", rank=1)],
                 "summary": self.ev.summarize([]), "config_dropped": {"self": ["tests.runner[0].suite"]}}
        text = self.ev.render({"tasks": rows, "summary": self.ev.summarize(rows)}, other)
        lines = {line.split()[0]: line for line in text.splitlines() if line.strip()}
        self.assertIn("err", lines["bad-config"].split())
        self.assertIn("(error: CONFIG: bad key)", lines["bad-config"])
        self.assertIn("@abc1234567: error: CONFIG: tests.runner[0] unknown keys", lines["hit"])  # the other side's why
        self.assertIn("expected miss: NOT held", lines["control-broken"])
        self.assertIn("errors 2", text)
        self.assertIn("controls held 1/2", text)
        self.assertIn("read topomark.toml without tests.runner[0].suite", text)

    def test_config_rejections_are_dropped(self) -> None:
        # One unknown name of each kind, in the words every topomark up to 0.2.0 rejects them with
        # (later versions warn and read on, so only an older REV needs this).
        raw = {"topomark": {"docs_dir": "docs/map", "colour": "red"}, "legacy": {"x": 1},
               "files": {"exclude": ["tests/fixtures/**"], "keep_short_names": []},
               "tests": {"runner": [{"match": "tests/", "command": "pytest {names}", "retries": 2},
                                    {"match": "web/", "command": "npx jest \"{files}\"", "names": "file"}]}}
        dropped: list[str] = []
        for message in ("topomark.toml: unknown section [legacy]", "topomark.toml: unknown key topomark.colour",
                        "topomark.toml: tests.runner[0] unknown keys ['retries']"):
            gone = self.ev.drop_rejected(raw, message)
            self.assertTrue(gone, f"not understood: {message}")
            dropped += gone
        self.assertEqual(sorted(dropped), ["[legacy]", "tests.runner[0].retries", "topomark.colour"])
        self.assertEqual(raw["files"]["exclude"], ["tests/fixtures/**"])  # only what was rejected goes
        self.assertEqual(self.ev.drop_rejected(raw, "a CONFIG error that names no key"), [])
        self.assertEqual(tomllib.loads(self.ev.toml_text(raw)), raw)
        with self.assertRaises(ValueError):
            self.ev.toml_text({"tests": {"runner": [{"match": "x", "when": {"a": [{"b": 1}, 2]}}]}})

    def test_real_tasks_have_no_stale_golds(self) -> None:
        path = TOOLS / "eval" / "tasks.toml"
        tasks = self.ev.load_tasks(path)
        self.assertTrue(any(t["expect"] == "miss" for t in tasks))
        rev = self.ev.snapshot_rev(path)
        self.assertTrue(rev, "tasks.toml pins no snapshot: the self tasks would run on a moving target")
        synth = _load("synth_repo")
        with tempfile.TemporaryDirectory(prefix="topomark-synth-golds-") as tmp:
            try:
                snap = self.ev.export_snapshot(rev, Path(tmp) / "self")
            except self.ev.NoSnapshot as e:
                self.skipTest(f"{e} (a shallow clone has no tags; CI's eval job checks the golds)")
            self.assertFalse((snap / "tools" / "eval").exists())  # the questions are not in the searched text
            self.assertTrue((snap / "src" / "topomark" / "cli.py").is_file())
            synth.generate(Path(tmp) / "synth", files=self.ev.SYNTH_FILES, commit=False)
            targets = {"self": snap, "synth": Path(tmp) / "synth"}
            bad = [b for t in tasks for b in self.ev.stale_golds(t, targets[t["repo"]])]
        self.assertEqual(bad, [])

    def test_locate_gold_that_no_longer_prints_the_message_is_stale(self) -> None:
        files = {"src/io.py": 'def check(path):\n    raise ValueError(f"refusing to read a secret file: {path}")\n\n\n'
                              "def read(path):\n    check(path)\n    return open(path).read()\n"}
        task = '[[task]]\nid = "locate-refusal"\nkind = "locate"\nquery = "ValueError: refusing to read a secret file: .env"\n'
        with TempRepo(files) as repo:
            rc, out = self.run_eval(task + 'gold = "src/io.py#read"\n', repo=repo.root)
            self.assertEqual(rc, 2, out)  # read() exists, but the message moved into check()
            self.assertIn("locate-refusal: src/io.py#read: no two consecutive words of the message", out)
            rc, out = self.run_eval(task + 'gold = "src/io.py#check"\n', "--json", repo=repo.root)
            self.assertEqual(rc, 0, out)
            self.assertEqual(json.loads(out)["tasks"][0]["rank"], 1)

    def test_fail_under_is_a_floor_on_mrr_and_errors(self) -> None:
        self.assertEqual(self.run_eval(TASKS, "--kind", "tests", "--fail-under", "1.0")[0], 0)
        rc, out = self.run_eval(TASKS.replace('gold = "tests/test_app.py"', 'gold = "src/app.py"'),
                                "--kind", "tests", "--fail-under", "0.5")
        self.assertEqual(rc, 1, out)  # tests-for never answers with the file it was asked about
        self.assertIn("below the floor", out)

    def test_compare_reads_a_config_the_other_side_rejects(self) -> None:
        rev = "v0.2.0"  # the last release that rejects a key it does not know
        probe = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", rev, "src"],
                               capture_output=True, check=False)
        if probe.returncode != 0 or not probe.stdout:
            self.skipTest(f"git archive of src/ at {rev} is not available (a shallow clone has no tags)")
        repo = TempRepo({**FILES, "topomark.toml": FUTURE_CONFIG})
        try:
            rc, out = self.run_eval(TASKS, "--compare", rev, "--json", repo=repo.root)
        finally:
            repo.close()
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        mine = {r["id"]: r for r in data["tasks"]}
        theirs = {r["id"]: r for r in data["compare"]["tasks"]}
        self.assertEqual(data["compare"]["rev"], rev)
        self.assertEqual(set(mine), set(theirs))
        # This side reads the file as it is: it warns about the key and runs.
        self.assertEqual(mine["find-router"]["status"], "ok")
        self.assertEqual(data["config_dropped"], {})
        self.assertEqual(data["summary"]["all"]["errors"], 0)
        # The --compare side drops the key it rejects and runs.
        self.assertEqual(data["compare"]["config_dropped"], {"self": ["tests.runner[0].from_the_future"]})
        self.assertEqual(theirs["find-router"]["status"], "ok")
        self.assertTrue(theirs["find-router"]["hit5"])
        self.assertEqual(theirs["tests-app"]["rank"], 1)
        self.assertEqual(data["compare"]["summary"]["all"]["errors"], 0)
        text = self.ev.render(data, data["compare"])
        self.assertIn("without tests.runner[0].from_the_future", text)


class SynthRepoTest(unittest.TestCase):
    def test_deterministic_with_fixed_chain_files(self) -> None:
        synth = _load("synth_repo")
        with tempfile.TemporaryDirectory(prefix="topomark-synth-test-") as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            stats = synth.generate(a, files=60)
            synth.generate(b, files=60, commit=False)
            tracked = subprocess.run(["git", "-C", str(a), "ls-files"], capture_output=True, text=True,
                                     encoding="utf-8", check=True).stdout.split()
            self.assertEqual(len(tracked), stats["files"])
            self.assertGreaterEqual(stats["files"], 60)
            for f in ("py/chain/leaf.py", "py/chain/top.py", "tests/py/test_chain.py", "ts/chain/index.ts",
                      "tests/ts/chain.test.ts", "py/plugins/loader.py", "ts/lazy/routes.ts", "py/big/monolith.py"):
                self.assertIn(f, tracked)
            for f in tracked:
                self.assertEqual((a / f).read_bytes(), (b / f).read_bytes(), f)

    @unittest.skipIf(os.name == "nt", "the hooks below are shell scripts")
    def test_runs_no_user_git_hook(self) -> None:
        synth = _load("synth_repo")
        with tempfile.TemporaryDirectory(prefix="topomark-synth-hooks-") as tmp:
            hooks, marker = Path(tmp) / "hooks", Path(tmp) / "hook-ran"
            hooks.mkdir()
            for name, body in (("pre-commit", "exit 1"), ("post-commit", f"touch '{marker}'")):
                (hooks / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="\n")
                (hooks / name).chmod(0o755)
            # As if the user's global config set core.hooksPath (git >= 2.31 reads these variables).
            env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(hooks)}
            with mock.patch.dict(os.environ, env):
                synth.generate(Path(tmp) / "repo", files=30)
            self.assertFalse(marker.exists())
            branch = subprocess.run(["git", "-C", str(Path(tmp) / "repo"), "symbolic-ref", "--short", "HEAD"],
                                    capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
            self.assertEqual(branch, "main")


class BenchNavTest(unittest.TestCase):
    def test_hook_problem(self) -> None:
        bench = _load("bench_nav")
        answer = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                    "additionalContext": "topomark: big.py has 900 lines. outline it"}})
        self.assertEqual(bench.hook_problem("", None), "")
        self.assertIn("expected no output", bench.hook_problem(answer, None))
        self.assertEqual(bench.hook_problem(answer, ["big.py", "outline"]), "")
        self.assertEqual(bench.hook_problem("", []), "printed nothing")
        self.assertIn("lacks ['syntax']", bench.hook_problem(answer, ["syntax"]))
        self.assertIn("not a hook answer", bench.hook_problem('{"error": {}}', []))

    def test_hooks_say_what_they_must(self) -> None:
        bench, synth = _load("bench_nav"), _load("synth_repo")
        with tempfile.TemporaryDirectory(prefix="topomark-bench-test-") as tmp:
            repo = Path(tmp) / "repo"
            synth.generate(repo, files=40)
            (Path(tmp) / "cache").mkdir()
            env = bench._env(ROOT / "src", Path(tmp) / "cache")
            rows = bench.bench_hooks(repo, env, 1, Path(tmp) / "broken")
            self.assertEqual(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True,
                                            text=True, encoding="utf-8", check=True).stdout, "")  # --repo untouched
        self.assertEqual({r["case"]: r["check"] for r in rows},
                         {"hook-session": "ok", "hook-pre-read": "ok", "hook-post-edit": "ok",
                          "hook-post-edit-broken": "ok"})

    def test_code_map_cases_find_the_changed_interface(self) -> None:
        bench, synth = _load("bench_nav"), _load("synth_repo")
        with tempfile.TemporaryDirectory(prefix="topomark-bench-test-") as tmp:
            repo = Path(tmp) / "repo"
            synth.generate(repo, files=40)
            (Path(tmp) / "cache").mkdir()
            env = bench._env(ROOT / "src", Path(tmp) / "cache")
            rows = bench.bench_codemap(repo, env, 1, Path(tmp) / "codemap")
            self.assertEqual(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True,
                                            text=True, encoding="utf-8", check=True).stdout, "")  # --repo untouched
        self.assertEqual({r["case"]: r["check"] for r in rows},
                         {"check": "ok", "stale": "ok", "gen": "ok", "changes": "ok"})
        self.assertIn("expected one STAMP_CHANGED", bench.codemap_problem("check", '{"problems": []}'))
        big = json.dumps({"problems": [{"code": "STAMP_CHANGED", "subject": "py/core/"}]})  # a directory unit
        self.assertEqual(bench.codemap_problem("check", big), "")


if __name__ == "__main__":
    unittest.main()
