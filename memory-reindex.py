#!/usr/bin/env python3
"""
memory-reindex.py: deterministic health auditor for an memory vault.

An memory vault is a bounded hot-set index (MEMORY.md) sitting over a pile of
typed, single-fact topic files. The index is the only thing loaded into the agent's
context every session; the topic files are surfaced on demand by recall (matching their
`description:` frontmatter). This tool makes "what should fall out of the index" a
computed answer instead of a periodic judgment call. It READS everything and CHANGES
NOTHING. It prints an exact punch-list:

  - index size vs the budget (default 18KB, the hot-set has to stay small)
  - index entry lines over the 200-char one-liner rule
  - dangling pointers    (MEMORY.md references a file that doesn't exist)
  - dangling [[wikilinks]] (a body link points at a memory that doesn't exist)
  - index orphans        (topic file not referenced in the index -> recall-only)
  - graph orphans        (topic file with no [[links]] in or out -> invisible to the graph)
  - hubs                 (heavily-referenced files that may be worth splitting)
  - eviction candidates  (status: done|dropped|shipped|archived, or a past `revisit:` date)
  - cold candidates      (behavioral disuse: old `last_accessed`, low `access_count`, low
                          `importance`; a soft demote hint, does NOT affect the exit code)
  - files missing a `description:` (recall can't find them well)
  - near-duplicate clusters (same slug prefix)

Slug matching normalizes '-' and '_' and resolves a [[link]] against BOTH the filename
stem and the `name:` frontmatter, so mixed slug conventions in a vault don't produce
false dangles. Non-memory forward-refs (e.g. [[task-42]]) are reported as benign.

Usage:
  memory-reindex.py                 # human-readable audit of the vault (default)
  memory-reindex.py --json          # machine-readable, for a scheduled agent
  memory-reindex.py --views         # views generated from frontmatter (type/enforcement)
  memory-reindex.py --dir PATH      # audit a specific vault directory
                                    # (else $AGENT_MEMORY_DIR, else ./example-vault)

Env:
  AGENT_MEMORY_DIR        vault directory to audit
  AGENT_MEMORY_BUDGET_KB  hot-set index budget in KB (default 18)
  AGENT_MEMORY_PREFIXES   comma-separated memory-slug prefixes
                          (default "feedback_,project_,reference_")

Frontmatter it understands (all optional except name + description):
  name, description, metadata.type, metadata.status, metadata.revisit (YYYY-MM-DD),
  metadata.enforcement (hook|pinned|recall),
  metadata.last_accessed (YYYY-MM-DD), metadata.access_count (int), metadata.importance (1-10)

Exit code: 0 = healthy, 1 = action recommended (over budget / dangling / stale found).
"""

import sys, os, re, json, fnmatch
from datetime import date

# --- configuration (resolved from args/env in __main__; safe import-time defaults) -------
MEM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example-vault")
INDEX = os.path.join(MEM_DIR, "MEMORY.md")
BUDGET_BYTES = int(os.environ.get("AGENT_MEMORY_BUDGET_KB", "18")) * 1024
MAX_LINE = 200
STALE_STATUSES = {"done", "dropped", "shipped", "archived", "complete", "completed"}
HUB_THRESHOLD = 4  # inbound wikilinks at/above which a file is a "hub" worth reviewing
# Behavioral "coldness" thresholds. This is a soft demote hint distinct from declarative
# staleness: it reads usage signals (last_accessed / access_count / importance) rather than a
# hand-set status. Defaults are deliberately conservative so shipping it never flags a note
# until something has actually been tracking usage. See docs/ARCHITECTURE.md ("Coldness").
COLD_DAYS = int(os.environ.get("AGENT_MEMORY_COLD_DAYS", "90"))       # recency: days untouched
COLD_MAX_HITS = int(os.environ.get("AGENT_MEMORY_COLD_MAX_HITS", "1"))  # frequency: hits at/under
IMPORTANT_MIN = int(os.environ.get("AGENT_MEMORY_IMPORTANT_MIN", "7"))  # importance: >= is protected
MEM_PREFIXES = tuple(
    p.strip() for p in
    os.environ.get("AGENT_MEMORY_PREFIXES", "feedback_,project_,reference_").split(",")
    if p.strip()
)

