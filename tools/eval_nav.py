#!/usr/bin/env python3
"""Minimal navigation eval: does a command put the right symbol on top, and at what cost?

    python3 tools/eval_nav.py                     # tools/eval/tasks.toml against this checkout
    python3 tools/eval_nav.py --kind find --json
    python3 tools/eval_nav.py --compare HEAD~3    # the same tasks with topomark from another rev

No LLM is involved: each task is the command an agent would type, run in-process
(like ``tests/harness.run_cli``) against a warm cache, and scored against a gold
answer. Per task it reports the gold's rank, hit@1, hit@5, the output tokens of
the text an agent would read (``topomark.contract.estimate_tokens``: ASCII 1 per
4 characters, anything else 1 each, as ``map`` counts) and the wall time.

Task file (TOML), one ``[[task]]`` per question::

    [[task]]
    id = "find-stamp"
    kind = "find"            # find | search | locate | brief | tests
    query = "stamp"          # what the agent types; {line:path#Qual} = a line inside that symbol
    args = ["--limit", "20"] # optional extra arguments
    gold = "src/topomark/stamps.py#Stamps"   # or a list (any one counts); "path" alone = that file
    repo = "self"            # "self" (--repo, default this checkout) or "synth" (tools/synth_repo.py)
    trace = "..."            # locate only: written to a file and passed as --trace FILE
    expect = "miss"          # optional, default "hit": a control the command must NOT answer with gold

Kinds map to commands: find → ``find``, search → ``search``, locate → ``locate``,
brief → ``brief``, tests → ``tests-for``. A task whose command (or one of whose
``--flags``) the parser does not have is reported as ``skipped: command not
available`` (``flag not available``), so tasks can be written before the command.

Candidates are read from the ``--json`` output in document order: an object
with ``path`` (and ``qualname`` or ``symbol``) is the candidate ``path#qualname``;
a string that is a repo file (or ``file#Qual``) inside a list is a candidate
too. ``find`` and ``tests-for`` are read from their answer key only (``results``,
``tests``); other commands from the whole payload, and the task's own input file
is never an answer. A symbol gold ranks among distinct ``path#qualname``
candidates, a file gold among distinct paths. New commands should list their
answers in that shape, best first.

Each task ends ``ok``, ``error`` or ``skipped``. ``ok``: the command answered and
is scored; a ``NOT_FOUND`` or ``UNSUPPORTED`` error is an answer too (nothing
found: a miss). ``error``: it did not answer: any other error code (``CONFIG``,
``USAGE``, ``INTERNAL``...), no JSON object on stdout, or a crash while running
the task. Its rank shows ``err`` with the reason on the row, and errors are
counted apart, never as misses. hit@1, hit@5 and MRR are over the ``ok`` tasks
that expect a hit. ``expect = "miss"`` makes a task a control (``tests-for
--depth 1`` on a file two imports from its test): it holds when the gold is not
among the candidates at all, it is reported as ``controls held n/m``, and it is
kept out of hit@k and MRR.

Every gold is checked before anything runs (the file exists, the symbol is
declared there); a stale gold exits 2 so the tasks can't silently rot.

``--compare REV`` exports ``src/`` at REV with ``git archive``, runs this script
on it in a subprocess (``--src``; the subprocess owns its own temporary cache),
and prints both side by side; the tasks, the target repo and the synthetic repo
stay the current ones. So does the target's ``topomark.toml``, which REV may not
read: topomark rejects keys it does not know, and a REV before the key existed
(``suite`` in ``[[tests.runner]]``, before 21e15fb) would fail every task with
``CONFIG``. The REV side therefore runs with ``--compat-config``: when its
topomark rejects the file, it reads a temporary copy (``--config``) without each
key its ``CONFIG`` errors name, and the report lists the keys dropped. That side
then runs without what they configure (the runner's suite command), as REV did.
Limits: a config REV still can't read shows as errors; REV needs ``--config`` and
``contract.estimate_tokens`` (both in 0.1.0); ``{line:}`` placeholders are filled
in with REV's own parser.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KIND_COMMAND = {"find": "find", "search": "search", "locate": "locate", "brief": "brief", "tests": "tests-for"}
ANSWER_KEY = {"find": "results", "search": "results", "locate": "results", "brief": "related", "tests": "tests"}  # kinds whose JSON shape is known
ANSWERS = {"NOT_FOUND", "UNSUPPORTED"}  # error codes that are the command's answer (nothing found): a miss
EXPECT = ("hit", "miss")
SYNTH_FILES = 150
CONFIG_FILE = "topomark.toml"
_LINE = re.compile(r"\{line:([^}#]+)#([^}]+)\}")


# ---------------------------------------------------------------- topomark access
def _load_topomark(src: Path) -> None:
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _synth_repo() -> Any:
    """``tools/synth_repo.py`` (``tools/`` goes on ``sys.path`` once; it is already there in a script run)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import synth_repo

    return synth_repo


