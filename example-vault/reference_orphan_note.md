---
name: reference_orphan_note
description: A note that nothing links to and that links to nothing, a graph orphan on purpose.
metadata:
  type: reference
---

This note has no [[wikilinks]] out and nothing links to it, and it is intentionally left out of
MEMORY.md.

So the auditor reports it two ways:
- a GRAPH orphan (no links in or out, invisible to the wikilink graph), and
- an INDEX orphan (on disk but not referenced in the index, so recall-only).

Neither is an error. Both are signals: an orphan is a candidate to link into a hub, merge into a
related note, or evict. This file demonstrates that state so you can see it in the audit output.
