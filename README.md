# agent-memory-vault

A file-based memory layer for AI agents. Plain Markdown, a bounded index, a knowledge graph,
and a deterministic auditor that keeps it honest as it grows.

No database, no server, no lock-in. Your agent's memory is a folder of Markdown files you can
read, diff, and grep. This repo is the engine and the conventions; your facts stay yours.

## The problem

An agent's context is small and expensive. The things worth remembering are not. You cannot
load everything you know into every session, so the real design question is not *how to store*
facts, it is *what gets loaded, when, and what falls out.*

This layer answers that with three ideas:

1. **A bounded hot-set index.** One file (`MEMORY.md`) is loaded every session. It has a byte
   budget. When it is full, the lowest-value lines are evicted.
2. **Recall by description.** Every fact is a file with a one-line `description:`. Facts are
   pulled into context on demand by matching that line. So eviction from the index never loses
   a memory: the file stays, and recall still finds it.
3. **A deterministic auditor.** `memory-reindex.py` turns "is my memory healthy?" into a
   computed punch-list instead of a vibe: over budget, dangling links, orphans, hubs, stale
   entries, duplicates.

The full design is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The file format is in
[`docs/SCHEMA.md`](docs/SCHEMA.md).

## Quickstart

```bash
# See the auditor work against the bundled example vault:
python3 memory-reindex.py

# Views generated from frontmatter (type / enforcement), so index drift is a computed diff:
python3 memory-reindex.py --views

# Point it at your own vault:
python3 memory-reindex.py --dir /path/to/your/vault
#   or:  AGENT_MEMORY_DIR=/path/to/your/vault python3 memory-reindex.py
```

The bundled `example-vault/` is intentionally seeded with one dangling link, one orphan, and
one hub so the first run shows every check firing. Run against it to learn what a finding
looks like before you point the tool at real notes.

## What the audit shows

```
=== memory vault health: .../example-vault ===
index size : 1,185 / 18,432 bytes (6%)  [ok]
topic files: 6

Dangling [[wikilinks]] (body links a missing memory): 1
  - project_second_brain_launch.md  ->  [[project_never_written]]
Graph orphans (no [[links]] in or out -> merge/link or evict): 1
  - reference_orphan_note.md
Hubs (heavily referenced -> consider splitting): 1
  - project_second_brain_launch.md  (4 inbound)

=> action recommended: True
```

Exit code is `0` when healthy and `1` when action is recommended, so a scheduled job can gate
on it. `scripts/memory-audit-cron.sh` is a ready-to-schedule wrapper that logs the report and
raises a banner only when something needs attention.

## Layout

```
memory-reindex.py         the auditor (single file, no dependencies beyond Python 3)
scripts/
  memory-audit-cron.sh    schedule this for periodic health checks
docs/
  ARCHITECTURE.md         the design: hot-set, recall, enforcement tiers, the graph
  SCHEMA.md               the file format: naming, frontmatter, links, the index
example-vault/            a small, self-documenting vault that demonstrates every check
```

## Using it in your own agent

This is a substrate, not an application. It has no opinion about who the agent is or what it
does. To adopt it: keep a vault directory, put your facts in it as Markdown files following
[`docs/SCHEMA.md`](docs/SCHEMA.md), have your agent write and recall from it, and schedule the
auditor to keep it in shape.

It pairs naturally with any agent harness or assistant that already reads Markdown. The
convention is small on purpose, so it composes rather than dictates.

## License

MIT. See [LICENSE](LICENSE).
