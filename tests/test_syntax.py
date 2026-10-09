"""``syntax``: Python, JSON (JSONC tolerated), TOML parse errors with line and column; bracket
balance in brace languages only when HEAD was balanced; --diff by default; exit 1 on findings;
``syntax.check_file`` needs no index."""

from __future__ import annotations

import argparse
import unittest
from unittest import mock

from tests.harness import TempRepo

FILES = {
    "app/main.py": "def run():\n    return 1\n",
    "app/legacy.py": "def broken(:\n    pass\n",
    "conf/settings.json": '{"a": 1}\n',
    "conf/tsconfig.json": '{\n  // comment\n  "compilerOptions": {"strict": true,},\n}\n',
    "conf/app.toml": 'name = "x"\n',
    "web/view.ts": "export function view(): number {\n  if (true) {\n    return 1;\n  }\n  return 0;\n}\n",
    # a lone brace in JSX text: the masker counts it, so this file is unbalanced at HEAD already
    "web/odd.tsx": "export const A = () => <p>a { b</p>;\nexport function f() { return [1, 2]; }\n",
    "README.md": "# Readme\n",
}


class SyntaxTest(unittest.TestCase):
    def test_strict_parsers(self) -> None:
        with TempRepo(FILES) as r:
            r.write({"app/main.py": "def run(:\n    return 1\n", "conf/settings.json": '{"a": 1,, }\n',
                     "conf/app.toml": 'name = "x"\nname = "y"\n'})
            d = r.json("syntax", expect=1)
            got = {p["path"]: p for p in d["problems"]}
            self.assertEqual(set(got), {"app/main.py", "conf/settings.json", "conf/app.toml"})
            self.assertEqual((got["app/main.py"]["line"], got["app/main.py"]["lang"]), (1, "python"))
            self.assertFalse(got["app/main.py"]["preexisting"])
            self.assertEqual(got["conf/settings.json"]["line"], 1)
            self.assertEqual(got["conf/app.toml"]["line"], 2)
            rc, out, _ = r.cli("syntax")
            self.assertEqual(rc, 1)
            self.assertIn("app/main.py:1:", out)
            self.assertIn("3 problems in 3 files", out)

    def test_jsonc_preexisting_and_not_checkable(self) -> None:
        with TempRepo(FILES) as r:
            d = r.json("syntax", "conf/tsconfig.json", "README.md", "app/legacy.py", expect=1)
            self.assertEqual([p["path"] for p in d["problems"]], ["app/legacy.py"])
            self.assertTrue(d["problems"][0]["preexisting"])  # broken at HEAD too
            self.assertEqual(d["skipped"], [{"path": "README.md", "reason": "no syntax check for markdown"}])
            self.assertIn("conf/tsconfig.json", d["checked"])

    def test_brackets_only_against_a_balanced_head(self) -> None:
        with TempRepo(FILES) as r:
            r.write({"web/view.ts": "export function view(): number {\n  if (true) {\n    return 1;\n  return 0;\n}\n",
                     "web/odd.tsx": "export const A = () => <p>a { b</p>;\nexport function f() { return [1, 2; }\n",
                     "web/fresh.ts": "export function g() {\n"})
            d = r.json("syntax", expect=1)
            self.assertEqual([(p["path"], p["lang"]) for p in d["problems"]], [("web/view.ts", "js")])
            self.assertIn("never closed", d["problems"][0]["message"])
            reasons = {s["path"]: s["reason"] for s in d["skipped"]}
            self.assertIn("unbalanced at HEAD", reasons["web/odd.tsx"])
            self.assertIn("new file", reasons["web/fresh.ts"])

    def test_clean_diff_and_missing(self) -> None:
        with TempRepo(FILES) as r:
            d = r.json("syntax")
            self.assertEqual((d["ok"], d["checked"]), (True, []))
            self.assertIn("no changed files", r.cli("syntax")[1])
            self.assertEqual(r.json("syntax", "nope.py", expect=4)["error"]["code"], "NOT_FOUND")

    def test_python_findings_name_the_interpreter_and_a_newer_requirement(self) -> None:
        import sys

        files = {**FILES, "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.11, <4"\n',
                 "svc/pyproject.toml": '[project]\nname = "svc"\nrequires-python = ">=3.99"\n', "svc/x.py": "X = 1\n"}
        with TempRepo(files) as r:
            r.write({"app/main.py": "def run(:\n", "svc/x.py": "X = (\n"})
            got = {p["path"]: p["message"] for p in r.json("syntax", expect=1)["problems"]}
            ver = f"Python {sys.version_info[0]}.{sys.version_info[1]}"
            self.assertTrue(got["app/main.py"].endswith(f"({ver})"), got)
            self.assertTrue(got["svc/x.py"].endswith(f"({ver}; the project requires >=3.99)"), got)

    def test_swift_raw_strings_are_masked(self) -> None:
        from topomark.masking import mask_file
        from topomark.syntax import imbalance

        for src in ['let s = #"he said "hi(" ok"#\n', 'let s = ##"x "#( "##\n', 'let s = #"a \\"(" b"#\n',
                    'let s = #"""\n  a "(" \\ \n"""#\n', 'let r = #/a(b/#\n', 'let s = #"a\\#(x)("#\n']:
            with self.subTest(src=src):
                self.assertIsNone(imbalance(mask_file("x.swift", src).text))
        self.assertIsNotNone(imbalance(mask_file("x.swift", 'let s = #"ok"# + f(\n').text))  # code after it still counts

    def test_check_file_needs_no_index(self) -> None:
        from topomark import syntax
        from topomark.context import Context

        with TempRepo(FILES) as r:
            r.write({"web/view.ts": "export function view(): number {\n  return 0;\n"})
            ctx = Context(argparse.Namespace(repo=str(r.root), config=None, verbose=0, quiet=True, json=False,
                                             debug=False))
            with mock.patch("topomark.index.Index.all", side_effect=AssertionError("index built")), \
                    mock.patch("topomark.workspace.Workspace.__init__", side_effect=AssertionError("workspace")):
                res = syntax.check_file(ctx, "web/view.ts")
                ok = syntax.check_file(ctx, "app/main.py")
            self.assertEqual([(f.line, f.lang) for f in res.findings], [(1, "js")])
            self.assertEqual((ok.lang, ok.findings, ok.skipped), ("python", [], ""))


if __name__ == "__main__":
    unittest.main()
