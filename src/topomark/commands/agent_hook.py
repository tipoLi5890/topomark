"""``topomark agent-hook session-start|pre-read|post-edit``: the Claude Code plugin hooks.

``hooks/hooks.json`` at the plugin root runs these. Each reads the hook's JSON on stdin and answers
in the hook protocol, not the ``--json`` envelope: nothing at all, or one object
``{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}`` on stdout, exit 0.
A hook must never get in the way, so every failure (a broken payload or one over ``MAX_PAYLOAD``,
a directory outside git, an invalid config, a bug) ends in silence and exit 0; an unknown action
is silent too, because an argparse usage error would exit 2, and exit 2 from a PreToolUse hook
blocks the tool call.
``--json`` wraps the same object in the usual envelope, for debugging; the hooks never pass it.

* ``session-start`` (SessionStart, on startup, clear and compact): the L0 file, each area's name
  and file, one line of navigation commands and whether review stamps exist; at most 40 lines and
  4 KB, no L0 prose, no index. Without a code map, one line suggesting ``map``.
* ``pre-read`` (PreToolUse on Read): silent for a ranged read (``offset``/``limit``), a file
  without a language adapter, outside the repo, secret-looking or excluded. A file over 400 lines
  gets a pointer to ``outline`` and ``symbol --skeleton``; the first file read in an area gets a
  pointer to its area file. Each hint is given once per session: one marker file per hint in the
  user cache directory, created with ``O_EXCL`` so parallel reads cannot both win. ``clear`` and
  ``compact`` forget the session's hints, since the context that held them is gone.
* ``post-edit`` (PostToolUse on Edit, Write, MultiEdit): ``syntax`` on the edited file; speaks only
  when the file no longer parses and its HEAD version did. Python findings are dropped when the
  project's ``requires-python`` minimum is newer than the interpreter running the hook: the code
  may be valid for the Python it targets.
"""

from __future__ import annotations

from . import Result
from ._common import add

EVENTS = {"session-start": "SessionStart", "pre-read": "PreToolUse", "post-edit": "PostToolUse"}
MAX_LINES = 40          # session-start: lines of additionalContext
MAX_BYTES = 4096        # session-start: UTF-8 bytes of additionalContext
LARGE_LINES = 400       # pre-read: a file this long gets the outline hint
KEEP_SECONDS = 2 * 86400  # session marker folders older than this are swept at session start
MAX_PAYLOAD = 1 << 20     # bytes of hook JSON read from stdin; a bigger payload (a huge Write) gets silence
STATE_DIR = "agent-hook"


def register(sub, common) -> None:
    p = add(sub, common, "agent-hook",
            "Claude Code plugin hooks (hook JSON on stdin): code-map pointer, read hints, syntax after an edit",
            "Run by the plugin's hooks/hooks.json, not by hand. Reads the hook payload on stdin and\n"
            "prints nothing or one hook-protocol object ({\"hookSpecificOutput\": {\"hookEventName\",\n"
            "\"additionalContext\"}}); always exits 0, whatever goes wrong.\n"
            "  session-start  the code map's areas and files, the navigation commands (<= 40 lines)\n"
            "  pre-read       before a Read: outline hint for files over 400 lines, the area file\n"
            "                 on the first read in an area; each hint once per session\n"
            "  post-edit      after Edit/Write/MultiEdit: report the file if it no longer parses",
            "examples:\n"
            "  echo '{\"cwd\": \".\"}' | topomark agent-hook session-start\n"
            "  topomark agent-hook pre-read < payload.json")
    p.add_argument("action", nargs="?", default="", metavar="{session-start,pre-read,post-edit}",
                   help="which hook to answer; anything else prints nothing")
    p.set_defaults(handler=run)


