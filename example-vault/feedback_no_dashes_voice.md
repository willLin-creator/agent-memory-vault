---
name: feedback_no_dashes_voice
description: Never use dashes as connectors in written output; use clean punctuation instead.
type: feedback
enforcement: hook
---

Do not use dashes as sentence connectors (no em dash, no en dash, no " -- " joining clauses).
Use a period, comma, colon, or parentheses, or split into two short sentences.

**Why:** Dash-connected clauses read as generated default prose, not as the user's voice.

**How to apply:** This is a hook-enforced rule (the strictest tier). It composes with
[[feedback_prefers_tight_writing]] and serves the same low-friction goal as
[[project_second_brain_launch]].

NOTE (frontmatter placement): this file declares `type` and `enforcement` at the TOP level
rather than under `metadata:`. The auditor coalesces both placements, so `--views` still
groups it correctly. That is intentional here, to demonstrate the tolerance.