# [[target]] or [[target|alias]] or [[target#heading]], capturing the target only.
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


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
    return MEM_DIR


def norm_slug(s):
    """Canonicalize a slug for matching: lowercase, dashes==underscores, no .md."""
    return s.strip().lower().removesuffix(".md").replace("-", "_")


def parse_frontmatter(text):
    """Minimal YAML-frontmatter parser for the known, flat-ish memory schema."""
    fm = {"metadata": {}}
    if not text.startswith("---"):
        return fm
    end = text.find("\n---", 3)
    if end == -1:
        return fm
    block = text[3:end].strip("\n").splitlines()
    in_meta = False
    for line in block:
        if not line.strip():
            continue
        if re.match(r"^metadata:\s*$", line):
            in_meta = True
            continue
        m = re.match(r"^(\s*)([\w-]+):\s*(.*)$", line)
        if not m:
            continue
        indent, key, val = m.group(1), m.group(2), m.group(3).strip().strip('"\'')
        if in_meta and len(indent) >= 2:
            fm["metadata"][key] = val
        else:
            in_meta = False
            fm[key] = val
    return fm


def load_files():
    out = []
    for fn in sorted(os.listdir(MEM_DIR)):
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        path = os.path.join(MEM_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue
        fm = parse_frontmatter(text)
        out.append({"file": fn, "fm": fm, "text": text})
    return out


def build_graph(files):
    """Analyze the [[wikilink]] graph over the topic-file bodies.

    Node identity is the normalized filename stem. A file is reachable by either its
    filename stem OR its `name:` frontmatter (slug forms drift between - and _ across a
    vault), so both are registered as aliases pointing at the canonical file.

    Returns: dangling wikilinks (target resolves to no file), graph orphans (no inbound
    AND no outbound links -> invisible to the graph), and hubs (heavily-referenced files).
    """
    alias_to_file = {}      # normalized alias -> canonical filename
    for f in files:
        stem = norm_slug(f["file"])
        alias_to_file[stem] = f["file"]
        nm = f["fm"].get("name")
        if nm:
            alias_to_file[norm_slug(nm)] = f["file"]

    outbound = {f["file"]: set() for f in files}   # file -> set(resolved target files)
    inbound = {f["file"]: set() for f in files}     # file -> set(source files linking in)
    dangling = []                                    # (source_file, raw_target)
    for f in files:
        # strip the frontmatter block so a `name:`/description [[x]] isn't double counted
        body = f["text"]
        end = body.find("\n---", 3) if body.startswith("---") else -1
        if end != -1:
            body = body[end + 4:]
        for raw in WIKILINK_RE.findall(body):
            target = alias_to_file.get(norm_slug(raw))
            if target and target != f["file"]:
                outbound[f["file"]].add(target)
                inbound[target].add(f["file"])
            elif not target:
                dangling.append((f["file"], raw.strip()))

    orphans = sorted(
        f["file"] for f in files
        if not outbound[f["file"]] and not inbound[f["file"]]
    )
    hubs = sorted(
        ((fn, len(srcs)) for fn, srcs in inbound.items() if len(srcs) >= HUB_THRESHOLD),
        key=lambda x: -x[1],
    )
    # Only memory-slug dangles are actionable; [[task-42]]-style forward refs are allowed.
    dangling_actionable = sorted(
        d for d in dangling if norm_slug(d[1]).startswith(MEM_PREFIXES)
    )
    dangling_benign = sorted(
        d for d in dangling if not norm_slug(d[1]).startswith(MEM_PREFIXES)
    )
    return {
        "graph_orphans": orphans,
        "hubs": hubs,
        "dangling_wikilinks": dangling_actionable,
        "dangling_wikilinks_benign": dangling_benign,
    }


def index_referenced_names(index_text):
    """Every *.md basename referenced in MEMORY.md, expanding prefix_*.md globs."""
    refs = set()
    for tok in re.findall(r"`?([\w./*-]+\.md)`?", index_text):
        refs.add(os.path.basename(tok))
    return refs


def is_stale(fm, today):
    st = (fm.get("metadata", {}).get("status") or "").lower()
    if st in STALE_STATUSES:
        return f"status: {st}"
    rv = fm.get("metadata", {}).get("revisit", "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", rv)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d < today:
            return f"revisit {rv} has passed"
    return None


def _meta_get(fm, key):
    """A field may live under metadata: or at the top level; coalesce like the views do."""
    return fm.get("metadata", {}).get(key, fm.get(key))


def _to_int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def is_cold(fm, today):
    """Behavioral disuse signal, distinct from declarative staleness (is_stale).

    Staleness asks "did someone mark this finished?"; coldness asks "has this gone unused?"
    It is the index-layer weighting the Generative Agents memory paper formalizes: recency
    (time since last access) + frequency (access count) + importance. Relevance, the paper's
    fourth term, is intentionally left out here because recall-by-description already handles
    query relevance; this signal only governs what stays in the hot-set.

    Deliberately conservative and opt-in:
      - a file is ignored unless it carries a `last_accessed:` date (nothing to weigh otherwise),
      - `pinned` / `hook` memories are exempt (they are never demoted by design),
      - it fires only when ALL of recency, frequency, and importance say "low signal".

    It is a hint, not a verdict: it never flips the exit code, because disuse is a reason to
    review a note, not proof it should go. Returns a human-readable reason or None."""
    enforcement = (_meta_get(fm, "enforcement") or "recall").lower()
    if enforcement in ("pinned", "hook"):
        return None
    la = _meta_get(fm, "last_accessed") or ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(la))
    if not m:
        return None
    days = (today - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    if days < COLD_DAYS:
        return None
    hits = _to_int(_meta_get(fm, "access_count"), 0)
    if hits > COLD_MAX_HITS:
        return None
    imp = _to_int(_meta_get(fm, "importance"), None)
    if imp is not None and imp >= IMPORTANT_MIN:
        return None
    imp_str = f", importance {imp}" if imp is not None else ""
    return f"{days}d since access, {hits} hit(s){imp_str}"


def audit():
    today = date.today()
    index_text = open(INDEX, encoding="utf-8").read() if os.path.exists(INDEX) else ""
    index_bytes = len(index_text.encode("utf-8"))
    files = load_files()
    refs = index_referenced_names(index_text)
    all_names = {f["file"] for f in files}

    oversize = []
    for i, line in enumerate(index_text.splitlines(), 1):
        if line.startswith("- ") and len(line) > MAX_LINE:
            oversize.append((i, len(line)))

    # dangling: a referenced *.md (non-glob) that isn't on disk (vault dir only)
    dangling = sorted(
        n for n in refs
        if "*" not in n and n.startswith(MEM_PREFIXES) and n not in all_names
    )

    def covered(name):
        return any(fnmatch.fnmatch(name, r) for r in refs)

    orphans = sorted(f["file"] for f in files if not covered(f["file"]))
    no_desc = sorted(f["file"] for f in files if not f["fm"].get("description"))
    stale = sorted(
        (f["file"], is_stale(f["fm"], today)) for f in files if is_stale(f["fm"], today)
    )
    # Cold is a softer signal than stale, so a note that is already hard-stale is not also
    # listed as cold (the stale line is the stronger action). Cold never gates the exit code.
    stale_files = {f for f, _ in stale}
    cold = sorted(
        (f["file"], is_cold(f["fm"], today))
        for f in files
        if f["file"] not in stale_files and is_cold(f["fm"], today)
    )

    # near-duplicate clusters by first 4 slug tokens. True dups share long prefixes
    # (naming front-loads the topic); distinct topics diverge by the 4th token, so 4
    # avoids false clusters like project_ai_native_operating vs project_ai_native_pm.
    clusters = {}
    for f in files:
        key = "_".join(f["file"].replace(".md", "").split("_")[:4])
        clusters.setdefault(key, []).append(f["file"])
    dups = {k: v for k, v in clusters.items() if len(v) > 1}

    graph = build_graph(files)

    action = bool(
        index_bytes > BUDGET_BYTES or oversize or dangling or stale
        or graph["dangling_wikilinks"]
    )
    report = {
        "vault_dir": MEM_DIR,
        "index_bytes": index_bytes, "budget_bytes": BUDGET_BYTES,
        "over_budget": index_bytes > BUDGET_BYTES,
        "topic_files": len(files),
        "oversize_lines": oversize, "dangling_pointers": dangling,
        "orphan_files": orphans, "missing_description": no_desc,
        "stale_candidates": stale, "cold_candidates": cold, "duplicate_clusters": dups,
        "graph_orphans": graph["graph_orphans"],
        "hubs": graph["hubs"],
        "dangling_wikilinks": graph["dangling_wikilinks"],
        "dangling_wikilinks_benign": graph["dangling_wikilinks_benign"],
        "action_recommended": action,
    }
    return report


def print_human(r):
    pct = round(100 * r["index_bytes"] / r["budget_bytes"]) if r["budget_bytes"] else 0
    flag = "OVER BUDGET" if r["over_budget"] else "ok"
    print(f"\n=== memory vault health: {r['vault_dir']} ===")
    print(f"index size : {r['index_bytes']:,} / {r['budget_bytes']:,} bytes ({pct}%)  [{flag}]")
    print(f"topic files: {r['topic_files']}")

    def section(title, items, fmt):
        print(f"\n{title}: {len(items)}")
        for it in items[:40]:
            print("  - " + fmt(it))

    section("Oversize index lines (>200 chars)", r["oversize_lines"],
            lambda x: f"line {x[0]} ({x[1]} chars)")
    section("Dangling pointers (index references a missing file)", r["dangling_pointers"], str)
    section("Dangling [[wikilinks]] (body links a missing memory)", r["dangling_wikilinks"],
            lambda x: f"{x[0]}  ->  [[{x[1]}]]")
    section("Stale / lapsed -> evict from index", r["stale_candidates"],
            lambda x: f"{x[0]}  ({x[1]})")
    section("Cold / disused -> consider demoting (hint, not gated)", r["cold_candidates"],
            lambda x: f"{x[0]}  ({x[1]})")
    section("Graph orphans (no [[links]] in or out -> merge/link or evict)", r["graph_orphans"], str)
    section("Index orphans (on disk, not in index -> recall-only)", r["orphan_files"], str)
    section("Missing description (recall-impaired)", r["missing_description"], str)
    section("Hubs (heavily referenced -> consider splitting)", r["hubs"],
            lambda x: f"{x[0]}  ({x[1]} inbound)")
    dups = r["duplicate_clusters"]
    print(f"\nNear-duplicate clusters (consider merging): {len(dups)}")
    for k, v in list(dups.items())[:20]:
        if len(v) > 1:
            print(f"  - {k}*: {', '.join(v)}")
    print(f"\n=> action recommended: {r['action_recommended']}\n")


def print_views(files):
    """Views generated FROM frontmatter instead of hand-maintaining index sections.
    Groups every topic file by its declared type and enforcement so drift between the
    frontmatter and the index is a computed diff, not a memory. Read-only."""
    def group_by(key):
        # type/enforcement live under metadata: in some files and at the top level in
        # others. Coalesce both so the view reflects the value, not the placement.
        buckets = {}
        for f in files:
            fm = f["fm"]
            val = (fm.get("metadata", {}).get(key) or fm.get(key) or "(none)").lower()
            buckets.setdefault(val, []).append(f["file"])
        return dict(sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])))

    for dim in ("type", "enforcement"):
        print(f"\n=== view: by {dim} ===")
        for val, fs in group_by(dim).items():
            print(f"\n[{dim}={val}]  ({len(fs)})")
            for fn in sorted(fs):
                desc = next((x["fm"].get("description", "") for x in files if x["file"] == fn), "")
                print(f"  - {fn[:-3]}" + (f": {desc}" if desc else ""))
    print()


if __name__ == "__main__":
    MEM_DIR = resolve_mem_dir(sys.argv[1:])
    INDEX = os.path.join(MEM_DIR, "MEMORY.md")
    if not os.path.isdir(MEM_DIR):
        sys.exit(f"memory-reindex: vault dir not found: {MEM_DIR}")
    if "--views" in sys.argv:
        print_views(load_files())
        sys.exit(0)
    r = audit()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2))
    else:
        print_human(r)
    sys.exit(1 if r["action_recommended"] else 0)
