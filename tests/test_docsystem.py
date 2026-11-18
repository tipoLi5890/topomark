"""The doc system end to end on a small repo: coverage, dead paths, caps, generated
reports, fan-in sync, review stamps (missing → baseline → interface change → diff →
stamp), dir granularity, owner, hook."""

from __future__ import annotations

import json
import os
import unittest

from tests.harness import TempRepo

CODE = {
    "src/core/router.py": '''
        """Routes requests to handlers."""

        class Router:
            def add(self, path, handler):
                self.routes[path] = handler

        def make_router():
            return Router()
        ''',
    "src/core/store.py": '''
        """Stores records."""

        from .router import Router

        class RecordStore:
            def save(self, record):
                return Router()
        ''',
    "src/web/views.py": '''
        """Web views."""

        from core.router import make_router

        def home():
            return make_router()
        ''',
    "tests/test_router.py": '''
        from core.router import Router

        def test_add():
            Router()
        ''',
}

L0 = """
# Code map
- [core](core.md)
- [web](web.md)
"""

CORE = """
---
area: core
title: Core
summary: routing and storage
scope:
  - src/core/
---

# Core

| file | summary | impact |
|---|---|---|
| `src/core/router.py` | Router | fan-in 0/0 |
| `src/core/store.py` | RecordStore | fan-in 0/0 |
"""

WEB = """
---
area: web
title: Web
summary: views
scope:
  - src/web/
  - tests/
---

# Web

| file | summary |
|---|---|
| `src/web/views.py` | views |
| `tests/test_router.py` | router tests |
"""


def make_repo() -> TempRepo:
    repo = TempRepo({**CODE, "docs/codemap/README.md": L0, "docs/codemap/core.md": CORE, "docs/codemap/web.md": WEB})
    return repo


class DocSystemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = make_repo()

    def tearDown(self) -> None:
        self.repo.close()

    def test_fresh_repo_reports_generated_fanin_and_missing_stamps(self) -> None:
        d = self.repo.json("check", expect=1)
        codes = d["counts"]
        self.assertEqual(codes.get("GENERATED_STALE"), 2)
        self.assertIn("STAMP_MISSING", codes)
        self.assertIn("FANIN_STALE", codes)
        self.assertNotIn("NOT_LISTED", codes)

    def test_full_cycle_to_green(self) -> None:
        r = self.repo
        self.assertEqual(r.cli("gen")[0], 0)
        self.assertEqual(r.cli("sync")[0], 0)
        self.assertIn("fan-in 2/1", r.read("docs/codemap/core.md"))  # store.py + views.py; test_router.py
        self.assertEqual(r.cli("stamp", "--baseline")[0], 0)
        d = r.json("check")
        self.assertTrue(d["ok"], d["problems"])
        # body-only change: check stays green, stale lists it as advisory
        r.write({"src/core/router.py": CODE["src/core/router.py"].replace("self.routes[path] = handler",
                                                                          "self.routes[path] = handler  # noop")})
        self.assertTrue(r.json("check")["ok"])
        s = r.json("stale")
        self.assertEqual(s["body_changed"], {"core": ["src/core/router.py"]})
        # interface change: check fails until the row is reviewed and stamped
        r.write({"src/core/router.py": CODE["src/core/router.py"] + "\n        def remove(self, path):\n            pass\n"})
        d = r.json("check", expect=1)
        self.assertEqual([p["code"] for p in d["problems"]], ["STAMP_CHANGED"])
        diff = r.json("diff", "src/core/router.py")
        self.assertTrue(diff["interface_changed"])
        self.assertTrue(any("remove" in line for line in diff["files"][0]["interface_diff"]))
        self.assertEqual(r.cli("stamp", "src/core/router.py")[0], 0)
        self.assertTrue(r.json("check")["ok"])

    def test_stamps_file_with_conflict_markers_is_a_config_error(self) -> None:
        r = self.repo
        self.assertEqual(r.cli("stamp", "--baseline")[0], 0)
        r.write({"docs/codemap/stamps.json": "<<<<<<< HEAD\n" + r.read("docs/codemap/stamps.json") + ">>>>>>> other\n"})
        err = r.json("check", expect=3)["error"]
        self.assertEqual(err["code"], "CONFIG")
        self.assertIn("docs/codemap/stamps.json is not valid JSON", err["message"])

    def test_blob_id_that_is_not_an_object_id_is_refused_before_git_sees_it(self) -> None:
        """stamps.json comes with the repository; ``git diff <old> <new>`` would take
        ``--output=<file>`` as an option and write that file."""
        import tempfile

        r = self.repo
        for step in ("gen", "sync"):
            self.assertEqual(r.cli(step)[0], 0)
        self.assertEqual(r.cli("stamp", "--baseline")[0], 0)
        unit = "src/core/router.py"
        r.write({unit: CODE[unit] + "\n        def remove(self, path):\n            pass\n"})
        stamps = json.loads(r.read("docs/codemap/stamps.json"))
        with tempfile.TemporaryDirectory() as outside:
            pwned = os.path.join(outside, "pwned")
            for bad in (f"--output={pwned}", "HEAD", "abc", 7):
                stamps["units"][unit]["blobs"][unit] = bad
                r.write({"docs/codemap/stamps.json": json.dumps(stamps)})
                for argv in (["diff", unit], ["check"], ["stale"]):
                    with self.subTest(blob=bad, argv=argv):
                        err = r.json(*argv, expect=3)["error"]
                        self.assertEqual(err["code"], "CONFIG")
                        self.assertIn("not a git object id", err["message"])
            self.assertEqual(os.listdir(outside), [])

    def test_a_stamp_from_another_reading_of_the_same_code_is_not_a_change(self) -> None:
        """After an adapter upgrade the stamped hash differs although nobody touched the file: the
        reviewed blob, read with today's adapter, decides."""
        r = self.repo
        for step in ("gen", "sync"):
            self.assertEqual(r.cli(step)[0], 0)
        self.assertEqual(r.cli("stamp", "--baseline")[0], 0)
        stamps = json.loads(r.read("docs/codemap/stamps.json"))
        unit = "src/core/router.py"
        stamps["units"][unit]["surface"] = "0" * 16  # what an older adapter would have recorded
        r.write({"docs/codemap/stamps.json": json.dumps(stamps)})
        self.assertTrue(r.json("check")["ok"])  # same content as reviewed
        self.assertIn("interface unchanged since review", r.cli("diff", unit)[1])
        # every command that reports the stamp gives check's answer, not the bare hash comparison
        self.assertEqual(r.json("owner", unit)["stamp"], "current")
        self.assertEqual(r.json("impact", unit)["stamp"], "current")
        self.assertEqual(r.json("brief", unit)["area"]["stamp"], "current")
        r.write({unit: CODE[unit].replace("self.routes[path] = handler", "self.routes[path] = handler  # noop")})
        self.assertTrue(r.json("check")["ok"])  # body only: the old blob reads the same today
        self.assertEqual(r.json("stale")["body_changed"], {"core": [unit]})
        r.write({unit: CODE[unit] + "\n        def remove(self, path):\n            pass\n"})
        self.assertEqual([p["code"] for p in r.json("check", expect=1)["problems"]], ["STAMP_CHANGED"])
        self.assertIn("interface CHANGED since review", r.cli("diff", unit)[1])
        # without a record of what was reviewed, the hashes decide
        r.write({unit: CODE[unit]})
        del stamps["units"][unit]["blobs"]
        r.write({"docs/codemap/stamps.json": json.dumps(stamps)})
        self.assertEqual([p["code"] for p in r.json("check", expect=1)["problems"]], ["STAMP_CHANGED"])

    def test_new_file_must_be_listed_and_stamped(self) -> None:
        r = self.repo
        r.cli("gen"), r.cli("sync"), r.cli("stamp", "--baseline")
        r.write({"src/core/cache.py": '"""Cache."""\n\nclass Cache:\n    pass\n'})
        r.cli("gen")
        d = r.json("check", expect=1)
        codes = {p["code"] for p in d["problems"]}
        self.assertIn("NOT_LISTED", codes)
        self.assertIn("STAMP_MISSING", codes)

    def test_dead_path_and_line_cap(self) -> None:
        r = self.repo
        r.write({"topomark.toml": "[topomark]\nl1_max = 5\n",
                 "docs/codemap/web.md": WEB + "\nSee `src/web/gone.py`.\n"})
        codes = r.json("check", expect=1)["counts"]
        self.assertIn("DEAD_PATH", codes)
        self.assertIn("LINE_CAP", codes)

    def test_editing_an_area_file_does_not_bless_other_rows(self) -> None:
        r = self.repo
        r.cli("gen"), r.cli("sync"), r.cli("stamp", "--baseline")
        r.write({"src/core/store.py": CODE["src/core/store.py"] + "\n        def load(self, key):\n            pass\n"})
        r.write({"docs/codemap/core.md": r.read("docs/codemap/core.md").replace("# Core", "# Core (typo fixed)")})
        r.cli("gen")  # `load` is a new top-level function, so the generated table changes too
        d = r.json("check", expect=1)
        self.assertEqual([(p["code"], p["subject"]) for p in d["problems"]], [("STAMP_CHANGED", "src/core/store.py")])

    def test_baseline_refuses_to_overwrite(self) -> None:
        r = self.repo
        r.cli("stamp", "--baseline")
        rc, out, err = r.cli("stamp", "--baseline")
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)

    def test_orphan_stamp_and_prune(self) -> None:
        r = self.repo
        r.cli("gen"), r.cli("sync"), r.cli("stamp", "--baseline")
        os.remove(r.root / "src/web/views.py")
        r.write({"docs/codemap/web.md": WEB.replace("| `src/web/views.py` | views |\n", "").replace("  - src/web/\n", "")})
        r.cli("gen"), r.cli("sync")
        codes = r.json("check", expect=1)["counts"]
        self.assertIn("STAMP_ORPHAN", codes)
        r.cli("stamp", "--prune")
        r.cli("stamp", "--edges", "web"), r.cli("stamp", "--edges", "core")
        self.assertTrue(r.json("check")["ok"], r.json("check", expect=None)["problems"])

    def test_owner(self) -> None:
        d = self.repo.json("owner", "src/core/router.py")
        self.assertEqual(d["area"], "core")
        self.assertEqual(d["fanin"]["prod"], 2)
        self.assertEqual(d["fanin"]["test"], 1)