def _cli(argv: list[str]) -> tuple[int, str, float]:
    from topomark.cli import main

    out, err = io.StringIO(), io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(list(argv))
        except SystemExit as e:
            rc = int(e.code or 0)
    return rc, out.getvalue(), time.perf_counter() - t0


def _subcommands() -> dict[str, set[str]]:
    """CLI name → its option strings, from the live parser."""
    from topomark.cli import build_parser

    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {name: {o for a in sp._actions for o in a.option_strings} for name, sp in action.choices.items()}
    return {}


def _tokens(text: str) -> int:
    from topomark.contract import estimate_tokens

    return estimate_tokens(text)


def _symbols(repo: Path, path: str) -> list[Any]:
    from topomark.lang.registry import analyze

    with open(repo / path, encoding="utf-8", errors="replace", newline="") as fh:
        return analyze(path, fh.read().replace("\r\n", "\n")).symbols


def _payload(out: str) -> dict | None:
    """The one JSON object a ``--json`` run printed, or None."""
    try:
        data = json.loads(out) if out.strip() else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- tasks
def load_tasks(path: Path) -> list[dict]:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    tasks = raw.get("task", [])
    seen = set()
    for t in tasks:
        for key in ("id", "kind", "gold"):
            if key not in t:
                raise SystemExit(f"eval: task {t.get('id', '?')} has no {key!r}")
        if t["kind"] not in KIND_COMMAND:
            raise SystemExit(f"eval: task {t['id']}: unknown kind {t['kind']!r}")
        if t.setdefault("expect", "hit") not in EXPECT:
            raise SystemExit(f"eval: task {t['id']}: expect must be \"hit\" or \"miss\", not {t['expect']!r}")
        if t["id"] in seen:
            raise SystemExit(f"eval: duplicate task id {t['id']!r}")
        seen.add(t["id"])
        t.setdefault("args", [])
        t.setdefault("repo", "self")
        t["gold"] = [t["gold"]] if isinstance(t["gold"], str) else list(t["gold"])
    return tasks


def stale_golds(task: dict, repo: Path) -> list[str]:
    bad = []
    specs = list(task["gold"]) + [f"{p}#{q}" for p, q in _LINE.findall(task.get("query", "") + task.get("trace", ""))]
    for g in specs:
        path, _, qual = g.partition("#")
        if not (repo / path).is_file():
            bad.append(f"{task['id']}: {g}: no such file")
        elif qual and not any(s.qualname == qual for s in _symbols(repo, path)):
            bad.append(f"{task['id']}: {g}: no symbol {qual!r} in {path}")
    return bad


def expand(text: str, repo: Path) -> str:
    """``{line:path#Qual}`` → the first line of that symbol's body (its declaration line + 1, within range)."""
    def line(m: re.Match[str]) -> str:
        for s in _symbols(repo, m.group(1)):
            if s.qualname == m.group(2):
                decl = s.line or s.start
                return str(min(decl + 1, s.end))
        return "0"

    return _LINE.sub(line, text)


# ---------------------------------------------------------------- the target's config, as REV can read it
_UNKNOWN_SECTION = re.compile(r"unknown section \[([^\]]+)\]")
_UNKNOWN_RUNNER_KEYS = re.compile(r"tests\.runner\[(\d+)\] unknown keys (\[.*\])")
_UNKNOWN_KEY = re.compile(r"unknown key ([\w-]+)\.([\w-]+)")


