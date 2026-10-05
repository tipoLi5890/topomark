"""``init`` (plan, dry run, write, refuse, force) and ``draft`` (rows, --write, dir units)."""

from __future__ import annotations

import os
import unittest

from tests.harness import TempRepo

CODE = {
    "product/backend/pyproject.toml": '[project]\nname = "backend"\ndescription = "The API server"\n',
    "product/backend/app/router.py": '''
        """Routes requests to handlers."""

        class Router:
            def add(self, path, handler):
                pass
        ''',
    "product/backend/app/store.py": '''
        """Stores records."""

        from .router import Router

        class RecordStore:
            def save(self):
                return Router()
        ''',
    "product/frontend/package.json": '{"name": "frontend", "description": "The web UI"}\n',
    "product/frontend/src/main.ts": "// Boots the UI.\nexport function boot(): void {}\n",
    "scripts/release.sh": "#!/bin/sh\n# Cuts a release.\necho release\n",
    "setup_env.py": '"""Sets up a dev environment."""\n',
    "lib/l10n/app_localizations_en.dart": "class AppLocalizationsEn {}\n",
    "CLAUDE.md": "# Rules\n",
    "product/backend/CLAUDE.md": "# Backend rules\n",
    "product/backend/app/notes.py": '"""See `product/backend/app/store.py` for storage."""\n',
    "tests/test_router.py": "from app.router import Router\n\ndef test_router():\n    Router()\n",
}
# enough code under product/ that init splits it (tiny trees stay one area)
CODE.update({f"product/backend/app/util{i}.py": f'"""Helper {i}."""\n\ndef helper_{i}():\n    pass\n' for i in range(8)})


def snapshot(root) -> dict[str, float]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirpath.split(os.sep):
            continue
        for f in filenames:
            p = os.path.join(dirpath, f)
            out[p] = os.stat(p).st_mtime_ns
    return out


class InitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TempRepo(CODE)

    def tearDown(self) -> None:
        self.repo.close()

    def test_dry_run_writes_nothing(self) -> None:
        before = snapshot(self.repo.root)
        status = self.repo.git("status", "--porcelain", "--untracked-files=all")
        d = self.repo.json("init", "--dry-run")
        self.assertEqual(snapshot(self.repo.root), before)
        self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=all"), status)
        self.assertTrue(d["dry_run"])
        self.assertEqual(d["written"], [])
        self.assertIn("topomark.toml", [w["path"] for w in d["writes"]])

    def test_plan_splits_manifest_dirs_and_links_rules(self) -> None:
        d = self.repo.json("init", "--dry-run")
        scopes = {a["name"]: a["scope"] for a in d["areas"]}
        self.assertEqual(scopes["backend"], ["product/backend/"])
        self.assertEqual(scopes["frontend"], ["product/frontend/"])
        self.assertEqual(scopes["scripts"], ["scripts/"])
        self.assertIn("setup_env.py", scopes["other"])
        summaries = {a["name"]: a["summary"] for a in d["areas"]}
        self.assertEqual(summaries["backend"], "The API server")
        self.assertIn("CLAUDE.md", d["rule_files_l0"])
        self.assertIn("**/l10n/app_localizations*.dart", [e["pattern"] for e in d["excludes"]])
        self.assertEqual(d["unowned"], [])
        self.assertLessEqual(d["l0_lines"], 160)
        self.assertEqual(d["conflicts"], [])

    def test_init_writes_skeleton_and_check_reports_only_expected_problems(self) -> None:
        r = self.repo
        d = r.json("init")
        self.assertIn("docs/codemap/README.md", d["written"])
        self.assertTrue((r.root / "docs/codemap/_TEMPLATE.md").is_file())
        self.assertIn("product/backend/CLAUDE.md", r.read("docs/codemap/backend.md"))
        self.assertIn("app_localizations", r.read("topomark.toml"))
        c = r.json("check", expect=1)
        self.assertLessEqual(set(c["counts"]), {"NOT_LISTED", "STAMP_MISSING", "EDGES_MISSING", "GENERATED_STALE"},
                             c["problems"])
        self.assertIn("NOT_LISTED", c["counts"])

    def test_refuses_to_overwrite_without_force(self) -> None:
        r = self.repo
        r.json("init")
        r.write({"docs/codemap/backend.md": "edited by hand\n"})
        rc, out, err = r.cli("init")
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)
        self.assertEqual(r.read("docs/codemap/backend.md"), "edited by hand\n")
        self.assertEqual(r.cli("init", "--force")[0], 0)
        self.assertIn("area: backend", r.read("docs/codemap/backend.md"))

    def test_zh_hant_and_docs_dir(self) -> None:
        r = self.repo
        r.json("init", "--lang", "zh-Hant", "--docs-dir", "docs/map")
        text = r.read("docs/map/README.md")
        self.assertIn("分區表", text)
        self.assertNotIn("—", text)
        self.assertIn('docs_dir = "docs/map"', r.read("topomark.toml"))
        self.assertIn('lang = "zh-Hant"', r.read("topomark.toml"))


