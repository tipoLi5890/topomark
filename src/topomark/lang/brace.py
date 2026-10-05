"""Generic declaration extractor for brace languages (C#, Java, Kotlin, Swift,
Dart, JS/TS, Go, Rust, C/C++).

The walker runs on masked text (see ``scan``) with a scope stack. At every
``{`` it hands the header (text since the previous ``;``, ``{`` or ``}``) to the
language's ``classify_block``; at every statement terminator inside a
declaration scope it hands the statement to ``classify_statement``. Bodies of
functions are tracked for brace balance only, never classified, so local
variables and lambdas don't pollute the outline.

A language plugs in by subclassing ``BraceLanguage`` and overriding the two
classifiers plus a few attributes; see ``csharp.py`` and ``js_ts.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .base import FileInfo, Symbol, doc_summary, head_comment, idents_of, norm, surface_text
from .scan import Masked, Syntax, mask

_ANNOTATION_ONLY = re.compile(r"^(?:@[\w.:]+(?:\s*\((?:[^()]|\([^()]*\))*\))?\s*)+$")
_NONSPACE = re.compile(r"\S")
_WHERE = re.compile(r"where\b")

# Scope kinds whose direct children are declarations worth listing.
DECL_SCOPES = {"file", "namespace", "class", "struct", "interface", "enum", "record", "object", "trait",
               "protocol", "extension", "impl", "mixin", "module", "type"}
BODY_KINDS = {"function", "method", "constructor", "destructor", "operator", "property", "indexer", "event",
              "accessor", "block", "init", "getter", "setter"}


@dataclass
class Decl:
    """What a classifier returns. ``kind`` in DECL_SCOPES opens a declaration
    scope; anything else is a symbol whose body is opaque. ``kind='block'`` or
    ``'init'`` is not a symbol."""

    kind: str
    name: str = ""
    exported: bool = True
    attrs: list[str] = field(default_factory=list)
    signature: str = ""          # override the raw header as signature
    surface: str | None = None   # override what goes into the surface (None = signature)
    container: str | None = None  # override the container (Go receivers, C++ ``Foo::bar``)
    at: int = -1                 # statement lists only: offset of this item from the statement start
    span: int = 0                # statement lists only: length of this item


@dataclass
class _Scope:
    kind: str
    name: str
    open_at: int
    sym: Symbol | None
    seg_restore: int = -1
    paren_restore: int = -1


class BraceLanguage:
    name = "brace"
    syntax = Syntax()
    terminators = ";"            # statement terminators at declaration level ("\n" for ASI languages)
    member_scopes = DECL_SCOPES  # scopes whose statements are classified

    # ---- language hooks -------------------------------------------------
    def classify_block(self, header: str, raw: str, parent: _Scope, enclosing_type: str) -> Decl | None:
        return Decl("block")

    def classify_statement(self, stmt: str, raw: str, parent: _Scope,
                           enclosing_type: str) -> Decl | list[Decl] | None:
        """One declaration, or a list of them (Go ``const (...)`` groups) whose
        ``at``/``span`` locate each item inside the statement."""
        return None

    def continues(self, stmt: str, nxt: str) -> bool:
        """Newline-terminated languages: does the statement go on past this newline?

        ``nxt`` is the start of the next non-blank text. True when the next line
        opens the body (Allman ``{``), continues an expression (``.``, ``:``,
        ``=``, ``,``, ``?``, ``|``, ``&``), starts a ``where`` clause or a
        ``->`` return type, or this line ends with an operator or an opening
        bracket."""
        if nxt[:1] and nxt[:1] in "{.:=,?|&+":
            return True
        if nxt.startswith("->") or _WHERE.match(nxt):
            return True
        tail = stmt.rstrip()[-1:]
        # `?` (Swift/Kotlin optionals), `!` (force unwrap / TS non-null) and `*`
        # (Kotlin `import a.*`) end lines in real code, so they are not continuations.
        return bool(tail) and tail in "=,:.([{+-/&|\\"

    def is_annotation_only(self, stmt: str) -> bool:
        """``@Composable`` / ``@objc`` / ``@MainActor`` on a line of its own."""
        return bool(_ANNOTATION_ONLY.match(stmt))

    def enum_members(self, body: str) -> list[str]:
        out = []
        for part in body.split(","):
            m = re.match(r"\s*(?:\[[^\]]*\]\s*)*@?([A-Za-z_]\w*)", part)
            if m:
                out.append(m.group(1))
        return out

    def extra_surface(self, masked: Masked) -> list[str]:
        return []

    def header_of(self, text: str) -> list[str]:
        if "#" not in self.syntax.line_comments and "#" in text:
            text = _PP_LINE.sub("", text)  # `#include`, `#if`, `#pragma` are not header comments
        return head_comment(text)

    def decl_offset(self, masked_head: str) -> int:
        """Hook: characters before the declaration proper (C++ ``public:`` labels),
        skipped for the symbol's line, signature and doc but still classified."""
        return 0

    # ---- driver ---------------------------------------------------------
    def premask(self, text: str) -> str:
        """Hook: blank text the brace walker must not see (same length, newlines kept)."""
        return text

    def analyze(self, path: str, text: str) -> FileInfo:
        pre = self.premask(text)
        m = mask(pre, self.syntax)
        m.original = text  # signatures and docs come from the real text; offsets are identical
        symbols, surface_decls = self._walk(m)
        header = self.header_of(text)
        info = FileInfo(path=path, lang=self.name, header=header, symbols=symbols,
                        idents=idents_of(m.text), line_count=m.line_count)
        info.types = [s.name for s in symbols if not s.container and s.kind in DECL_SCOPES - {"file", "namespace"}
                      or (not s.container and s.kind in ("function", "const") and s.exported and self.functions_are_types)]
        info.types = list(dict.fromkeys(info.types))
        info.surface = surface_text(header, surface_decls + self.extra_surface(m))
        return info

    functions_are_types = False  # JS/TS/Go: top-level exported functions are the unit of fan-in

    def _walk(self, m: Masked) -> tuple[list[Symbol], list[str]]:
        text, raw = m.text, m.original
        symbols: list[Symbol] = []
        surface: list[str] = []
        stack: list[_Scope] = [_Scope("file", "", 0, None)]
        seg = 0
        paren = 0
        n = len(text)
        term = self.terminators
        interesting = re.compile(r"[{};()\[\]\n]")
        i = 0
        while i < n:
            mm = interesting.search(text, i)
            if not mm:
                break
            i = mm.start()
            c = text[i]
            top = stack[-1]
            in_decl = top.kind in self.member_scopes
            if c in "([":
                paren += 1
            elif c in ")]":
                paren = max(0, paren - 1)
            elif c == "{":
                if paren > 0 and in_decl:
                    # `{` inside (...) or [...]: destructuring, object/lambda argument, default value.
                    stack.append(_Scope("block", "", i, None, seg_restore=seg, paren_restore=paren))
                    paren = 0
                elif not in_decl:
                    stack.append(_Scope("block", "", i, None))
                    seg = i + 1
                    paren = 0
                else:
                    header = text[seg:i]
                    lead = len(header) - len(header.lstrip())
                    lead += self.decl_offset(header[lead:])
                    raw_header = raw[seg + lead:i]
                    d = self.classify_block(norm(header), raw_header, top, self._enclosing_type(stack))
                    scope = self._open(d, stack, i, seg, lead, m, raw_header, symbols, surface)
                    stack.append(scope)
                    seg = i + 1
                    paren = 0
            elif c == "}":
                if len(stack) > 1:
                    scope = stack.pop()
                    self._close(scope, i, m, text, surface)
                    if scope.seg_restore >= 0:
                        seg = scope.seg_restore
                        paren = max(0, scope.paren_restore)
                        i += 1
                        continue
                seg = i + 1
                paren = 0
            elif (c == ";" or (c == "\n" and "\n" in term)) and paren == 0:
                if in_decl and c in term:
                    stmt = text[seg:i]
                    if stmt.strip():
                        if c == "\n":
                            nxt = _NONSPACE.search(text, i)
                            nc = text[nxt.start():nxt.start() + 8] if nxt else ""
                            code = stmt.rstrip()
                            tail = raw[seg + len(code):i].strip()
                            if tail and not tail.startswith(("//", "/*", "#")):
                                code += " ;"  # the line ends with a string literal: no operator tail
                            if self.continues(code, nc) or self.is_annotation_only(stmt.strip()):
                                i += 1
                                continue
                        lead = len(stmt) - len(stmt.lstrip())
                        lead += self.decl_offset(stmt[lead:])
                        d = self.classify_statement(norm(stmt), raw[seg + lead:i], top, self._enclosing_type(stack))
                        for item in (d if isinstance(d, list) else [d] if d else []):
                            if item.kind in ("block", "init"):
                                continue
                            sym = self._symbol(item, m, seg, lead, i, raw, stack)
                            symbols.append(sym)
                            if sym.exported:
                                surface.append(item.surface if item.surface is not None else sym.signature)
                        seg = i + 1
                    elif c == ";":
                        seg = i + 1
                    # a blank line (comments only) keeps ``seg``: the doc comment above a
                    # declaration in a newline-terminated language stays attached to it
                elif c == ";":
                    seg = i + 1
            i += 1
        return symbols, surface

    def _enclosing_type(self, stack: list[_Scope]) -> str:
        for s in reversed(stack):
            if s.kind in DECL_SCOPES - {"file", "namespace", "module"}:
                return s.name
        return ""

    def _container(self, stack: list[_Scope]) -> str:
        return ".".join(s.name for s in stack if s.name and s.kind in DECL_SCOPES - {"file", "namespace"})

    def _symbol(self, d: Decl, m: Masked, seg: int, lead: int, end: int, raw: str, stack: list[_Scope]) -> Symbol:
        """``seg`` = segment start (may include a doc comment), ``seg+lead`` = declaration start."""
        container = self._container(stack)
        if d.container is not None:
            container = ".".join(x for x in (container, d.container) if x)
        decl_at = seg + lead
        if d.at >= 0:  # one item of a statement list: locate it inside the statement
            decl_at, end, seg, lead = decl_at + d.at, decl_at + d.at + max(1, d.span), decl_at + d.at, 0
        sig = d.signature or norm(_strip_leading_attrs(raw[decl_at:end]))
        code = m.text[seg:decl_at].rstrip()
        if code.strip():  # an access label or macro sits between the comment and the declaration
            seg += len(code)
        seg = _adjacent_comment_start(raw, seg, decl_at)
        comment = raw[seg:decl_at]
        if "#" in comment and "#" not in self.syntax.line_comments:
            # preprocessor lines (`#if`, `#region`) above a declaration are not its doc
            comment = _PP_LINE.sub(lambda mm: " " * len(mm.group(0)), comment)
        doc = doc_summary(comment) if comment.strip() else ""
        # range starts at the doc comment's first line when it sits right above the declaration
        start = decl_at
        if doc:
            k = len(comment.rstrip())
            first = len(comment) - len(comment.lstrip())
            start = seg + first if k else decl_at
        return Symbol(kind=d.kind, name=d.name, qualname=(container + "." if container else "") + d.name,
                      start=m.line_of(start), end=m.line_of(max(decl_at, end)), signature=sig,
                      exported=d.exported, container=container, attrs=d.attrs, doc=doc, line=m.line_of(decl_at))

    def _open(self, d: Decl | None, stack: list[_Scope], i: int, seg: int, lead: int, m: Masked, raw_header: str,
              symbols: list[Symbol], surface: list[str]) -> _Scope:
        if d is None or d.kind == "block":
            return _Scope("block", "", i, None)
        if d.kind == "init":
            return _Scope("block", "", i, None, seg_restore=seg)
        if d.kind == "transparent":  # extern "C" { }, Rust extern blocks: members belong to the parent
            return _Scope("namespace", "", i, None)
        sym = self._symbol(d, m, seg, lead, i, m.original, stack)
        symbols.append(sym)
        if sym.exported:
            surface.append(d.surface if d.surface is not None else sym.signature)
        kind = d.kind if d.kind in DECL_SCOPES else "body"
        return _Scope(kind, d.name if kind != "body" else "", i, sym)

    def _close(self, scope: _Scope, i: int, m: Masked, text: str, surface: list[str]) -> None:
        if scope.sym is None:
            return
        scope.sym.end = m.line_of(i)
        if scope.kind == "enum":
            members = self.enum_members(text[scope.open_at + 1:i])
            if members and scope.sym.exported:
                surface.append(f"enum {scope.sym.name} = " + ",".join(members))


_PP_LINE = re.compile(r"^[ \t]*#[^\n]*", re.M)
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")


def _adjacent_comment_start(raw: str, seg: int, decl_at: int) -> int:
    """Start of the comment block that touches the declaration: text separated
    from it by a blank line (a file header, a section banner) is not its doc."""
    if seg > 0 and raw[seg - 1] != "\n":  # `}  // namespace geo`: the rest of the previous line
        nl = raw.find("\n", seg, decl_at)
        if nl >= 0:
            seg = nl + 1
    comment = raw[seg:decl_at]
    if "\n" not in comment.strip():
        return seg
    cut = 0
    for bm in _BLANK_LINE.finditer(comment):
        before = comment[:bm.start()]
        if before.count("/*") <= before.count("*/"):  # not inside a block comment
            cut = bm.end()
    return seg + cut


def mask_preprocessor(text: str) -> str:
    """C-family ``#if``: keep the first branch of every group, blank ``#elif``/``#else``
    branches and all directive lines, so alternative branches can't unbalance braces."""
    return preprocessor_branches(text)[0]


def preprocessor_branches(text: str) -> tuple[str, list[tuple[str, str]]]:
    """``mask_preprocessor`` plus the blanked code lines of inactive branches as
    ``(directive, line)`` pairs, e.g. ``("#else", "public static float X = 1f;")``,
    so adapters can keep public declarations of other branches in the surface."""
    if "#" not in text:
        return text, []
    out = []
    inactive: list[tuple[str, str]] = []
    stack: list[bool] = []  # per #if group: is the current branch the kept one?
    labels: list[str] = []
    for ln in text.split("\n"):
        st = ln.lstrip()
        if st.startswith("#"):
            word = st[1:].lstrip().split(None, 1)[0] if len(st) > 1 and st[1:].strip() else ""
            if word in ("if", "ifdef", "ifndef"):
                stack.append(True)
                labels.append("#" + word)
            elif word in ("elif", "else", "elifdef", "elifndef"):
                if stack:
                    stack[-1] = False
                    labels[-1] = norm(st.split("//")[0])
            elif word == "endif":
                if stack:
                    stack.pop()
                    labels.pop()
            out.append(" " * len(ln))
            continue
        if all(stack):
            out.append(ln)
        else:
            out.append(" " * len(ln))
            if st:
                inactive.append((labels[-1] if labels else "#if", ln))
    return "\n".join(out), inactive


def _strip_leading_attrs(raw: str) -> str:
    s = raw.strip()
    while s.startswith("["):
        depth = 0
        for k, ch in enumerate(s):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    s = s[k + 1:].lstrip()
                    break
        else:
            break
    return s


def leading_attrs(raw: str) -> list[str]:
    out = []
    s = raw.strip()
    while s.startswith("["):
        depth = 0
        for k, ch in enumerate(s):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    out.append(norm(s[1:k]))
                    s = s[k + 1:].lstrip()
                    break
        else:
            break
    return out
