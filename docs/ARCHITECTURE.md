# Architecture

Agent memory has one hard constraint the rest of the design falls out of: **context is
small and expensive, but the things worth remembering grow without bound.** You cannot load
everything you know into every session. So the real question is not "how do I store facts,"
it is "what gets loaded, when, and what falls out."

This system answers that with three commitments.

## 1. A bounded hot-set index

`MEMORY.md` is the only file loaded into the agent's context every session. It is a
**bounded hot-set**, not a registry of everything. It holds:

- always-on hard rules (things that must never be forgotten), and
- one-line pointers to the current working set.

It has a byte budget (18KB by default). When it exceeds the budget, the lowest-value lines
are **evicted**. Eviction is cheap and safe because of commitment #2.

The point of the budget is discipline. Without it, an index grows until it is as expensive
to load as the thing it was supposed to summarize. A hard ceiling forces a ranking decision
every time the vault grows, and the auditor makes that decision a computed one.

## 2. Recall by description, not by index membership

Every topic file is a single fact with a one-line `description:` in its frontmatter.
"Recall" is the act of matching a query against those descriptions and pulling the relevant
files into context on demand.

This is the load-bearing idea: **evicting a line from the index does not lose the memory.**
The file and its description remain on disk, and recall still finds them. The index is a
hot cache; the topic files are the cold store. So the index can stay small forever without
knowledge loss, and "what should fall out of the index" becomes a low-stakes question
instead of a deletion.

A corollary: a file on disk that is not in the index is not an error. It is **recall-only**,
which is the correct resting state for most memories most of the time.

## 3. A deterministic auditor

`memory-reindex.py` reads the whole vault and changes nothing. It turns every judgment call
about vault health into a computed punch-list:

| Signal | What it means | Action |
|---|---|---|
| over budget | the hot-set is too big to load cheaply | evict lowest-value index lines |
| oversize index line | an entry smuggled detail into the index | move detail to the topic file |
| dangling pointer | the index names a file that is gone | fix or drop the pointer |
| **dangling `[[wikilink]]`** | a body links a memory that does not exist | fix the link or write the memory |
| **graph orphan** | a file with no links in or out | link into a hub, merge, or evict |
| **hub** | a file many others depend on | consider splitting; handle with care |
| stale / lapsed | `status:` done, or `revisit:` date passed | evict from the index |
| cold / disused | `last_accessed` old, `access_count` low, not important | consider demoting (a hint, not gated) |
| missing description | recall cannot surface it well | add a `description:` |
| near-duplicate | two files share a long slug prefix | consider merging |

Determinism matters because the alternative is asking an LLM "is my memory healthy?" every so
often and getting a different, unfalsifiable answer each time. A script gives the same answer
twice and can gate a scheduled job on its exit code (`0` healthy, `1` action recommended).

## The knowledge graph

Topic files link to each other with `[[wikilinks]]`. The auditor builds the directed graph
over those links and uses it two ways:

- **Integrity.** A `[[link]]` to a memory that does not exist is a silent rot vector. The
  auditor resolves each link against both the filename stem and the `name:` frontmatter, and
  normalizes `-` against `_`, so mixed slug conventions do not produce false alarms. Links to
  non-memory entities (a task id, a ticket) are classified benign and never block.
- **Shape.** Orphans (no edges) and hubs (many inbound edges) are the two ends of the health
  spectrum. Orphans are candidates to connect or retire; hubs are your load-bearing concepts,
  worth protecting and sometimes splitting.

## Enforcement tiers

Not every memory is equal. A fact carries an optional `enforcement:` level that says how
hard the system should hold it:

- **hook**: mechanically enforced outside the model (a pre-write hook, a linter). The model
  cannot violate it even if it tries. Reserve for rules that must never break.
- **pinned**: always kept in the hot-set index, never evicted. The model always sees it.
- **recall** (default): surfaced by description when relevant. The overwhelming majority of
  memories live here.

The tiers are a cost gradient. Hook enforcement is the most reliable and the most work;
recall is the cheapest and scales to thousands of facts. You spend reliability only where a
mistake is expensive.

## Coldness: usage-weighted demotion

Staleness above is declarative: a human marks a note `done` or lets a `revisit:` date lapse.
But most memories never get marked anything. They just quietly stop being useful. Coldness is
the behavioral counterpart, and it is the one place this design borrows a scoring idea from the
Generative Agents memory paper (Park et al., 2023), whose retrieval score sums **recency**,
**frequency**, **importance**, and **relevance**.

Three of those four are usage facts about a note, and they map onto optional frontmatter:

- **recency** is `last_accessed` (a date), the dominant term, weighed by time since last use.
- **frequency** is `access_count`, an integer bumped each time recall uses the note.
- **importance** is `importance` (1-10), a protection weight, so a rarely-touched but important
  note is not demoted.

The fourth term, **relevance**, is deliberately left out. Relevance is a property of a *query*,
not of a note at rest, and recall-by-description (commitment #2) already handles it. Coldness
governs only the hot-set layer: what deserves to stay resident, not what matches right now.

The signal is conservative on purpose:

- **Opt-in.** A note with no `last_accessed` is never cold. Shipping this flags nothing until
  something is actually recording usage, so it cannot avalanche on an existing vault.
- **Non-destructive and non-gating.** Cold is a hint printed for review. It never deletes, and
  it never flips the auditor's exit code. Disuse is a reason to look, not a verdict.
- **Tier-aware.** `pinned` and `hook` memories are exempt. They are load-bearing by
  declaration, and no amount of disuse should push them out.

Writing the usage facts is a separate, single-purpose tool, `scripts/memory-touch.py`. The
auditor still writes nothing; the toucher writes exactly two fields (`last_accessed`,
`access_count`). Wire the toucher into your recall step and the vault starts learning its own
working set. Thresholds (`AGENT_MEMORY_COLD_DAYS`, `AGENT_MEMORY_COLD_MAX_HITS`,
`AGENT_MEMORY_IMPORTANT_MIN`) tune how patient the signal is.

## Why files, not a database

The whole vault is plain Markdown with YAML frontmatter. That is deliberate:

- **The agent reads and writes it natively.** No schema migration, no query language, no
  server. Writing a memory is writing a file.
- **It is inspectable and diffable.** You can read your agent's memory in any editor and
  track its evolution in git.
- **No lock-in.** The format outlives any tool, including this one. The auditor is a
  convenience over the data, not a gatekeeper of it.

The cost is that structure is a convention rather than a constraint, which is exactly what
the deterministic auditor exists to backstop.
