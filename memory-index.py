#!/usr/bin/env python3
"""memory-index.py: GENERATE the MEMORY.md pointer block from the memories themselves.

The problem this removes
------------------------
A hand-maintained index asks a human (or an agent) to hold three constraints in their head on
every write: a line limit the consumer enforces SILENTLY (a Claude Code memory index is cut off
at 200 lines on read, with no error), a byte budget, and 100% coverage of the vault. Hand-held
constraints drift. In the vault this was extracted from, the index was over the line limit and
53 of 172 memories (31%) had no pointer at all, so they were invisible to the index and the
orphan detector that should have caught it was buried in false positives.

The fix is to stop maintaining it. Each memory carries its own `cluster:` and `hook:` in
frontmatter, and this script renders the pointer block from that. Consequences:

  * Adding a memory adds its pointer. Coverage is 100% BY CONSTRUCTION, not by discipline.
  * Line count scales with the number of CLUSTERS, not the number of memories. Going from 170
    to 250 memories makes lines longer, never more numerous.
  * The line limit becomes this script's problem instead of a thing anyone remembers.

Resident sections stay hand-written ABOVE the BEGIN marker. They hold what must fire unprompted
(hard rules, never-default-wrong facts), where absence is a SILENT failure and the reasoning is
the payload. Any memory already referenced outside the generated block is skipped inside it, so
nothing is listed twice, and a memory dropped from the resident block reappears in the generated
block automatically instead of going missing.

Frontmatter it reads (root level or under `metadata:`):
  cluster: <heading the pointer is grouped under>      default "Unsorted"
  hook:    <a few words of relevance, shown after the filename>   optional
  description:                                          used for the no-description warning

Usage
-----
  memory-index.py build            # regenerate the block in place
  memory-index.py build --init     # also append the marker pair to MEMORY.md if it has none
  memory-index.py build --dry      # print what would change, write nothing
  memory-index.py --check          # validate only; exit 1 if action needed (hooks, cron)
  memory-index.py --report         # coverage, budget, composition, coldest memories
  memory-index.py --dir PATH ...   # vault directory (else $AGENT_MEMORY_DIR, else ./example-vault)

Env
---
  AGENT_MEMORY_DIR            vault directory
  AGENT_MEMORY_LINE_LIMIT     hard line limit the consumer enforces (default 200)
  AGENT_MEMORY_BUDGET_KB      byte budget for the whole index (default 18, same as the auditor)
  AGENT_MEMORY_CLUSTER_ORDER  comma-separated cluster names to present first, in this order;
                              other clusters follow alphabetically; "Unsorted" is always last

Exit codes: 0 healthy, 1 action needed. Read-only except for `build`, which writes MEMORY.md.
"""

import argparse
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))

BEGIN = "<!-- BEGIN GENERATED POINTERS. Do not hand-edit: run memory-index.py build. -->"
END = "<!-- END GENERATED POINTERS -->"
PROSE_START = "reindex:prose-start"   # the auditor's markers for the resident prose region
PROSE_END = "reindex:prose-end"

FM_KEY = re.compile(r"^([A-Za-z_]+):\s*(.*)$")


def config_from_env():
    hard = int(os.environ.get("AGENT_MEMORY_LINE_LIMIT", "200"))
    return {
        # The consumer silently drops everything past this line. The soft target leaves headroom.
        "hard_line_limit": hard,
        "soft_line_target": int(hard * 0.7),
        "byte_budget": int(os.environ.get("AGENT_MEMORY_BUDGET_KB", "18")) * 1024,
        # Informational only: the resident half competes for attention every session, so it is
        # the half whose growth deserves a challenge. Not a gate.
        "resident_warn_bytes": 8 * 1024,
        "cluster_order": [c.strip() for c in os.environ.get("AGENT_MEMORY_CLUSTER_ORDER", "").split(",") if c.strip()],
    }


