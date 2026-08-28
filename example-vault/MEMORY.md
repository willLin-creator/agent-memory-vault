# Memory

<!-- SCALING RULE: this index is a BOUNDED HOT-SET, not a complete registry. Two regions:
(1) the hand-written RESIDENT block below, for rules that must fire unprompted and whose
reasoning is the payload; keep it small, it competes for attention every session.
(2) the GENERATED pointer block, one dense line per cluster, rendered by memory-index.py from
each memory's `cluster:` / `hook:` frontmatter. Never hand-edit it: set the frontmatter and run
`memory-index.py build` (or wire hooks/memory-index-rebuild.sh). Coverage is 100% by
construction, and line count scales with clusters, not memories. The consumer's line limit
(default 200, silently truncated) is the binding constraint, not bytes. -->

<!-- reindex:prose-start -->
## Always-on hard rules (never evict)
- No dashes as connectors in written output; use clean punctuation instead (`feedback_no_dashes_voice.md`, enforcement: hook).
- Never send an outbound message without explicit approval (`feedback_verify_before_send.md`, enforcement: pinned).
<!-- reindex:prose-end -->

## Pointers (generated)

<!-- BEGIN GENERATED POINTERS. Do not hand-edit: run memory-index.py build. -->

**Design notes.** `reference_orphan_note.md` a graph orphan on purpose · `reference_recall_design.md` why the index stays small

**Projects.** `project_second_brain_launch.md` the vault's own build

**Voice.** `feedback_prefers_tight_writing.md` short sentences, no hedges

<!-- END GENERATED POINTERS -->