class DraftTest(unittest.TestCase):
    def test_draft_prints_rows_and_write_makes_not_listed_disappear(self) -> None:
        with TempRepo(CODE) as r:
            r.json("init")
            d = r.json("draft", "backend")
            units = {row["unit"]: row for row in d["rows"]}
            self.assertIn("product/backend/app/router.py", units)
            self.assertEqual(units["product/backend/app/router.py"]["summary"], "Routes requests to handlers.")
            self.assertEqual(units["product/backend/app/router.py"]["impact"], "fan-in 1/1")
            rc, out, _ = r.cli("draft", "backend")
            self.assertIn("| `product/backend/app/router.py` | Routes requests to handlers. | fan-in 1/1 |", out)
            self.assertFalse(d["written"])
            # a backticked path in a docstring must not become a backticked path in the row
            self.assertNotIn("`", units["product/backend/app/notes.py"]["summary"])
            self.assertIn("product/backend/app/store.py", units["product/backend/app/notes.py"]["summary"])
            for area in ("backend", "frontend", "scripts", "tests", "other"):
                r.json("draft", area, "--write")
            c = r.json("check", expect=1)
            self.assertNotIn("NOT_LISTED", c["counts"], c["problems"])
            self.assertNotIn("FANIN_STALE", c["counts"], c["problems"])
            again = r.json("draft", "backend", "--write")
            self.assertEqual(again["rows"], [])
            # the rows can be stamped and the map goes green
            r.cli("gen")
            r.cli("stamp", "--baseline")
            self.assertTrue(r.json("check")["ok"], r.json("check", expect=None)["problems"])
            # fan-in in drafted rows is kept current by sync
            r.write({"product/backend/app/extra.py": "from .router import Router\n\nx = Router()\n"})
            r.json("draft", "backend", "--write")
            r.cli("gen")
            self.assertEqual(r.json("check", "--no-stamps", expect=1)["counts"], {"FANIN_STALE": 1})
            r.cli("sync")
            self.assertIn("fan-in 2/1", r.read("docs/codemap/backend.md"))

    def test_draft_dir_granularity_and_zh(self) -> None:
        files = {f"svc/billing/m{i}.py": f'"""Billing part {i}."""\n\nclass Part{i}:\n    pass\n' for i in range(3)}
        files["svc/mail/send.py"] = '"""Sends mail."""\n\ndef send_mail():\n    pass\n'
        files["topomark.toml"] = '[topomark]\nlang = "zh-Hant"\n'
        files["docs/codemap/README.md"] = "[svc](svc.md)\n"
        files["docs/codemap/svc.md"] = ("---\narea: svc\ntitle: Services\nsummary: services\ngranularity: dir\n"
                                        "depth: 1\nscope:\n  - svc/\n---\n\n# Services\n\n## 檔案表\n\n"
                                        "| 單元 | 摘要 | 影響範圍 |\n|---|---|---|\n\n## 延伸閱讀\n")
        with TempRepo(files) as r:
            d = r.json("draft", "svc", "--write")
            rows = {row["unit"]: row for row in d["rows"]}
            self.assertEqual(set(rows), {"svc/billing/", "svc/mail/"})
            self.assertEqual(rows["svc/billing/"]["files"], 3)
            self.assertEqual(rows["svc/billing/"]["summary"], "Billing part 0.")
            self.assertEqual(rows["svc/mail/"]["impact"], "扇入 0／0")
            text = r.read("docs/codemap/svc.md")
            self.assertIn("`svc/billing/`（3 檔）", text)  # the count sits where `check` verifies it
            self.assertLess(text.index("`svc/mail/`"), text.index("## 延伸閱讀"))
            self.assertNotIn("NOT_LISTED", r.json("check", "--no-stamps", expect=None)["counts"])

    def test_draft_creates_table_when_missing_and_unknown_area(self) -> None:
        files = {"a/x.py": '"""X."""\n', "docs/codemap/README.md": "[a](a.md)\n",
                 "docs/codemap/a.md": "---\narea: a\ntitle: A\nsummary: a\nscope:\n  - a/\n---\n\n# A\n"}
        with TempRepo(files) as r:
            r.json("draft", "a", "--write")
            self.assertIn("## Files\n\n| file | summary | impact |\n|---|---|---|\n| `a/x.py` | X. | fan-in 0/0 |",
                          r.read("docs/codemap/a.md"))
            rc, _, err = r.cli("draft", "nope")
            self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main()
