---
name: remember
description: Capture a durable fact into the memory vault as a schema-correct, cross-linked note, and keep the bounded index honest. The write path for agent-memory-vault.
---

# /remember: write a fact into the memory vault

The write side of the vault. Recall reads (it matches a note's `description`), the auditor
(`memory-reindex.py`) maintains, and this is how a well-formed note gets *in*. Its whole job is to
turn "remember this" into a single, typed, cross-linked file that recall can find later, without
duplicating what is already there.

Read [`docs/SCHEMA.md`](../../docs/SCHEMA.md) for the exact file format this must produce. The vault
directory is `$AGENT_MEMORY_DIR` (else the repo's `example-vault/`).

## When to use it

Use it when a fact is durable and worth recalling in a future session: a stable preference, a
project constraint, a decision and its rationale, a pointer to an external resource. Do NOT store
what is recoverable from the code, the git history, or the current conversation alone.

## The loop

1. **Classify.** Pick the type from the fact, which sets the filename prefix:
   - `user`: who the person is (role, preferences, expertise).
   - `feedback`: guidance on how to work, a correction or a confirmed approach (include the why).
   - `project`: ongoing work, goals, or constraints not derivable from the code.
   - `reference`: a pointer to an external resource (URL, dashboard, ticket).

2. **Dedupe before writing.** Search the vault for a note that already covers this: grep the `name:`
   and `description:` lines of the topic files. If one exists, UPDATE it rather than create a
   near-duplicate. The auditor flags same-prefix clusters; do not create them on purpose.

3. **Draft the note** (per `docs/SCHEMA.md`):
   - Filename: `<type>_<short-kebab-slug>.md`.
   - Frontmatter: `name` (the slug, which is the wikilink target), `description` (the one sentence
     recall matches on, so write it as the query you would use to find this later), `metadata.type`.
     Add `metadata.enforcement` (`hook` / `pinned` / `recall`), `status`, or `revisit: YYYY-MM-DD`
     only when they apply.
   - Body: one fact. For `feedback` and `project`, follow with a `**Why:**` line and a
     `**How to apply:**` line so the memory is actionable, not merely true.
   - Cross-link: `[[other-note-name]]` to related notes. Link liberally. A link to a note you have
     not written yet is fine; it marks something worth capturing, and the auditor lists it until the
     file exists.

4. **Place it in the index, or don't.** `MEMORY.md` is a bounded hot-set, not a registry. Add a
   one-line pointer only if the note earns always-loaded status (an always-on rule, or the current
   working set). Everything else stays recall-only: the file and its `description` are enough for
   recall to surface it. When in doubt, leave it out of the index.

5. **Confirm, then write.** Show the drafted note (and any index line) and wait for approval before
   writing to disk. This is a save, not a send, but never write silently.

6. **Audit.** After writing, run `python3 memory-reindex.py` (add `--dir <vault>` for a non-default
   vault). Clear anything it flags: a dangling `[[link]]` you just introduced, an over-length index
   line, a budget overflow.

## Guardrails

- One fact per file. If a note wants to be two facts, it is two files.
- Update over duplicate. Delete a note that turns out to be wrong.
- The `description` is the most important line; recall lives or dies by it.
- Keep the index small. Prefer eviction (the note stays, recall still finds it) over letting
  `MEMORY.md` grow past its budget.
- Never write without showing the draft first.