def drop_rejected(raw: dict, message: str) -> list[str]:
    """Remove from ``raw`` (a parsed topomark.toml) what a CONFIG error ``message`` rejects; returns
    the names removed, [] when the message names nothing in ``raw``. These three shapes are how
    every topomark since 0.1.0 rejects a section or key it does not know."""
    m = _UNKNOWN_SECTION.search(message)
    if m and m.group(1) in raw:
        del raw[m.group(1)]
        return [f"[{m.group(1)}]"]
    m = _UNKNOWN_RUNNER_KEYS.search(message)
    if m:
        tests = raw.get("tests")
        runners = tests.get("runner") if isinstance(tests, dict) else None
        i = int(m.group(1))
        try:
            names = ast.literal_eval(m.group(2))
        except (ValueError, SyntaxError):
            names = []
        if isinstance(runners, list) and i < len(runners) and isinstance(runners[i], dict):
            gone = [k for k in names if isinstance(k, str) and k in runners[i]]
            for k in gone:
                del runners[i][k]
            return [f"tests.runner[{i}].{k}" for k in gone]
        return []
    m = _UNKNOWN_KEY.search(message)
    if m and isinstance(raw.get(m.group(1)), dict) and m.group(2) in raw[m.group(1)]:
        del raw[m.group(1)][m.group(2)]
        return [f"{m.group(1)}.{m.group(2)}"]
    return []


def toml_text(data: dict) -> str:
    """``data`` (a parsed topomark.toml) written as TOML again: tables, arrays of tables, and values
    ``json.dumps`` spells the TOML way (strings, integers, booleans, arrays of them). Raises
    ValueError when the text does not read back as ``data`` (dates, inline tables in arrays)."""
    out: list[str] = []

    def key(k: str) -> str:
        return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)

    def tables(v: Any) -> bool:
        return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)

    def table(path: list[str], d: dict) -> None:
        for k, v in d.items():
            if not isinstance(v, dict) and not tables(v):
                out.append(f"{key(k)} = {json.dumps(v, ensure_ascii=False)}")
        for k, v in d.items():
            sub = [*path, key(k)]
            if isinstance(v, dict):
                out.append(f"\n[{'.'.join(sub)}]")
                table(sub, v)
            elif tables(v):
                for item in v:
                    out.append(f"\n[[{'.'.join(sub)}]]")
                    table(sub, item)

    try:
        table([], data)
        text = "\n".join(out).lstrip("\n") + "\n"
        same = tomllib.loads(text) == data
    except (TypeError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"cannot write the config back as TOML: {e}") from e
    if not same:
        raise ValueError("cannot write the config back as TOML: it does not read back the same")
    return text


