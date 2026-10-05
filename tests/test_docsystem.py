"""The doc system end to end on a small repo: coverage, dead paths, caps, generated
reports, fan-in sync, review stamps (missing → baseline → interface change → diff →
stamp), dir granularity, owner, hook."""

from __future__ import annotations

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
                | `app/services/billing/`（2 檔） | billing |
                | `app/services/mail/`（3 檔） | mail |
                | `app/services/` | entry points |
                """,
        }
        with TempRepo(files) as r:
            r.cli("gen")
            d = r.json("check", "--no-stamps", expect=1)
            self.assertEqual([(p["code"], p["subject"]) for p in d["problems"]],
                             [("UNIT_COUNT", "app/services/mail/")])
            r.write({"docs/codemap/services.md": r.read("docs/codemap/services.md").replace("（3 檔）", "（1 檔）")})
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
