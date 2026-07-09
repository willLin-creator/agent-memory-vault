---
name: reference_recall_design
description: How recall works. The index is a hot-set; topic files are surfaced by description.
metadata:
  type: reference
---

Recall is the mechanism that lets the hot-set index stay small without losing knowledge.

- The index (MEMORY.md) holds only always-on rules and the current working set.
- Every topic file carries a one-line `description:`. Recall matches a query against those
  descriptions and pulls in the relevant files, even ones not listed in the index.
- So "evicting" a line from the index does NOT lose the memory. The file and its description
  remain, and recall still finds them. This is why the auditor treats index orphans as
  recall-only rather than as errors. See the parent project: [[project_second_brain_launch]].

BENIGN FORWARD-REF DEMO: a link to a non-memory entity like a task id is allowed and reported
as benign, not actionable: [[task-42]].
