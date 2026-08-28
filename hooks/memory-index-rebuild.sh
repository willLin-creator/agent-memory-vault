#!/bin/bash
# PostToolUse(Edit|Write): regenerate the MEMORY.md pointer block whenever a memory file is
# written, so nobody has to remember to add a pointer.
#
# Why this exists: a hand-maintained index only gets a pointer for a new memory if whoever wrote
# it remembered to add one. In the vault this was extracted from, 31% of memories had no pointer
# as a result. Now the pointer block is generated from each memory's own `cluster:` / `hook:`
# frontmatter (memory-index.py), and this hook runs the generator on every write.
#
# No loop risk: the generator writes MEMORY.md directly with Python, which does not pass through
# the agent's Write/Edit tool, so it cannot re-trigger this hook.
#
# Fails open: a broken generator must never block a memory write. Does nothing unless
# AGENT_MEMORY_DIR is set and the written file lives inside it.
#
# Wire it (Claude Code settings.json):
#   {"matcher": "Edit|Write", "hooks": [{"type": "command",
#     "command": "AGENT_MEMORY_DIR=/abs/vault bash /abs/agent-memory-vault/hooks/memory-index-rebuild.sh"}]}
set -u
[ -n "${AGENT_MEMORY_DIR:-}" ] || exit 0
[ -d "$AGENT_MEMORY_DIR" ] || exit 0
VAULT="$(cd "$AGENT_MEMORY_DIR" && pwd -P)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
GEN="$HERE/memory-index.py"
[ -f "$GEN" ] || exit 0

f=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)
[ -n "$f" ] || exit 0
[ -f "$f" ] || exit 0
case "$f" in *.md) ;; *) exit 0 ;; esac
fdir="$(cd "$(dirname "$f")" 2>/dev/null && pwd -P)"
[ "$fdir" = "$VAULT" ] || exit 0

case "$(basename "$f")" in
  MEMORY.md)
    # The index itself was hand-edited. Do not rebuild (that would clobber a deliberate resident
    # edit mid-write); report whether the generated block is now stale.
    out=$(AGENT_MEMORY_DIR="$VAULT" python3 "$GEN" --check --quiet 2>&1)
    if [ -n "$out" ]; then
      printf '{"systemMessage":%s}\n' "$(printf '%s' "MEMORY.md: $out" | jq -Rs .)"
    fi
    ;;
  *)
    out=$(AGENT_MEMORY_DIR="$VAULT" python3 "$GEN" build --quiet 2>&1)
    rc=$?
    if [ $rc -ne 0 ] || [ -n "$out" ]; then
      printf '{"systemMessage":%s}\n' "$(printf '%s' "memory index: ${out:-rebuilt}" | jq -Rs .)"
    fi
    ;;
esac
exit 0
