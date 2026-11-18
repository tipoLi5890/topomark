"""``locate``: a printed message back to the code that formats it (interpolated values, strings
split across lines, code before tests before docs), --regex, and stack traces in each supported
format mapped to repo files by the longest path suffix, innermost frame first."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest import mock

from tests.harness import TempRepo

FILES = {
    "src/app/store.py": '''
        """Storage."""


        def load_record(key, version):
            if version > 3:
                raise ValueError(f"record {key} uses format {version}; this build reads "
                                 f"format 3. Migrate it first.")
            return key


        def other():
            return "nothing to see"
        ''',
    "src/app/util.py": "def helper():\n    return 1\n",
    "lib/util.py": "def helper():\n    return 2\n",
    "tests/test_store.py": '''
        import unittest
        from app.store import load_record

        class StoreTest(unittest.TestCase):
            def test_message(self):
                self.assertIn("this build reads format 3", "x")
        ''',
    "docs/errors.md": "# Errors\n\n`record K uses format 5; this build reads format 3. Migrate it first.`\n",
    "web/app.js": "function boot() {\n  const x = 1;\n  throw new Error('boom');\n}\n",
    "src/main/java/com/acme/Billing.java": "package com.acme;\npublic class Billing {\n  void charge() {\n    int a = 1 / 0;\n  }\n}\n",
    "game/Pad.cs": "namespace Game {\n  public class Pad {\n    public void Tick() {\n      var a = 1;\n      throw new System.Exception();\n    }\n  }\n}\n",
    "svc/main.go": "package main\n\nfunc main() {\n\tpanic(\"x\")\n}\n\nfunc helper() {\n\tmain()\n}\n",
    "crate/src/lib.rs": "pub fn run() {\n    let v: Vec<i32> = vec![];\n    v[0];\n}\n",
    "app/lib/main.dart": "void main() {\n  print('a');\n  throw Exception('x');\n}\n",
    "web/ui.ts": "export function draw(): number {\n  const n: number = 'x';\n  return n;\n}\n",
}

PY_TRACE = '''Traceback (most recent call last):
  File "/usr/lib/python3.12/runpy.py", line 198, in _run_module_as_main
    return _run_code(code, main_globals, None,
  File "/home/ci/build/checkout/src/app/store.py", line 7, in load_record
    raise ValueError(...)
ValueError: record k uses format 5
'''


class LocateMessageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_interpolated_and_split_message_code_first(self) -> None:
        d = self.repo.json("locate", "ValueError: record k7 uses format 5; this build reads format 3. Migrate it first.")
        got = [(r["path"], r["qualname"], r["group"]) for r in d["results"]]
        self.assertEqual(got[0], ("src/app/store.py", "load_record", "code"))
        self.assertEqual([g for _, _, g in got], sorted([g for _, _, g in got], key=["code", "test", "doc"].index))
        self.assertIn(("tests/test_store.py", "StoreTest.test_message", "test"), got)
        self.assertIn("docs/errors.md", [p for p, _, _ in got])
        self.assertEqual(d["results"][0]["line"], 6)  # the first line of the split string

    def test_short_literal_regex_and_nothing(self) -> None:
        d = self.repo.json("locate", "nothing to see")
        self.assertEqual([(r["path"], r["qualname"]) for r in d["results"]], [("src/app/store.py", "other")])
        rx = self.repo.json("locate", r"raise \w+Error", "--regex")
        self.assertEqual(rx["mode"], "regex")
        self.assertEqual(rx["results"][0]["qualname"], "load_record")
        none = self.repo.json("locate", "completely absent words here")
        self.assertEqual((none["total"], none["results"]), (0, []))
        self.assertEqual(self.repo.json("locate", "(", "--regex", expect=2)["error"]["code"], "USAGE")
        self.assertEqual(self.repo.json("locate", expect=2)["error"]["code"], "USAGE")


    def test_quotes_in_tests_and_docs_do_not_hide_the_source(self) -> None:
        # the source only shares the two-word run "unknown section" with the printed message; four
        # files quoting the whole message must not make that run look common to the code
        quote = 'MSG = "app.toml: unknown section [tool]"\n'
        with TempRepo({
            "src/conf.py": 'def load(where, section):\n    raise ValueError(f"{where}: unknown section [{section}]")\n',
            "tests/test_a.py": quote, "tests/test_b.py": quote, "tests/test_c.py": quote,
            "docs/errors.md": "`app.toml: unknown section [tool]`\n",
        }) as r:
            d = r.json("locate", "app.toml: unknown section [tool]")
            self.assertEqual((d["results"][0]["path"], d["results"][0]["qualname"]), ("src/conf.py", "load"))


class LocateTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)
        cls.tmp = tempfile.TemporaryDirectory(prefix="topomark-trace-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()
        cls.tmp.cleanup()

    def trace(self, text: str, expect: int = 0, name: str = "trace.txt") -> dict:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return self.repo.json("locate", "--trace", path, expect=expect)

    def frames(self, text: str) -> list[tuple[str, int, str]]:
        return [(f["path"], f["line"], f["qualname"]) for f in self.trace(text)["results"]]

    def test_python_innermost_first_and_outside_skipped(self) -> None:
        d = self.trace(PY_TRACE)
        self.assertEqual([(f["path"], f["line"], f["qualname"]) for f in d["results"]],
                         [("src/app/store.py", 7, "load_record")])
        self.assertEqual(d["skipped"][0]["path"], "/usr/lib/python3.12/runpy.py")
        self.assertEqual(d["formats"], ["python"])

    def test_each_format(self) -> None:
        self.assertEqual(self.frames("Error: boom\n    at boot (/srv/www/web/app.js:3:9)\n    at /srv/www/node_modules/x/i.js:1:1\n"),
                         [("web/app.js", 3, "boot")])
        self.assertEqual(self.frames("boot@http://localhost/web/app.js:3:9\n"), [("web/app.js", 3, "boot")])
        self.assertEqual(self.frames("java.lang.ArithmeticException: / by zero\n\tat com.acme.Billing.charge(Billing.java:4)\n"
                                     "\tat java.base/java.lang.Thread.run(Thread.java:833)\n"),
                         [("src/main/java/com/acme/Billing.java", 4, "Billing.charge")])
        self.assertEqual(self.frames("System.Exception: x\n   at Game.Pad.Tick() in C:\\build\\repo\\game\\Pad.cs:line 5\n"),
                         [("game/Pad.cs", 5, "Pad.Tick")])
        self.assertEqual(self.frames("panic: x\n\ngoroutine 1 [running]:\nmain.main()\n\t/home/u/proj/svc/main.go:4 +0x1d\n"
                                     "main.helper()\n\t/home/u/proj/svc/main.go:8 +0x11\n"),
                         [("svc/main.go", 4, "main"), ("svc/main.go", 8, "helper")])
        self.assertEqual(self.frames("goroutine 1 [running]:\nmain.main()\n\tC:/Users/u/proj/svc/main.go:4 +0x1d\n"),
                         [("svc/main.go", 4, "main")])  # a drive letter is part of the path, not the line separator
        self.assertEqual(self.frames("thread 'main' panicked at crate/src/lib.rs:3:5:\nindex out of bounds\n"),
                         [("crate/src/lib.rs", 3, "run")])
        self.assertEqual(self.frames("#0      main (package:app/main.dart:3:3)\n#1      _start (dart:isolate-patch/x.dart:1:1)\n"),
                         [("app/lib/main.dart", 3, "main")])
        self.assertEqual(self.frames("web/ui.ts(2,9): error TS2322: Type 'string' is not assignable to type 'number'.\n"),
                         [("web/ui.ts", 2, "draw")])

    def test_bare_name_lists_candidates_and_stdin(self) -> None:
        d = self.trace("util.py:2: AssertionError\n")
        self.assertEqual(d["results"][0]["candidates"], ["lib/util.py", "src/app/util.py"])
        with mock.patch("sys.stdin", io.StringIO(PY_TRACE)):
            got = self.repo.json("locate", "--trace")
        self.assertEqual(got["results"][0]["qualname"], "load_record")

    def test_refusals(self) -> None:
        self.assertEqual(self.trace("nothing that looks like a frame\n", expect=2)["error"]["code"], "USAGE")
        self.assertEqual(self.trace(PY_TRACE, expect=2, name=".env")["error"]["code"], "REFUSED")
        self.assertEqual(self.repo.json("locate", "--trace", "/no/such/trace.txt", expect=4)["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.repo.json("locate", "x y", "--trace", "t.txt", expect=2)["error"]["code"], "USAGE")



class TraceParsingSpeedTest(unittest.TestCase):
    def test_long_lines_parse_in_linear_time(self) -> None:
        import time

        from topomark.locate import parse_trace

        lines = ["ValueError: " + "x" * 4000, "a.a" * 1400 + ":", "x.b" * 1400, "a-" * 2000, "a." * 2000,
                 "a/" * 2000, "at " + "a" * 4000, "foo@" + "a" * 4000, "x:1" * 1500]
        start = time.perf_counter()
        for line in lines:
            parse_trace(line)
        self.assertLess(time.perf_counter() - start, 1.0)  # 0.5 to 7.7 s each with the old regex
        self.assertEqual([(f.path, f.line) for f in parse_trace("x" * 600 + " app/x.py:3\nerror:src/a.py:12: bad\n")],
                         [("src/a.py", 12)])  # past the first 500 characters is not searched


if __name__ == "__main__":
    unittest.main()