def run(args, ctx) -> Result:
    args.quiet = True  # a hook says what it has to say in its answer, never on stderr (config warnings)
    try:
        handler = _HANDLERS.get(args.action)
        if handler is None:
            return Result()
        payload = _payload()
        text = handler(args, ctx, payload)
        if not text:
            return Result()
        import json

        out = {"hookSpecificOutput": {"hookEventName": EVENTS[args.action], "additionalContext": text}}
        return Result(out, json.dumps(out, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - a hook never fails: silence, exit 0
        if getattr(args, "debug", False):
            raise
        return Result()


# ---------------------------------------------------------------- payload and paths
def _payload() -> dict:
    import json
    import sys

    stream = sys.stdin
    if stream is None or stream.isatty():
        return {}
    buf = getattr(stream, "buffer", None)
    raw = buf.read(MAX_PAYLOAD + 1) if buf is not None else stream.read(MAX_PAYLOAD + 1)
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("hook payload over MAX_PAYLOAD")  # run() turns it into silence
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    if not text.strip():
        return {}  # no payload (a run by hand): the current directory is the repo
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("hook payload is not a JSON object")
    return data


def _root(args, ctx, payload: dict):
    """The repo root, found from the payload's ``cwd`` unless ``-C`` was given; raises outside git."""
    cwd = payload.get("cwd")
    if getattr(args, "repo", None) is None and isinstance(cwd, str) and cwd:
        args.repo = cwd
    return ctx.root


def _file_arg(payload: dict) -> str:
    ti = payload.get("tool_input")
    fp = ti.get("file_path") if isinstance(ti, dict) else None
    return fp if isinstance(fp, str) else ""


def _repo_path(ctx, payload: dict, raw: str) -> str | None:
    """``raw`` as a repo-relative POSIX path, or None when it is outside the repo."""
    import os
    from pathlib import Path

    p = Path(raw)
    if not p.is_absolute():
        cwd = payload.get("cwd")
        p = Path(cwd if isinstance(cwd, str) and cwd else os.getcwd()) / p
    root = ctx.root
    for cand, base in ((Path(os.path.abspath(p)), root), (p.resolve(), root.resolve())):
        try:
            rel = cand.relative_to(base).as_posix()
        except ValueError:
            continue
        return rel if rel not in ("", ".") else None
    return None


def _excludes(ctx) -> tuple[str, ...]:
    from ..errors import TopomarkError
    from ..repo import DEFAULT_EXCLUDES

    try:
        return tuple(ctx.config.exclude)
    except TopomarkError:  # a broken topomark.toml must not silence the other hints
        return DEFAULT_EXCLUDES


# ---------------------------------------------------------------- once per session
def _session_dir(root, payload: dict):
    import hashlib

    from ..index import cache_dir

    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    return cache_dir(root) / STATE_DIR / hashlib.sha256(sid.encode("utf-8")).hexdigest()[:16]


def _first_time(state, key: str) -> bool:
    """True exactly once per session and key; False when the marker cannot be written either,
    so an unwritable cache means no hints rather than the same hint on every read."""
    import hashlib
    import os

    if state is None:
        return False
    try:
        state.mkdir(parents=True, exist_ok=True)
        fd = os.open(state / hashlib.sha256(key.encode("utf-8")).hexdigest()[:24],
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:  # FileExistsError included: said before
        return False
    os.close(fd)
    return True


def _sweep(root, payload: dict) -> None:
    """Drop marker folders of old sessions, and this session's after a clear or compact."""
    import shutil
    import time

    from ..index import cache_dir

    base = cache_dir(root) / STATE_DIR
    if not base.is_dir():
        return
    current = _session_dir(root, payload) if payload.get("source") in ("clear", "compact") else None
    cutoff = time.time() - KEEP_SECONDS
    for d in base.iterdir():
        try:
            if d == current or d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


# ---------------------------------------------------------------- session-start
def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _session_start(args, ctx, payload: dict) -> str:
    from ..docs import load_areas
    from ..errors import TopomarkError

    root = _root(args, ctx, payload)
    try:
        _sweep(root, payload)
    except OSError:
        pass
    try:
        docs = ctx.config.docs_dir
    except TopomarkError as e:
        return f"topomark: {_clip(e.message, 200)}; `topomark doctor` says how to fix it."
    areas = load_areas(ctx)
    nav = ("Read code by symbol, not whole files: `topomark outline <file>`, `topomark symbol <file>#<Name>` "
           "(`--skeleton` for a class), `topomark search <keywords>`, `topomark locate \"<error text>\"` "
           "(`--trace` for a stack trace), `topomark brief <file|Name>` before an edit, `topomark syntax` after.")
    if not areas:
        return ("topomark: this repo has no code map; `topomark map --tokens 2000` gives a ranked overview "
                "of its central files and signatures.")
    l0 = f"{docs}/README.md"
    head = (f"topomark code map: {l0} is the index (read it first); one file per area:"
            if (root / l0).is_file() else "topomark code map, one file per area:")
    if (root / docs / "stamps.json").is_file():
        stamps = ("Review stamps are on (stamps.json): `topomark check` before committing; after an interface "
                  "change, `topomark diff <unit>`, update the row, then `topomark stamp <unit>`.")
    else:
        stamps = "No review stamps yet (no stamps.json): `topomark check --no-stamps` checks coverage only."
    rows = [f"- {a.name}: {a.file}" + (f" ({_clip(a.title, 70)})" if a.title.lower() not in ("", a.name.lower())
                                       else "") for a in areas]
    keep = min(len(rows), MAX_LINES - 4)
    while True:
        shown = rows[:keep]
        if keep < len(rows):
            shown.append(f"- … {len(rows) - keep} more areas: see {l0}")
        text = "\n".join([head, *shown, nav, stamps])
        if len(text.encode("utf-8")) <= MAX_BYTES or keep == 0:
            return text
        keep -= 1


# ---------------------------------------------------------------- pre-read
def _pre_read(args, ctx, payload: dict) -> str:
    from ..errors import TopomarkError
    from ..lang import registry
    from ..repo import matches_any, safe_path

    ti = payload.get("tool_input")
    raw = _file_arg(payload)
    if not raw or not isinstance(ti, dict) or ti.get("offset") is not None or ti.get("limit") is not None:
        return ""
    lang = getattr(registry.adapter_for(raw), "name", "text")
    if lang == "text":
        return ""
    _root(args, ctx, payload)
    rel = _repo_path(ctx, payload, raw)
    if rel is None or matches_any(rel, _excludes(ctx)):
        return ""
    try:
        full = safe_path(ctx.root, rel)  # secret-looking, or a link out of the repo or onto a secret
    except TopomarkError:
        return ""
    if not full.is_file():
        return ""
    state = _session_dir(ctx.root, payload)
    hints = []
    if full.stat().st_size > LARGE_LINES:
        with open(full, "rb") as fh:
            lines = sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
        if lines > LARGE_LINES and _first_time(state, f"large:{rel}"):
            if lang in ("markdown", "data"):
                hints.append(f"topomark: {rel} has {lines:,} lines. `topomark outline {rel}` lists its "
                             f"{'headings' if lang == 'markdown' else 'keys'} with line ranges; then Read "
                             "just the range you need (offset and limit).")
            else:
                hints.append(f"topomark: {rel} has {lines:,} lines. Outline it first (`topomark outline {rel}`), "
                             f"then read only what you need: `topomark symbol {rel}#<Name>` (`--skeleton` "
                             "for a class without its bodies), or Read a line range.")
    hint = _area_hint(ctx, rel, state)
    if hint:
        hints.append(hint)
    return "\n".join(hints)


def _area_hint(ctx, rel: str, state) -> str:
    from ..docs import load_areas, owner_of
    from ..errors import TopomarkError

    try:
        areas = load_areas(ctx)
    except TopomarkError:
        return ""
    for a in areas:
        if a.file == rel:  # reading the area file itself: nothing left to point at
            _first_time(state, f"area:{a.name}")
            return ""
    area, _ = owner_of(rel, areas)
    if area is None or not _first_time(state, f"area:{area.name}"):
        return ""
    return (f"topomark: {rel} is in area `{area.name}`; {area.file} has a row per file, the data flow and the "
            "pitfalls (worth reading before editing here).")


# ---------------------------------------------------------------- post-edit
def _post_edit(args, ctx, payload: dict) -> str:
    from .. import syntax as X
    from ..lang import registry
    from ..repo import is_secret

    raw = _file_arg(payload)
    if not raw:
        return ""
    low = raw.lower()
    if not (low.endswith(X.PY_EXT + X.JSON_EXT + X.JSONC_EXT + X.TOML_EXT)
            or getattr(registry.adapter_for(raw), "name", "") in X.BRACE_LANGS):
        return ""
    _root(args, ctx, payload)
    rel = _repo_path(ctx, payload, raw)
    if rel is None or is_secret(rel) or not (ctx.root / rel).is_file():
        return ""
    found = [f for f in X.check_file(ctx, rel).findings if not f.preexisting]
    if any(f.lang == "python" for f in found) and X.newer_python(ctx, rel):
        found = [f for f in found if f.lang != "python"]  # maybe valid for the newer Python the project requires
    if not found:
        return ""
    return "\n".join([*(f"topomark syntax: {f.text()}" for f in found[:5]),
                      f"{rel} no longer parses after this edit: fix it before going on."])


_HANDLERS = {"session-start": _session_start, "pre-read": _pre_read, "post-edit": _post_edit}
