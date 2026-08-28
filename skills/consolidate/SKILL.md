---
name: consolidate
description: The periodic maintenance pass for the memory vault. Run the deterministic auditor for candidates, judge each one (merge, delete, demote, fix), propose one plan, apply only what the user approves, re-audit. The Consolidate step of Write / Consolidate / Recall / Apply.
---

# /consolidate: memory consolidation pass

## What this is

The Consolidate step of the memory loop (Write / Consolidate / Recall / Apply). Write is how a
note gets in (`/remember`). Recall surfaces notes by description. This is the maintenance step
that keeps the vault from rotting: review the notes, merge duplicates into denser files, delete
the ones that turned out wrong, demote the ones that have gone cold, and fix structural rot
(dangling links, orphans, oversize index lines, missing descriptions, a stale generated block).

The lesson this exists to enforce: a memory system that only ever adds is not a memory system, it
is a log. Consolidation is the step nobody does, because it has no natural trigger. The trigger
is the scheduled audit (`scripts/memory-audit-cron.sh`), which nudges via its log; this skill is
the pass itself.

**Every mutation is human-gated.** The auditor detects; the agent judges; the user approves; only
then does anything change. Nothing is merged, deleted, or demoted without explicit approval,
because losing a real memory is worse than carrying a stale one.

## Usage

- `/consolidate`: full pass. Audit, propose, apply on approval, re-audit.
- `/consolidate dry`: audit and propose only; make no changes even if approved.

## Step 1: detect (deterministic)

Run both tools for the candidate list. Do not eyeball the vault.

```
AGENT_MEMORY_DIR=/path/to/vault python3 memory-reindex.py --json     # structure, links, coldness
AGENT_MEMORY_DIR=/path/to/vault python3 memory-index.py --check      # coverage, line limit, staleness
```

The auditor returns `duplicate_clusters`, `stale_candidates`, `cold_candidates`, `graph_orphans`,
`dangling_wikilinks`, `oversize_lines`, `missing_description`, `hubs`, and budget state. The
generator check reports whether the pointer block is stale, whether the index is over the line
limit its consumer enforces, and any memory with no readable `cluster:`. This is detection only.
The tools cannot tell whether two notes *say* the same thing or whether a lesson is *wrong*; that
is the judgment this pass adds.

## Step 2: judge (read the flagged files, decide the action)

For each candidate, read the actual file(s) and classify into one action. Hold the delete-vs-demote
distinction firmly:

| Action | When | What happens |
|---|---|---|
| **Merge** | two or more notes cover the same underlying lesson | combine into the single most accurate, most current file; re-point inbound `[[links]]`; delete the merged-away files |
| **Delete** | the note is WRONG, superseded, or outdated | remove the file entirely (not archived): a wrong lesson recalled later is worse than no lesson |
| **Demote** | the note is still TRUE but cold or orphaned (unused, no longer working-set) | if it sits in the hand-written resident block, drop it from there (the generator re-lists it as a plain pointer); if it is already only a generated pointer, move the file to `<vault>/archive/` so it leaves the index and default recall but is never lost |
| **Fix** | structural rot | add a missing `description:`, set a missing `cluster:`, trim an oversize resident line (move detail into the file), link an orphan into a hub, split an over-referenced hub, or rebuild a stale generated block |

Rules:

- Delete is for WRONG. Demote is for UNUSED-but-true. Never delete a still-true memory because it
  is cold; that is what demotion is for.
- `pinned` and `hook` enforcement notes are never demoted or deleted by this pass. The always-on
  hard rules stay.
- When merging, preserve every distinct fact and the strongest evidence; a merge that drops a
  nuance is a lossy delete in disguise.
- Prefer the smallest change that resolves the candidate.
- A note whose content outgrew its `description:` is invisible to both tools (it is structurally
  healthy). The write path (`/remember`, or a capture skill) is the only place that drift gets
  caught, at the moment it is created. This pass cannot find it; do not claim it did.

## Step 3: propose (one plan, for approval)

Present the full plan grouped by action, each line with the file(s) and a one-line why:

```
CONSOLIDATION PLAN: [N] proposed changes

MERGE ([n])
- keep `a.md`  <-  merge+delete `b.md`, `c.md`   | same lesson: [one line]

DELETE ([n])
- `x.md`   | wrong/superseded: [one line]

DEMOTE (out of the resident block, or to archive/) ([n])
- `y.md`   | cold/orphan, still true: [one line]

FIX ([n])
- `z.md`   | add description / set cluster / link orphan / rebuild block: [one line]

Approve? [all] / [numbers to apply] / [edit] / [cancel]
```

Never apply without explicit approval. `/consolidate dry` stops here regardless of the answer.

## Step 4: apply (only what was approved)

- **Merge:** write the consolidated file, update inbound `[[links]]` and any resident pointer,
  delete the merged-away files.
- **Delete:** remove the file; remove any resident pointer; note (do not auto-fix) any now-dangling
  `[[links]]` for a follow-up.
- **Demote:** remove the resident line, or move the file to `archive/`. Never edit the generated
  block by hand.
- **Fix:** the surgical edit.
- Then `python3 memory-index.py build` so the generated block reflects the new state.

## Step 5: confirm and re-audit

Re-run both tools and report the delta: candidate counts before vs after, index lines and bytes
before vs after, and anything intentionally left (with why). Close with a one-line summary.

## Guardrails

1. **Human-gated.** Detection is automatic; mutation never is. Show the plan, wait for approval.
2. **Delete only what is wrong.** Cold-but-true is a demotion, not a deletion.
3. **Protect the pinned tier.** Always-on hard rules and `hook` / `pinned` notes are out of scope.
4. **Merges are lossless.** Carry every distinct fact forward, or it is not a merge.
5. **Re-point, don't orphan.** A merge or delete that leaves dangling `[[links]]` is not done.
6. **Never hand-edit the generated block.** Set the frontmatter and rebuild.
