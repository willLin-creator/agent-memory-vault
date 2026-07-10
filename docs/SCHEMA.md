# Schema

The whole contract is: one fact per file, Markdown body, YAML frontmatter on top, an index
file named `MEMORY.md`. Everything below is what the auditor understands.

## File naming

Topic files are named `<type>_<slug>.md`, for example `feedback_prefers_tight_writing.md`.

The default memory-slug prefixes are `feedback_`, `project_`, `reference_` (override with
`AGENT_MEMORY_PREFIXES`). The prefix does two jobs: it types the file at a glance, and it
tells the auditor which `[[links]]` are supposed to resolve to a real memory (so a link to a
non-memory entity like `[[task-42]]` is treated as a benign forward-reference, not rot).

Slugs are matched case-insensitively and `-` is treated the same as `_`, so a vault that
mixes `reference-foo` and `reference_foo` will not throw false dangling-link warnings.

## Frontmatter

```yaml
---
name: feedback_prefers_tight_writing        # required. the wikilink target for this file.
description: The user prefers tight writing. # required. the string recall matches against.
metadata:
  type: feedback                             # feedback | project | reference (or your own)
  enforcement: recall                        # hook | pinned | recall   (default: recall)
  status: active                             # active | done | dropped | shipped | archived
  revisit: 2026-09-01                        # YYYY-MM-DD; once past, flagged for eviction
  last_accessed: 2026-07-10                  # YYYY-MM-DD; when recall last used it (see memory-touch.py)
  access_count: 12                           # int; how many times recall has used it
  importance: 8                              # 1-10; high importance is protected from cold-demotion
---
```

- **`name`** and **`description`** are the only required fields. `description` is the most
  important line in the file: recall lives or dies by it, so write it as the sentence you
  would want to match on later.
- **`type`** and **`enforcement`** may be nested under `metadata:` or placed at the top
  level. The auditor coalesces both. Pick one convention and the `--views` command will show
  you if any file drifted from it.
- **`status`** and **`revisit`** drive staleness. A finished project or a lapsed revisit date
  is an eviction candidate, surfaced automatically.
- **`last_accessed`**, **`access_count`**, and **`importance`** drive *coldness*, a softer
  counterpart to staleness: a note that has gone unused (old `last_accessed`, low
  `access_count`) and is not marked important is surfaced as a demote hint, never gated or
  deleted. These are written by `scripts/memory-touch.py` from your agent's recall step, not by
  hand. `pinned` and `hook` memories are never cold. See `docs/ARCHITECTURE.md`.

## Body

Plain Markdown. Two conventions the auditor and recall reward:

- Keep it to a single fact. If a file wants to be two facts, it is two files.
- For `feedback` and `project` files, a `**Why:**` and `**How to apply:**` line make the
  memory actionable rather than merely true.

## Links

Link related facts with `[[name]]`, where `name` is another file's `name:` (or its filename
stem). Link liberally. A `[[link]]` to a memory you have not written yet is fine; it is a
marker of something worth writing, and the auditor will list it as a dangling link until the
file exists. That list is a to-do, not an error log.

## The index (`MEMORY.md`)

- Every entry is one line: a slug plus a relevance hook. Detail lives in the topic file, not
  the index. Lines over 200 characters are flagged.
- Reference each listed topic file by its filename so the auditor can check coverage.
- Stay under the byte budget (18KB default). Over budget, evict the lowest-value lines. The
  files stay; recall still finds them.
