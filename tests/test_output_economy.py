"""Output economy: ``symbol --skeleton`` (declarations kept, bodies elided), ``outline`` over
several files or a directory (top level, token budget, ``{"files": [...]}``), and the capped
text of ``refs`` and ``impact`` (summary first, then the first N, with the flag that shows more)."""

from __future__ import annotations

import unittest

from tests.harness import TempRepo

FILES = {
    "pkg/engine.py": '''
        """Runs jobs."""

        LIMITS = {
            "cpu": 4,
            "mem": 8,
        }


        class Engine:
            """Schedules and runs jobs."""

            def start(self, jobs):
                """Start every job.

                Long explanation.
                """
                for j in jobs:
                    j.run()
                return len(jobs)

            def stop(self):
                return None

            class Policy:
                def allow(self, job):
                    if job:
                        return True
                    return False
        ''',
    "pkg/util.py": "def helper():\n    return 1\n\n\ndef other():\n    return 2\n",
    "pkg/notes.md": "# Notes\n",
    "pkg/sub/deep.py": "class Deep:\n    def m(self):\n        return 1\n",
    "web/panel.ts": '''
        export class Panel {
          render(): string {
            const a = 1;
            return "x" + a;
          }

          size(): number { return 0; }
        }
        ''',
}


class SkeletonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_python_class_keeps_declarations_and_docstring_first_lines(self) -> None:
        d = self.repo.json("symbol", "pkg/engine.py#Engine", "--skeleton")
        m = d["matches"][0]
        text = m["skeleton"]
        self.assertIn("    def start(self, jobs):", text)
        self.assertIn('        """Start every job.', text)
        self.assertNotIn("j.run()", text)
        self.assertNotIn("Long explanation", text)
        self.assertIn("        … (lines 14-19)", text)
        self.assertIn("        return None", text)          # a one-line body costs what its marker would
        self.assertIn("\n    class Policy:\n        def allow(self, job):\n            … (lines 26-28)", text)
        self.assertNotIn("return True", text)
        self.assertEqual(m["elided"], [[14, 19], [26, 28]])
        self.assertNotIn("source", m)

    def test_function_and_constant_and_braces(self) -> None:
        func = self.repo.json("symbol", "pkg/engine.py#Engine.start", "--skeleton")["matches"][0]["skeleton"]
        self.assertEqual(func.split("\n")[0], "    def start(self, jobs):")
        self.assertNotIn("for j in jobs", func)
        const = self.repo.json("symbol", "pkg/engine.py#LIMITS", "--skeleton")["matches"][0]["skeleton"]
        self.assertEqual(const, "LIMITS = {\n    … (lines 4-6)")
        ts = self.repo.json("symbol", "web/panel.ts#Panel", "--skeleton")["matches"][0]["skeleton"]
        self.assertIn("  render(): string {\n    … (lines 3-4)\n  }", ts)
        self.assertIn("size(): number { return 0; }", ts)
        rc, out, _ = self.repo.cli("symbol", "pkg/engine.py#Engine", "--skeleton")
        self.assertEqual(rc, 0)
        self.assertIn("12\t    def start(self, jobs):", out)

    def test_skeleton_and_signature_exclude_each_other(self) -> None:
        self.assertEqual(self.repo.cli("symbol", "pkg/engine.py#Engine", "--skeleton", "--signature")[0], 2)


class MultiOutlineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_directory_expands_to_code_files_top_level_only(self) -> None:
        d = self.repo.json("outline", "pkg")
        self.assertEqual([f["path"] for f in d["files"]], ["pkg/engine.py", "pkg/sub/deep.py", "pkg/util.py"])
        engine = d["files"][0]
        self.assertEqual([s["qualname"] for s in engine["symbols"]], ["LIMITS", "Engine"])
        self.assertEqual((d["depth"], d["truncated"], d["total_files"]), (1, False, 3))
        deeper = self.repo.json("outline", "pkg/engine.py", "pkg/util.py", "--depth", "2")
        self.assertIn("Engine.start", [s["qualname"] for s in deeper["files"][0]["symbols"]])

    def test_single_file_shape_is_unchanged(self) -> None:
        d = self.repo.json("outline", "pkg/engine.py")
        self.assertNotIn("files", d)
        self.assertEqual(d["path"], "pkg/engine.py")
        self.assertIn("Engine.Policy.allow", [s["qualname"] for s in d["symbols"]])

    def test_token_budget_and_missing_paths(self) -> None:
        d = self.repo.json("outline", "pkg", "web", "--tokens", "30")
        self.assertTrue(d["truncated"])
        self.assertEqual(d["shown_files"], 1)
        self.assertEqual(d["total_files"], 4)
        rc, out, _ = self.repo.cli("outline", "pkg", "web", "--tokens", "30")
        self.assertIn("… 3 more files (raise --tokens", out)
        self.assertEqual(self.repo.json("outline", "nope", expect=4)["error"]["code"], "NOT_FOUND")


class CappedTextTest(unittest.TestCase):
    def test_refs_text_is_capped_json_is_not(self) -> None:
        files = {"lib/core.py": "class Widget:\n    pass\n"}
        files.update({f"app/m{i:02}.py": "from lib.core import Widget\n" + "Widget()\n" * 2 for i in range(15)})
        with TempRepo(files) as r:
            rc, out, _ = r.cli("refs", "Widget")
            self.assertIn("Widget: 45 sites in 15 files", out)
            self.assertIn("by group: app/ 45", out)
            self.assertIn("… 25 more sites (--limit N to list more", out)
            self.assertEqual(len(r.json("refs", "Widget")["results"]), 45)
            self.assertNotIn("more sites", r.cli("refs", "Widget", "--limit", "100")[1])
            rc, out, _ = r.cli("impact", "lib/core.py", "--top", "3")
            self.assertIn("… 12 more (--top N lists more)", out)


if __name__ == "__main__":
    unittest.main()
