---
name: project_second_brain_launch
description: Building an agent second brain. Bounded hot-set index, recall-by-description, graph auditing.
metadata:
  type: project
  status: active
---

The active project: a file-based second brain for an agent. Three design commitments:

1. A bounded hot-set index (MEMORY.md) is the only thing loaded every session.
2. Everything else is recalled on demand by matching a topic file's `description:`.
3. A deterministic auditor keeps the graph and the index honest over time. See
   [[reference_recall_design]] for how recall and the budget interact.

DANGLING-LINK DEMO: the next link points at a memory that was never written, so the auditor
reports it as an actionable dangling [[wikilink]]: [[project_never_written]]. Delete this line
(or create that file) to clear the finding.
