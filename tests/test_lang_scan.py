"""The masking scanner (lang/scan.py) on literals that trip naive scanners.

Each case masks a snippet with a language's ``Syntax`` and checks the code that
survives: whitespace is collapsed, so ``"f( ) { }"`` means every literal and
comment between those tokens was blanked and nothing after it was swallowed.
Offsets must be preserved exactly (same length, newlines in place).
"""

from __future__ import annotations

import unittest

import tests.harness  # noqa: F401  (puts src/ on sys.path)
from topomark.lang.brace import mask_preprocessor, preprocessor_branches
from topomark.lang.cfamily import CFamily
from topomark.lang.csharp import CSharp
from topomark.lang.dart import Dart
from topomark.lang.go import Go
from topomark.lang.js_ts import JsTs
from topomark.lang.kotlin import Kotlin
from topomark.lang.python import SYNTAX as PY
from topomark.lang.rust import Rust
from topomark.lang.scan import mask
from topomark.lang.simple import mask_shell
from topomark.lang.swift import Swift


def code(text: str, syntax) -> str:
    m = mask(text, syntax)
    assert len(m.text) == len(text), "mask must keep offsets"
    assert [k for k, c in enumerate(m.text) if c == "\n"] == [k for k, c in enumerate(text) if c == "\n"]
    return " ".join(m.text.split())


class CSharpStrings(unittest.TestCase):
    S = CSharp.syntax

    def test_verbatim_with_doubled_quotes_and_braces(self) -> None:
        self.assertEqual(code('var p = @"C:\\{x}\\""q"""; f();', self.S), "var p = ; f();")

    def test_interpolated_with_nested_quotes_and_braces(self) -> None:
        self.assertEqual(code('var s = $"P{(a ? "x}" : "{y")}"; g();', self.S), "var s = ; g();")

    def test_interpolated_verbatim_and_escaped_braces(self) -> None:
        self.assertEqual(code('var s = $@"{{lit}} {Name} ""q"""; h();', self.S), "var s = ; h();")

    def test_char_literals(self) -> None:
        self.assertEqual(code("char a = '{', b = '\\'', c = '\"'; k();", self.S), "char a = , b = , c = ; k();")

    def test_preprocessor_keeps_first_branch(self) -> None:
        text = "#if A\nvoid F() {\n#else\nvoid G() {\n#endif\n}\n"
        pre, inactive = preprocessor_branches(text)
        self.assertEqual(" ".join(pre.split()), "void F() { }")
        self.assertEqual(inactive, [("#else", "void G() {")])
        self.assertEqual(len(pre), len(text))
        self.assertEqual(mask_preprocessor(text), pre)


class JsStrings(unittest.TestCase):
    S = JsTs.syntax

    def test_nested_template_literals(self) -> None:
        self.assertEqual(code("const s = `a ${`b ${c ? '}' : \"{\"}`} }`; f();", self.S), "const s = ; f();")

    def test_regex_literals_vs_division(self) -> None:
        self.assertEqual(code("x = s.replace(/\\/\\*[}]*\\*\\//g, ''); y = a / b / c;", self.S),
                         "x = s.replace( , ); y = a / b / c;")
        self.assertEqual(code("if (/[/{]/.test(x)) { go(); }", self.S), "if ( .test(x)) { go(); }")
        self.assertEqual(code("return <a>{x}</a>;", self.S), "return <a>{x}</a>;")


class DartStrings(unittest.TestCase):
    S = Dart.syntax

    def test_raw_strings_have_no_escapes_or_holes(self) -> None:
        self.assertEqual(code("var a = r'C:\\' ; var b = r\"${x} {\"; f();", self.S), "var a = ; var b = ; f();")

    def test_triple_quoted_with_interpolation(self) -> None:
        self.assertEqual(code("var s = '''one { ${'nested'} \n two }'''; f();", self.S), "var s = ; f();")
        self.assertEqual(code('var s = """a ${m["k"]} }"""; g();', self.S), "var s = ; g();")

    def test_interpolation_holes_with_nested_quotes(self) -> None:
        self.assertEqual(code("var s = 'n: ${c > 1 ? \"many {\" : '$c'}'; h();", self.S), "var s = ; h();")


class KotlinSwiftStrings(unittest.TestCase):
    def test_kotlin_holes_and_raw_strings(self) -> None:
        self.assertEqual(code('val s = "a ${b.let { "}" }} c"; f()', Kotlin.syntax), "val s = ; f()")
        self.assertEqual(code('val r = """x { ${y} \n } """; g()', Kotlin.syntax), "val r = ; g()")

    def test_kotlin_nested_block_comments(self) -> None:
        self.assertEqual(code("/* a /* b { */ c */ fun f() {}", Kotlin.syntax), "fun f() {}")

    def test_swift_interpolation_and_multiline(self) -> None:
        self.assertEqual(code('let s = "Hi \\(n.isEmpty ? "{anon}" : "\\(n)")"; f()', Swift.syntax), "let s = ; f()")
        self.assertEqual(code('let m = """\n  { \\(x) \n  """\ng()', Swift.syntax), "let m = g()")


class PythonStrings(unittest.TestCase):
    def test_fstring_nested_quotes_and_format_spec(self) -> None:
        self.assertEqual(code("x = f\"{a!r:>10} {'q'} {d['k']}\"; y()", PY), "x = ; y()")

    def test_raw_string_with_escaped_quote(self) -> None:
        self.assertEqual(code('p = r"(?:\\"[^\\"]*)"\nq = [1]', PY), "p = q = [1]")

    def test_triple_quoted_hides_defs(self) -> None:
        self.assertEqual(code('s = """\ndef fake():\n"""\ndef real(): pass', PY), "s = def real(): pass")


class RustCAndGo(unittest.TestCase):
    def test_rust_lifetimes_are_not_char_literals(self) -> None:
        self.assertEqual(code("fn f<'a>(x: &'a str) -> &'a str { let c = '}'; x }", Rust.syntax),
                         "fn f<'a>(x: &'a str) -> &'a str { let c = ; x }")

    def test_rust_raw_strings_and_raw_identifiers(self) -> None:
        self.assertEqual(code('let a = r#"x"{"#; let b = br"}"; let r#type = 1;', Rust.syntax),
                         "let a = ; let b = ; let r#type = 1;")

    def test_cpp_raw_strings(self) -> None:
        self.assertEqual(code('auto s = R"x(a)"{ )x"; auto t = u8R"(})"; f();', CFamily.syntax),
                         "auto s = ; auto t = ; f();")

    def test_go_backtick_raw_strings(self) -> None:
        self.assertEqual(code("var s = `C:\\ { \n }`\nfunc f() {}", Go.syntax), "var s = func f() {}")


class ShellMasking(unittest.TestCase):
    def test_comments_only_at_word_start_and_heredocs(self) -> None:
        text = 'n=${#arr[@]} # count {\ncat <<EOF\n{ not code\nEOF\nf() { echo "}"; }\n'
        m = mask_shell(text)
        self.assertEqual(len(m.text), len(text))
        self.assertEqual(" ".join(m.text.split()), "n=${#arr[@]} cat <<EOF EOF f() { echo ; }")


if __name__ == "__main__":
    unittest.main()
