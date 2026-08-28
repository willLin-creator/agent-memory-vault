# agent-memory-vault

A file-based memory layer for AI agents. Plain Markdown, a bounded index, a knowledge graph,
and a deterministic auditor that keeps it honest as it grows.

No database, no server, no lock-in. Your agent's memory is a folder of Markdown files you can
read, diff, and grep. This repo is the engine and the conventions; your facts stay yours.

## Provenance

This is a genericized split-out of one piece of a private AI operating system I have built, refined,
and relied on daily for **3,000+ hours** of real work: the memory layer that let a chief-of-staff
agent remember across sessions and stay honest as its vault grew past what any index could list by
hand. The public repository is a fresh extraction with every personal and company detail removed, so
its commit history is recent. **The engine it is distilled from is not.** Every check here fired on a
real vault before it was written down: the 31% uncovered memories, the silently truncated index, the
lessons file nobody read any more.

Sibling extractions from the same system: [ai-chief-of-staff](https://github.com/willLin-creator/ai-chief-of-staff)
(the operating system itself), [agent-eval-loop](https://github.com/willLin-creator/agent-eval-loop)
(corrections as scored cases, enforcement that graduates on evidence), and
[agent-harness](https://github.com/willLin-creator/agent-harness) (the engineering loop). Each works
alone.

## The problem

An agent's context is small and expensive. The things worth remembering are not. You cannot
load everything you know into every session, so the real design question is not *how to store*
facts, it is *what gets loaded, when, and what falls out.*

This layer answers that with four ideas:

1. **A bounded hot-set index.** One file (`MEMORY.md`) is loaded every session. It has a line
   limit (the one its consumer silently enforces) and a byte budget. A small hand-written block
   holds the rules that must fire unprompted.
2. **Generated pointers.** Everything else in the index is rendered by `memory-index.py` from each
   memory's own `cluster:` / `hook:` frontmatter. Coverage is 100% by construction, and the line
   count scales with clusters, not memories, so the index stops being something anyone maintains.
3. **Recall by description.** Every fact is a file with a one-line `description:`. Facts are
   pulled into context on demand by matching that line. So a memory that is only a pointer, or
   no pointer at all, is never lost: the file stays, and recall still finds it.
4. **A deterministic auditor and a gated consolidation pass.** `memory-reindex.py` turns "is my
   memory healthy?" into a computed punch-list instead of a vibe: over budget, dangling links,
   orphans, hubs, stale entries, duplicates, cold notes. `skills/consolidate/` is the human-gated
   pass that acts on it: merge, delete what is wrong, demote what is cold, fix the rest.

The full design is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The file format is in
[`docs/SCHEMA.md`](docs/SCHEMA.md).

## Quickstart

```bash
# See the auditor work against the bundled example vault:
python3 memory-reindex.py

# Regenerate the example index's pointer block from the memories' frontmatter:
python3 memory-index.py build --dir example-vault
python3 memory-index.py --report --dir example-vault     # coverage, budget, composition

# Views generated from frontmatter (type / enforcement), so index drift is a computed diff:
python3 memory-reindex.py --views

# Point both at your own vault:
export AGENT_MEMORY_DIR=/path/to/your/vault
python3 memory-index.py build --init     # appends the marker pair to your MEMORY.md, then renders
python3 memory-reindex.py

# Run the tests:
python3 tests/test_memory.py
```

To adopt the generated block in an existing vault, add `cluster: <heading>` (and optionally
`hook: <a few words>`) to each memory's frontmatter and run `memory-index.py build --init`. Memories
without a cluster land in `Unsorted` and are warned about, so you can migrate incrementally.

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
memory-index.py           the generator: renders the pointer block from frontmatter; --check for cron
scripts/
  memory-audit-cron.sh    schedule this: generator check + auditor, banner when there is work
  memory-touch.py         the only writer besides the generator: stamps last_accessed / access_count
hooks/
  recall-touch.py         PostToolUse(Read): stamp a memory when the agent reads it
  memory-index-rebuild.sh PostToolUse(Edit|Write): regenerate the pointer block on every memory write
docs/
  ARCHITECTURE.md         the design: hot-set, generated vs resident, the consumer's limit, the graph
  SCHEMA.md               the file format: naming, frontmatter, links, the two index regions
example-vault/            a small, self-documenting vault that demonstrates every check
skills/
  remember/SKILL.md       the write path: capture a fact as a schema-correct, linked note
  consolidate/SKILL.md    the maintenance path: merge / delete / demote / fix, every mutation gated
tests/test_memory.py      stdlib unittest for the auditor, generator, toucher, and both hooks
```

## Using it in your own agent

This is a substrate, not an application. It has no opinion about who the agent is or what it
does. To adopt it: keep a vault directory, put your facts in it as Markdown files following
[`docs/SCHEMA.md`](docs/SCHEMA.md), have your agent write and recall from it, and schedule the
auditor to keep it in shape.

The four surfaces of the vault: **write** (`skills/remember/`: classify, dedupe, draft, confirm,
write a schema-correct note), **index** (`memory-index.py` renders the pointers; nothing to
maintain), **recall** (match a note's `description` to pull it into context on demand), and
**consolidate** (`memory-reindex.py` detects, `skills/consolidate/` judges and, with your approval,
merges, deletes, demotes, fixes). The write skill exists so your agent produces well-formed,
cross-linked notes instead of freehand files; the consolidate skill exists because a memory that
only ever adds is a log.

It pairs with two sibling repos. [ai-chief-of-staff](https://github.com/willLin-creator/ai-chief-of-staff)
is the operating system this vault was extracted from; its `/capture` command is a write path with
index reconciliation built in. [agent-eval-loop](https://github.com/willLin-creator/agent-eval-loop)
scores the `feedback` memories' corrections and recommends when a rule's `enforcement:` tier should
move. Neither is required.

It pairs naturally with any agent harness or assistant that already reads Markdown. The
convention is small on purpose, so it composes rather than dictates.

## License

MIT. See [LICENSE](LICENSE).
