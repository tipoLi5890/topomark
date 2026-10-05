#!/usr/bin/env python3
"""Gate every ``skills/*/SKILL.md``: a broken frontmatter makes a skill silently not load.

Checks: the frontmatter block exists and parses (a hand-written parser for the
subset skills use: ``key: value``, quoted values and ``>-`` / ``|`` block
scalars), ``name`` equals the directory name, ``description`` is non-empty and at
most 700 characters, SKILL.md is at most 15 KiB, every ``reference/...`` file it
names exists, and shipped scripts pass ``bash -n`` / ``py_compile``.

    python3 tools/lint_skills.py

Stdlib only (no PyYAML).
"""

from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SKILL_BYTES = 15 * 1024
MAX_DESCRIPTION_CHARS = 700
ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "version"}


class FrontmatterError(ValueError):
    pass


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the leading ``---`` block. Raises FrontmatterError with a reason."""
    if not text.startswith("---\n"):
        raise FrontmatterError("no frontmatter block (file must start with ---)")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise FrontmatterError("frontmatter block is not closed with ---")
    lines = text[4:end].split("\n")
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z][\w-]*):(?:\s+(.*))?$", line)
        if not m:
            raise FrontmatterError(f"line {i + 2}: expected `key: value`, got {line!r}")
        key, val = m.group(1), (m.group(2) or "").strip()
        if key in out:
            raise FrontmatterError(f"duplicate key {key!r}")
        i += 1
        if val in (">", ">-", ">+", "|", "|-", "|+") or val == "":
            block = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            if val.startswith("|"):
                out[key] = "\n".join(block).strip()
            else:
                out[key] = " ".join(b for b in block if b).strip()
            continue
        if val[0] in "\"'":
            if len(val) < 2 or val[-1] != val[0]:
                raise FrontmatterError(f"{key}: unterminated quoted string")
            val = val[1:-1]
        elif ": " in val or val.startswith(("[", "{", "&", "*", "!", "%", "@", "`")):
            raise FrontmatterError(f"{key}: plain value needs quoting or a block scalar (>-): {val[:40]!r}")
        out[key] = val
    return out


def lint_skill(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    errors = []
    size = path.stat().st_size
    if size > MAX_SKILL_BYTES:
        errors.append(f"{rel}: {size} bytes, over the {MAX_SKILL_BYTES}-byte limit")
    text = path.read_text(encoding="utf-8")
    try:
        fm = parse_frontmatter(text)
    except FrontmatterError as e:
        return errors + [f"{rel}: {e}"]
    unknown = set(fm) - ALLOWED_KEYS
    if unknown:
        errors.append(f"{rel}: unknown frontmatter keys {sorted(unknown)}")
    if fm.get("name") != path.parent.name:
        errors.append(f"{rel}: name={fm.get('name')!r} != directory {path.parent.name!r}")
    desc = fm.get("description", "")
    if not desc:
        errors.append(f"{rel}: empty description")
    elif len(desc) > MAX_DESCRIPTION_CHARS:
        errors.append(f"{rel}: description is {len(desc)} characters, over {MAX_DESCRIPTION_CHARS}")
    for ref in sorted(set(re.findall(r"`(reference/[\w./-]+\.md)`", text))):
        if not (path.parent / ref).is_file():
            errors.append(f"{rel}: names {ref}, which does not exist")
    return errors


def lint_executables() -> list[str]:
    errors = []
    if shutil.which("bash"):
        for f in sorted(ROOT.glob("skills/**/*.sh")):
            r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                errors.append(f"{f.relative_to(ROOT).as_posix()}: bash -n failed: {r.stderr.strip()[:120]}")
    for f in sorted(list(ROOT.glob("skills/**/*.py")) + list(ROOT.glob("tools/*.py"))):
        if "__pycache__" in f.parts:
            continue
        try:
            py_compile.compile(str(f), doraise=True, cfile=None)
        except py_compile.PyCompileError as e:
            errors.append(f"{f.relative_to(ROOT).as_posix()}: py_compile failed: {str(e)[:120]}")
    return errors


def main() -> int:
    skills = sorted(ROOT.glob("skills/*/SKILL.md"))
    if not skills:
        print("lint_skills: no skills/*/SKILL.md found (wrong directory?)", file=sys.stderr)
        return 1
    errors: list[str] = []
    for s in skills:
        errors += lint_skill(s)
    errors += lint_executables()
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    print(f"lint_skills: {len(skills)} SKILL.md scanned, {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
