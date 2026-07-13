#!/usr/bin/env python3
"""
memory-touch.py: record that a memory was used.

The auditor's coldness signal (see memory-reindex.py) weighs three usage facts:
`last_accessed`, `access_count`, and `importance`. Something has to write the first two, and
that something is this script. Wire it into your agent's recall step: whenever a topic file
is pulled into context, touch it. Over time the vault learns which memories are load-bearing
and which have quietly gone cold, without anyone deciding that by hand.

It is the ONLY writer in this repo. The auditor reads and changes nothing; this changes
exactly two frontmatter fields and nothing else. It edits the frontmatter block in place:
it sets `last_accessed` to the given date (default today) and increments `access_count`
(default 0 -> 1). Existing fields are updated wherever they already live (top level or under
`metadata:`); missing fields are added under a `metadata:` block, which is created if absent.
The body is never touched.

Usage:
  memory-touch.py FILE [FILE ...]        # touch one or more topic files (writes in place)
  memory-touch.py --date YYYY-MM-DD FILE # override the access date (else today)
  memory-touch.py --dry-run FILE         # print the rewritten file, write nothing

Exit code: 0 on success, 2 if a file is missing or has no YAML frontmatter (nothing written).
"""

import sys, os, re
from datetime import date

FIELD_ORDER = ("last_accessed", "access_count")  # insertion order when adding under metadata


def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def split_frontmatter(text):
    """Return (fm_lines, body_lines) or (None, None) if there is no leading --- ... --- block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    return None, None


def _find_field(fm_lines, name):
    """Index and (indent, value) of a `name:` line anywhere in the frontmatter, else None."""
    pat = re.compile(rf"^(\s*){re.escape(name)}:\s*(.*)$")
    for i, ln in enumerate(fm_lines):
        m = pat.match(ln)
        if m:
            return i, m.group(1), m.group(2).strip()
    return None


def touch_frontmatter(fm_lines, access_date):
    """Set last_accessed and increment access_count, in place on a copy of fm_lines."""
    fm = list(fm_lines)
    ac = _find_field(fm, "access_count")
    new_count = (_to_int(ac[2], 0) if ac else 0) + 1
    values = {"last_accessed": access_date, "access_count": str(new_count)}

    missing = []
    for name in FIELD_ORDER:
        found = _find_field(fm, name)
        if found:
            i, indent, _ = found
            fm[i] = f"{indent}{name}: {values[name]}"
        else:
            missing.append(name)

    if missing:
        mi = next((i for i, ln in enumerate(fm) if re.match(r"^metadata:\s*$", ln)), None)
        if mi is None:
            fm.append("metadata:")
            mi = len(fm) - 1
        for offset, name in enumerate(missing):
            fm.insert(mi + 1 + offset, f"  {name}: {values[name]}")
    return fm


def rewrite(text, access_date):
    fm_lines, body_lines = split_frontmatter(text)
    if fm_lines is None:
        return None
    fm_lines = touch_frontmatter(fm_lines, access_date)
    out = "\n".join(["---", *fm_lines, "---", *body_lines])
    return out if out.endswith("\n") else out + "\n"


def touch_file(path, access_date):
    """Stamp one file in place. Returns 'ok', 'nofm' (no frontmatter), or 'missing'.

    This is the programmatic entry point (the recall hook calls it). It writes; callers
    that want a preview use rewrite() instead."""
    if not os.path.isfile(path):
        return "missing"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = rewrite(text, access_date)
    if out is None:
        return "nofm"
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return "ok"


def main(argv):
    access_date = date.today().isoformat()
    dry_run = False
    paths = []
    it = iter(argv)
    for a in it:
        if a == "--dry-run":
            dry_run = True
        elif a == "--date":
            access_date = next(it, access_date)
        elif a.startswith("--date="):
            access_date = a.split("=", 1)[1]
        else:
            paths.append(a)

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", access_date):
        print(f"memory-touch: --date must be YYYY-MM-DD, got {access_date!r}", file=sys.stderr)
        return 2
    if not paths:
        print("memory-touch: no files given", file=sys.stderr)
        return 2

    rc = 0
    for p in paths:
        if dry_run:
            if not os.path.isfile(p):
                print(f"memory-touch: not a file: {p}", file=sys.stderr)
                rc = 2
                continue
            with open(p, encoding="utf-8") as f:
                out = rewrite(f.read(), access_date)
            if out is None:
                print(f"memory-touch: no frontmatter, skipped: {p}", file=sys.stderr)
                rc = 2
                continue
            sys.stdout.write(out)
            continue
        status = touch_file(p, access_date)
        if status == "missing":
            print(f"memory-touch: not a file: {p}", file=sys.stderr)
            rc = 2
        elif status == "nofm":
            print(f"memory-touch: no frontmatter, skipped: {p}", file=sys.stderr)
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