class DirGranularityTest(unittest.TestCase):
    def test_dir_units_and_counts(self) -> None:
        files = {
            "app/services/billing/invoice.py": "class Invoice:\n    pass\n",
            "app/services/billing/tax.py": "class TaxRule:\n    pass\n",
            "app/services/mail/send.py": "def send_mail():\n    pass\n",
            "app/services/top.py": "def entry():\n    pass\n",
            "docs/codemap/README.md": "[services](services.md)\n",
            "docs/codemap/services.md": """
                ---
                area: services
                title: Services
                summary: service layer
                granularity: dir
                depth: 1
                scope:
                  - app/services/
                ---
                | unit | summary |
                |---|---|
                | `app/services/billing/` (2 files) | billing |
                | `app/services/mail/` (3 files) | mail |
                | `app/services/` | entry points |
                """,
        }
        with TempRepo(files) as r:
            r.cli("gen")
            d = r.json("check", "--no-stamps", expect=1)
            self.assertEqual([(p["code"], p["subject"]) for p in d["problems"]],
                             [("UNIT_COUNT", "app/services/mail/")])
            r.write({"docs/codemap/services.md": r.read("docs/codemap/services.md").replace("(3 files)", "(1 file)")})
            r.cli("stamp", "--baseline")
            self.assertTrue(r.json("check")["ok"])
            r.write({"app/services/billing/tax.py": "class TaxRule:\n    def rate(self):\n        pass\n"})
            d = r.json("check", expect=1)
            self.assertEqual([p["subject"] for p in d["problems"]], ["app/services/billing/"])


class HookTest(unittest.TestCase):
    def test_install_keeps_and_restores_existing_hook(self) -> None:
        with make_repo() as r:
            hooks = r.root / ".git" / "hooks"
            (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            self.assertEqual(r.cli("hook", "install")[0], 0)
            self.assertTrue((hooks / "pre-commit.local").exists())
            self.assertIn("topomark pre-commit gate", (hooks / "pre-commit").read_text(encoding="utf-8"))
            self.assertEqual(r.json("hook", "status")["state"], "installed")
            self.assertEqual(r.cli("hook", "uninstall")[0], 0)
            self.assertEqual((hooks / "pre-commit").read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")


if __name__ == "__main__":
    unittest.main()