def resolve_mem_dir(argv):
    """Vault dir precedence: --dir PATH  >  $AGENT_MEMORY_DIR  >  bundled example-vault."""
    for i, a in enumerate(argv):
        if a == "--dir" and i + 1 < len(argv):
            return os.path.abspath(os.path.expanduser(argv[i + 1]))
        if a.startswith("--dir="):
            return os.path.abspath(os.path.expanduser(a.split("=", 1)[1]))
    env = os.environ.get("AGENT_MEMORY_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(HERE, "example-vault")


def unquote(v):
    """Strip only a MATCHED surrounding quote pair.

    strip("\\"'") would eat an unmatched trailing quote and silently truncate a value like
    `processing lead, "the problem"` into `processing lead, 'the problem`.
    """
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def read_frontmatter(path):
    """Flat frontmatter read, plus the one nested block (metadata:) that matters here."""
    out, meta = {}, {}
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return out, meta
    if not text.startswith("---"):
        return out, meta
    end = text.find("\n---", 3)
    if end == -1:
        return out, meta
    in_meta = False
    for line in text[4:end].splitlines():
        if line.startswith("  ") and in_meta:
            m = FM_KEY.match(line.strip())
            if m:
                meta[m.group(1)] = unquote(m.group(2))
            continue
        in_meta = False
        m = FM_KEY.match(line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if k == "metadata":
            in_meta = True
            continue
        out[k] = unquote(v)
    return out, meta


def load_memories(mem_dir):
    mems = []
    for f in sorted(os.listdir(mem_dir)):
        if not f.endswith(".md") or f == "MEMORY.md":
            continue
        fm, meta = read_frontmatter(os.path.join(mem_dir, f))
        mems.append(
            {
                "slug": f[:-3],
                "file": f,
                # Root first, then the nested metadata block. Some editing tools normalize
                # memory frontmatter to name/description/metadata.* and MOVE any other root key
                # (cluster, hook) inside metadata. A root-only read would lose the cluster on any
                # tool-based write and the pointer would silently land in Unsorted. Accepting both
                # shapes is cheaper than forbidding the tools.
                "cluster": fm.get("cluster") or meta.get("cluster") or "Unsorted",
                "hook": fm.get("hook") or meta.get("hook") or "",
                "desc": fm.get("description") or "",
                "last_accessed": meta.get("last_accessed") or fm.get("last_accessed", ""),
                "access_count": meta.get("access_count") or fm.get("access_count", ""),
            }
        )
    return mems


def split_index(text):
    """-> (head, generated, tail), or (None, None, None) if the markers are absent."""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        gen, tail = rest.split(END, 1)
        return head, gen, tail
    return None, None, None


def render(mems, outside_text, cfg):
    """Pointer lines for every memory NOT already referenced outside the generated block."""
    by_cluster, skipped = {}, []
    for m in mems:
        if m["file"] in outside_text:
            skipped.append(m["slug"])
            continue
        by_cluster.setdefault(m["cluster"], []).append(m)

    order = [c for c in cfg["cluster_order"] if c in by_cluster]
    order += sorted(c for c in by_cluster if c not in cfg["cluster_order"] and c != "Unsorted")
    if "Unsorted" in by_cluster:
        order.append("Unsorted")

    lines = []
    for c in order:
        # resident:* clusters only appear here if the memory FELL OUT of the resident block,
        # which is a real problem, so label it loudly instead of hiding it.
        label = c
        if c.startswith("resident:"):
            label = "NOT IN RESIDENT BLOCK (%s), re-add above or re-cluster" % c
        parts = [
            "`%s`%s" % (m["file"], (" " + m["hook"]) if m["hook"] else "")
            for m in sorted(by_cluster[c], key=lambda x: x["slug"])
        ]
        # One dense line per cluster, on purpose. Lines are the scarce resource (the consumer's
        # limit is in lines and it truncates silently); characters are not. Wrapping was tried
        # and rejected: it cost lines and fixed nothing.
        lines.append("**%s.** " % label + " · ".join(parts))
    return lines, skipped, by_cluster


def build_text(head, tail, lines):
    return head + BEGIN + "\n\n" + "\n\n".join(lines) + "\n\n" + END + tail


def coldness_key(m):
    """Coldest first: never-accessed, then oldest access, then lowest count."""
    la = m["last_accessed"] or "0000-00-00"
    try:
        ac = int(m["access_count"] or 0)
    except ValueError:
        ac = 0
    return (la, ac)


def audit(text, mems, cfg):
    problems, warnings = [], []
    n_lines = len(text.splitlines())
    n_bytes = len(text.encode("utf-8"))
    hard, soft = cfg["hard_line_limit"], cfg["soft_line_target"]

    if n_lines > hard:
        problems.append(
            "OVER THE READ LIMIT: %d lines > %d. Everything past line %d is SILENTLY DROPPED when "
            "the index loads." % (n_lines, hard, hard)
        )
    elif n_lines > soft:
        warnings.append(
            "%d lines, over the %d target (hard cliff %d). Merge or archive memories, or fold two "
            "clusters together." % (n_lines, soft, hard)
        )
    if n_bytes > cfg["byte_budget"]:
        problems.append("over byte budget: %d > %d" % (n_bytes, cfg["byte_budget"]))

    # Lint ONLY the region this script generates. The hand-written resident sections are not
    # this script's to police.
    inside = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith(BEGIN[:40]):
            inside = True
            continue
        if line.startswith(END[:20]):
            inside = False
            continue
        if inside and "NOT IN RESIDENT BLOCK" in line:
            problems.append("line %d: a memory tagged resident:* is missing from the hand-written block" % i)

    missing = [m["file"] for m in mems if m["file"] not in text]
    if missing:
        problems.append("NOT COVERED (%d): %s" % (len(missing), ", ".join(missing)))

    no_cluster = [m["slug"] for m in mems if m["cluster"] == "Unsorted"]
    if no_cluster:
        warnings.append(
            "%d memories have no readable cluster:, landing in Unsorted. The field is either absent or "
            "nested somewhere this reader does not look: %s" % (len(no_cluster), ", ".join(no_cluster))
        )
    no_desc = [m["slug"] for m in mems if not m["desc"]]
    if no_desc:
        warnings.append("no description: (recall-impaired): %s" % ", ".join(no_desc))
    return problems, warnings, n_lines, n_bytes


def report(new_text, mems, skipped, by_cluster, n_lines, n_bytes, cfg):
    print("=== memory index report (%s) ===" % date.today().isoformat())
    print("memories        : %d" % len(mems))
    print("resident (above): %d" % len(skipped))
    print("generated       : %d in %d clusters" % (len(mems) - len(skipped), len(by_cluster)))
    print("lines           : %d / %d hard, %d target" % (n_lines, cfg["hard_line_limit"], cfg["soft_line_target"]))
    print("bytes           : %d / %d" % (n_bytes, cfg["byte_budget"]))
    print()
    print("HEADROOM: lines scale with clusters, not memories, so growth is safe.")
    print("  bytes left: %d (~%d more memories at ~90B each)"
          % (cfg["byte_budget"] - n_bytes, max(0, (cfg["byte_budget"] - n_bytes) // 90)))
    print()
    # Split resident from generated. These two grow for different reasons and only one of them is
    # worth challenging: resident content competes for attention every session, while the
    # generated block is mechanical and only costs bytes. A single blended byte budget cannot tell
    # them apart, so it ends up pressuring the resident sections, which are the highest-value
    # content and the one thing the design says not to thin.
    src = new_text.splitlines(keepends=True)

    def _find(needle, default):
        hits = [i for i, l in enumerate(src) if needle in l]
        return hits[0] if hits else default

    i_gs = _find(BEGIN[:20], 0)
    i_ge = _find(END[:20], len(src) - 1)
    i_ps = _find(PROSE_START, 0)
    i_pe = _find(PROSE_END, i_gs)
    nb = lambda a, z: sum(len(l.encode("utf-8")) for l in src[a:z])
    resident, generated = nb(i_ps, i_pe + 1), nb(i_gs, i_ge + 1)
    print("COMPOSITION (the two halves grow for different reasons):")
    print("  resident  (hand-written, competes for attention) : %6d B  ~%4d tok  %4.1f%%"
          % (resident, resident // 4, 100.0 * resident / max(n_bytes, 1)))
    print("  generated (mechanical, cheap to carry)           : %6d B  ~%4d tok  %4.1f%%"
          % (generated, generated // 4, 100.0 * generated / max(n_bytes, 1)))
    if resident > cfg["resident_warn_bytes"]:
        print("  ^ resident is over %d B. THIS is the half worth challenging; merging memories barely"
              % cfg["resident_warn_bytes"])
        print("    moves bytes (~60B each), so do not let a byte budget push you into thinning hard rules.")
    print()
    cold = sorted(mems, key=coldness_key)[:12]
    print("COLDEST 12 (merge/archive candidates if you ever need lines or bytes):")
    for m in cold:
        print("  %-58s last=%s count=%s" % (m["slug"][:58], m["last_accessed"] or "never", m["access_count"] or "0"))


def run(argv=None, mem_dir=None):
    """Entry point usable from tests. Returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", default="check", choices=["build", "check", "report"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--init", action="store_true", help="append the marker pair if MEMORY.md has none (build only)")
    ap.add_argument("--quiet", action="store_true", help="print only on failure")
    ap.add_argument("--dir", default=None)
    args = ap.parse_args(argv)
    action = "check" if args.check else "report" if args.report else args.action
    cfg = config_from_env()

    mem_dir = mem_dir or resolve_mem_dir(argv)
    index = os.path.join(mem_dir, "MEMORY.md")
    if not os.path.isdir(mem_dir):
        print("FAIL: vault dir not found: %s" % mem_dir, file=sys.stderr)
        return 1
    if not os.path.exists(index):
        if action == "build" and args.init:
            open(index, "w", encoding="utf-8").write("# Memory\n\n")
        else:
            print("FAIL: %s missing (run: memory-index.py build --init)" % index, file=sys.stderr)
            return 1

    original = open(index, encoding="utf-8").read()
    head, gen, tail = split_index(original)
    if head is None:
        if action == "build" and args.init:
            original = original.rstrip("\n") + "\n\n" + BEGIN + "\n\n" + END + "\n"
            head, gen, tail = split_index(original)
        else:
            print(
                "FAIL: markers not found in MEMORY.md. Run `memory-index.py build --init` to append "
                "them, or place these around the pointer block:\n  %s\n  %s" % (BEGIN, END),
                file=sys.stderr,
            )
            return 1

    mems = load_memories(mem_dir)
    lines, skipped, by_cluster = render(mems, head + tail, cfg)
    new_text = build_text(head, tail, lines)
    problems, warnings, n_lines, n_bytes = audit(new_text, mems, cfg)

    if action == "build":
        changed = new_text != original
        if args.dry:
            print("would %s: %d lines, %d bytes" % ("CHANGE" if changed else "keep", n_lines, n_bytes))
        elif changed:
            open(index, "w", encoding="utf-8").write(new_text)
        if not args.quiet:
            print(
                "index %s: %d lines / %d limit, %d bytes / %d budget, %d memories "
                "(%d resident outside the block, %d pointers in %d clusters)"
                % ("written" if changed and not args.dry else "already current",
                   n_lines, cfg["hard_line_limit"], n_bytes, cfg["byte_budget"],
                   len(mems), len(skipped), len(mems) - len(skipped), len(by_cluster))
            )

    if action == "report":
        report(new_text, mems, skipped, by_cluster, n_lines, n_bytes, cfg)

    if problems:
        print("\nACTION NEEDED:", file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
    if warnings and not args.quiet:
        print("\nwarnings:")
        for w in warnings:
            print("  - %s" % w)

    if action == "check" and not problems and not args.quiet:
        print("OK: %d lines / %d, %d bytes / %d, %d memories all covered"
              % (n_lines, cfg["hard_line_limit"], n_bytes, cfg["byte_budget"], len(mems)))
    if action == "check" and new_text != original:
        print("\nSTALE: the generated block does not match the memories on disk. Run: memory-index.py build",
              file=sys.stderr)
        return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run())