def config_flags(repo: Path, work: Path) -> tuple[list[str], list[str]]:
    """``(global flags, names dropped)`` under which the topomark being evaluated reads ``repo``'s
    topomark.toml: ``([], [])`` when it reads the file as it is (or there is none). Otherwise
    ``--config`` and a copy in ``work`` without each key its CONFIG errors name, one error at a
    time. An error that names nothing it can drop stops the loop; the tasks then show that error."""
    path = repo / CONFIG_FILE
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return [], []  # no config, or one no version reads: the tasks say so
    flags: list[str] = []
    dropped: list[str] = []
    for _ in range(64):
        error = (_payload(_cli(["-C", str(repo), *flags, "map", "--tokens", "1", "--json"])[1]) or {}).get("error")
        if not isinstance(error, dict) or error.get("code") != "CONFIG":
            break
        gone = drop_rejected(raw, str(error.get("message", "")))
        if not gone:
            break
        try:
            text = toml_text(raw)
        except ValueError:
            break
        work.mkdir(parents=True, exist_ok=True)
        copy = work / CONFIG_FILE
        with open(copy, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        flags, dropped = ["--config", str(copy)], dropped + gone
    return flags, dropped


# ---------------------------------------------------------------- scoring
def candidates(payload: Any, files: set[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def from_string(s: str) -> None:
        path, _, qual = s.partition("#")
        if path in files:
            out.append((path, qual))

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            p = x.get("path")
            if isinstance(p, str):
                q = x.get("qualname") if isinstance(x.get("qualname"), str) else x.get("symbol")
                out.append((p, q if isinstance(q, str) else ""))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                if isinstance(v, str):
                    from_string(v)
                else:
                    walk(v)

    walk(payload)
    return out


def gold_rank(cands: list[tuple[str, str]], gold: list[str]) -> int | None:
    best = None
    for g in gold:
        path, _, qual = g.partition("#")
        seen: list[Any] = []
        for p, q in cands:
            key = (p, q) if qual else p
            if qual and not q:
                continue
            if key not in seen:
                seen.append(key)
            if p == path and (not qual or q == qual):
                rank = seen.index(key) + 1
                best = rank if best is None else min(best, rank)
                break
    return best


# ---------------------------------------------------------------- running
def git_files(repo: Path) -> set[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return {f for f in out.split("\0") if f}


def _row(task: dict) -> dict[str, Any]:
    return {"id": task["id"], "kind": task["kind"], "repo": task["repo"], "gold": task["gold"],
            "expect": task["expect"], "rank": None, "hit1": False, "hit5": False, "tokens": 0, "ms": 0, "exit": None}


def run_task(task: dict, repo: Path, files: set[str], subs: dict[str, set[str]], workdir: Path,
             flags: list[str] | None = None) -> dict:
    cmd = KIND_COMMAND[task["kind"]]
    row = _row(task)
    if cmd not in subs:
        return {**row, "status": "skipped", "reason": "command not available"}
    missing = [a for a in task["args"] if a.startswith("--") and a.split("=", 1)[0] not in subs[cmd]]
    if missing:
        return {**row, "status": "skipped", "reason": f"flag not available: {', '.join(missing)}"}
    argv = [cmd]
    if task.get("query"):
        argv.append(expand(task["query"], repo))
    if task.get("trace"):
        trace = workdir / f"{task['id']}.trace.txt"
        with open(trace, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(expand(task["trace"], repo))
        argv += ["--trace", str(trace)]
    argv += [str(a) for a in task["args"]]
    base = ["-C", str(repo), *(flags or [])]
    rc, text, secs = _cli([*base, *argv])
    _, out, _ = _cli([*base, *argv, "--json"])
    row.update({"exit": rc, "tokens": _tokens(text), "ms": round(secs * 1000)})
    payload = _payload(out)
    if payload is None:
        return {**row, "status": "error", "reason": f"no JSON object on stdout (exit {rc})"}
    error = payload.get("error")
    cands: list[tuple[str, str]] = []
    if isinstance(error, dict):
        row["reason"] = f"{error.get('code', '?')}: {error.get('message', '')}"
        if error.get("code") not in ANSWERS:
            return {**row, "status": "error"}
    else:
        answer = payload.get(ANSWER_KEY[task["kind"]], []) if task["kind"] in ANSWER_KEY else payload
        cands = candidates(answer, files)
        if len(argv) > 1 and argv[1] in files:  # the input file itself is not an answer
            cands = [c for c in cands if c[0] != argv[1]]
    rank = gold_rank(cands, task["gold"])
    row.update({"status": "ok", "rank": rank, "hit1": rank == 1, "hit5": rank is not None and rank <= 5,
                "top": [f"{p}#{q}" if q else p for p, q in _dedupe(cands)[:3]]})
    if task["expect"] == "miss":
        row["held"] = rank is None
    return row


def _run_safely(task: dict, *args: Any) -> dict:
    try:
        return run_task(task, *args)
    except Exception as e:  # noqa: BLE001 - a task that crashes is an error row, not the end of the eval
        return {**_row(task), "status": "error", "reason": f"crashed: {type(e).__name__}: {e}"}


def _dedupe(cands: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def summarize(rows: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        ran = [r for r in rs if r["status"] == "ok"]
        scored = [r for r in ran if r["expect"] == "hit"]
        controls = [r for r in ran if r["expect"] == "miss"]
        n, k = len(scored), len(ran)
        return {"tasks": len(rs), "ran": k, "scored": n,
                "errors": sum(r["status"] == "error" for r in rs),
                "skipped": sum(r["status"] == "skipped" for r in rs),
                "hit1": sum(r["hit1"] for r in scored), "hit5": sum(r["hit5"] for r in scored),
                "missed": sum(r["rank"] is None for r in scored),
                "hit1_rate": round(sum(r["hit1"] for r in scored) / n, 3) if n else None,
                "hit5_rate": round(sum(r["hit5"] for r in scored) / n, 3) if n else None,
                "mrr": round(sum(1 / r["rank"] for r in scored if r["rank"]) / n, 3) if n else None,
                "controls": len(controls), "controls_held": sum(bool(r.get("held")) for r in controls),
                "tokens_total": sum(r["tokens"] for r in ran),
                "tokens_mean": round(sum(r["tokens"] for r in ran) / k) if k else None,
                "ms_mean": round(sum(r["ms"] for r in ran) / k) if k else None}

    kinds = sorted({r["kind"] for r in rows})
    return {"all": block(rows), "by_kind": {k: block([r for r in rows if r["kind"] == k]) for k in kinds}}


def evaluate(tasks: list[dict], repo: Path, src: Path, validate: bool = True,
             synth_files: int = SYNTH_FILES, compat_config: bool = False) -> dict:
    _load_topomark(src)
    with tempfile.TemporaryDirectory(prefix="topomark-eval-") as tmp:
        work = Path(tmp)
        targets: dict[str, Path] = {"self": repo}
        if any(t["repo"] == "synth" for t in tasks):
            targets["synth"] = work / "synth"
            _synth_repo().generate(targets["synth"], synth_files)
        for t in tasks:
            if t["repo"] not in targets:
                raise SystemExit(f"eval: task {t['id']}: unknown repo {t['repo']!r} (self or synth)")
        if validate:
            bad = [b for t in tasks for b in stale_golds(t, targets[t["repo"]])]
            if bad:
                raise StaleGold(bad)
        subs = _subcommands()
        files = {name: git_files(path) for name, path in targets.items()}
        flags: dict[str, list[str]] = {}
        dropped: dict[str, list[str]] = {}
        for name, path in targets.items():
            flags[name], gone = config_flags(path, work / "config" / name) if compat_config else ([], [])
            if gone:
                dropped[name] = gone
            _cli(["-C", str(path), *flags[name], "map", "--tokens", "1"])  # warm the cache; timings below are warm
        rows = [_run_safely(t, targets[t["repo"]], files[t["repo"]], subs, work, flags[t["repo"]]) for t in tasks]
    return {"src": str(src), "repo": str(repo), "config_dropped": dropped, "tasks": rows, "summary": summarize(rows)}


class StaleGold(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def compare_run(rev: str, args: argparse.Namespace, repo: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="topomark-eval-rev-") as tmp:
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", rev, "src"], capture_output=True)
        if archive.returncode != 0:
            raise SystemExit(f"eval: --compare {rev}: git archive failed:\n"
                             f"{archive.stderr.decode('utf-8', errors='replace')}")
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp, filter="data")
            else:  # Python 3.11 before 3.11.4
                tf.extractall(tmp)
        # No TOPOMARK_CACHE here: the child's main() owns its cache (a fresh temporary one, as in any run
        # without --cache), so REV's index never meets the current side's.
        env = dict(os.environ, PYTHONUTF8="1")
        argv = [sys.executable, str(Path(__file__).resolve()), "--src", str(Path(tmp) / "src"), "--tasks",
                str(args.tasks), "--repo", str(repo), "--json", "--no-validate", "--compat-config",
                "--synth-files", str(args.synth_files)]
        for k in args.kind or []:
            argv += ["--kind", k]
        for i in args.only or []:
            argv += ["--only", i]
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env)
        if p.returncode != 0:
            raise SystemExit(f"eval: --compare {rev} failed:\n{p.stderr}")
        result = json.loads(p.stdout)
        result["rev"] = rev
        return result


# ---------------------------------------------------------------- output
def _rank(r: dict) -> str:
    if r["status"] == "skipped":
        return "skip"
    if r["status"] == "error":
        return "err"
    return str(r["rank"]) if r["rank"] else "-"


def _clip(s: str, n: int = 120) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


def _note(r: dict) -> str:
    """Why a row is not a plain scored answer: its error or skip reason, the outcome of a control,
    the command's own "nothing found"; "" for a plain row."""
    if r["status"] != "ok":
        return f"{r['status']}: {_clip(r.get('reason', ''))}"
    notes = []
    if r.get("expect") == "miss":
        notes.append("expected miss: held" if r.get("held") else "expected miss: NOT held, the gold was returned")
    if r.get("reason"):
        notes.append(_clip(r["reason"]))
    return "; ".join(notes)


def _summary_line(name: str, b: dict) -> str:
    n = b["scored"]
    parts = [f"{n}/{b['tasks']} scored  hit@1 {b['hit1']}/{n}  hit@5 {b['hit5']}/{n}  MRR {b['mrr']}" if n
             else f"{b['tasks']} tasks, none scored"]
    if b["controls"]:
        parts.append(f"controls held {b['controls_held']}/{b['controls']}")
    if b["errors"]:
        parts.append(f"errors {b['errors']}")
    if b["skipped"]:
        parts.append(f"skipped {b['skipped']}")
    if b["ran"]:
        parts.append(f"tokens mean {b['tokens_mean']}  ms mean {b['ms_mean']}")
    return f"  {name:<7} " + "  ".join(parts)


def render(result: dict, other: dict | None = None) -> str:
    lines = []
    head = f"{'task':<28} {'kind':<7} {'rank':>5} {'tok':>6} {'ms':>6}"
    rev = other["rev"][:10] if other else ""
    if other:
        head += f"   {'rank@' + rev:>16} {'tok':>6} {'ms':>6}"
    lines.append(head)
    theirs = {r["id"]: r for r in other["tasks"]} if other else {}
    for r in result["tasks"]:
        line = f"{r['id']:<28} {r['kind']:<7} {_rank(r):>5} {r['tokens']:>6} {r['ms']:>6}"
        mine = _note(r)
        notes = [mine] if mine else []
        if r["id"] in theirs:
            o = theirs[r["id"]]
            line += f"   {_rank(o):>16} {o['tokens']:>6} {o['ms']:>6}"
            note = _note(o)
            if note and (o["status"] != "ok" or note != mine):
                notes.append(f"@{rev}: {note}")
        if notes:
            line += "  (" + " | ".join(notes) + ")"
        lines.append(line)
    lines.append("")
    for label, res in [("current", result)] + ([(other["rev"], other)] if other else []):
        s = res["summary"]
        lines.append(f"[{label}]")
        for target, keys in sorted(res.get("config_dropped", {}).items()):
            lines.append(f"  config  {target}: read {CONFIG_FILE} without {', '.join(keys)} "
                         "(this topomark rejects them)")
        for name, b in [("all", s["all"])] + sorted(s["by_kind"].items()):
            lines.append(_summary_line(name, b))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", type=Path, default=HERE / "eval" / "tasks.toml")
    ap.add_argument("--repo", type=Path, default=ROOT, help="target of repo = \"self\" tasks (default: this checkout)")
    ap.add_argument("--src", type=Path, default=ROOT / "src", help="topomark source to evaluate (default: this checkout)")
    ap.add_argument("--kind", action="append", choices=sorted(KIND_COMMAND), help="only these kinds (repeatable)")
    ap.add_argument("--only", action="append", metavar="ID", help="only these task ids (repeatable)")
    ap.add_argument("--compare", metavar="REV", help="also run the tasks with topomark's src/ at REV")
    ap.add_argument("--cache", type=Path, help="TOPOMARK_CACHE to use (default: a fresh temporary one)")
    ap.add_argument("--synth-files", type=int, default=SYNTH_FILES, help=f"size of the synthetic repo ({SYNTH_FILES})")
    ap.add_argument("--no-validate", action="store_true", help="skip the gold check (used by --compare)")
    ap.add_argument("--compat-config", action="store_true",
                    help="if --src rejects keys of a target's topomark.toml, read a copy without them "
                         "(used by --compare)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    args = ap.parse_args(argv)
    args.tasks = args.tasks.resolve()
    tasks = load_tasks(args.tasks)
    if args.kind:
        tasks = [t for t in tasks if t["kind"] in args.kind]
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]
    repo = args.repo.resolve()
    # The one place TOPOMARK_CACHE is set (a --compare child sets its own, in its own process).
    old_cache = os.environ.get("TOPOMARK_CACHE")
    tmp_cache = None if args.cache else tempfile.TemporaryDirectory(prefix="topomark-eval-cache-")
    os.environ["TOPOMARK_CACHE"] = str(args.cache) if args.cache else tmp_cache.name if tmp_cache else ""
    try:
        result = evaluate(tasks, repo, args.src.resolve(), validate=not args.no_validate,
                          synth_files=args.synth_files, compat_config=args.compat_config)
    except StaleGold as e:
        sys.stderr.write("eval: stale gold answers (fix tools/eval/tasks.toml):\n  " + "\n  ".join(e.problems) + "\n")
        return 2
    finally:
        if old_cache is None:
            os.environ.pop("TOPOMARK_CACHE", None)
        else:
            os.environ["TOPOMARK_CACHE"] = old_cache
        if tmp_cache is not None:
            tmp_cache.cleanup()
    other = compare_run(args.compare, args, repo) if args.compare else None
    if args.json:
        payload = dict(result)
        if other:
            payload["compare"] = other
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(render(result, other))
    return 0


if __name__ == "__main__":
    sys.exit(main())
