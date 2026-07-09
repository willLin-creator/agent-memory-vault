# Memory

<!-- SCALING RULE: this index is a BOUNDED HOT-SET, not a complete registry. Completeness
lives in the topic files; recall surfaces them by their `description:` frontmatter even
when NOT listed here. Keep this file small (default budget 18KB, enforced by
memory-reindex.py). Every entry = ONE line: slug + relevance hook only; detail goes in the
topic file. When over budget, evict the lowest-value lines (the topic file and its
description stay, so recall still finds them). Always-on hard rules stay listed. -->

## Always-on hard rules (never evict)
- No dashes as connectors in written output; use clean punctuation instead (`feedback_no_dashes_voice.md`, enforcement: hook).
- Never send an outbound message without explicit approval (`feedback_verify_before_send.md`, enforcement: pinned).

## Writing voice
- Prefer tight writing: short sentences, cut hedges, structure over prose (`feedback_prefers_tight_writing.md`).

## Active project
- The second-brain launch: bounded hot-set index, recall-by-description, graph auditing (`project_second_brain_launch.md`).

## Reference
- How recall works and why the index stays small (`reference_recall_design.md`).
