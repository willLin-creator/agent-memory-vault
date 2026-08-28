#!/bin/bash
# Periodic vault health check. Point cron / launchd / systemd at this on whatever cadence fits your
# vault's churn (weekly is plenty for a personal vault).
#
# It runs two read-only checks and appends the report to a log:
#   1. memory-index.py --check   coverage, the consumer's LINE limit, and whether the generated
#                                pointer block is stale (skipped if the index has no markers)
#   2. memory-reindex.py         bytes, dangling links, orphans, hubs, stale and cold candidates
# When either recommends action it writes a loud banner pointing at the human-gated pass
# (skills/consolidate/). This is the calendar trigger for the Consolidate step: consolidation dies
# without one, so this is the one. Detection is deterministic and read-only. It NEVER mutates the
# vault; the merge/delete/demote is judgment work, run via /consolidate.
#
# Config (env):
#   AGENT_MEMORY_DIR   vault to audit (else the bundled example-vault)
#   AGENT_MEMORY_LOG   log file (default ~/.agent-memory-audit.log)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT="${AGENT_MEMORY_DIR:-$HERE/example-vault}"
LOG="${AGENT_MEMORY_LOG:-$HOME/.agent-memory-audit.log}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
{
  echo ""
  echo "########## memory audit $STAMP ##########"
  idx_rc=0
  if grep -q 'BEGIN GENERATED POINTERS' "$VAULT/MEMORY.md" 2>/dev/null; then
    # The auditor checks a BYTE budget and cannot see the consumer's LINE limit, past which the
    # index is silently truncated on load. The generator owns the line and coverage half, so run
    # it first and let its exit code count toward the banner.
    echo "--- index generator check (lines, coverage, staleness) ---"
    AGENT_MEMORY_DIR="$VAULT" python3 "$HERE/memory-index.py" --check
    idx_rc=$?
  fi
  echo "--- vault auditor (bytes, links, duplicates, coldness) ---"
  AGENT_MEMORY_DIR="$VAULT" python3 "$HERE/memory-reindex.py"
  rc=$?
  [ "$idx_rc" -ne 0 ] && rc=1
  if [ "$rc" -eq 1 ]; then
    echo ">>> CONSOLIDATE: candidates above. Run the human-gated pass in skills/consolidate/ (or clear the punch-list by hand)."
  else
    echo ">>> healthy, no consolidation needed."
  fi
} >> "$LOG" 2>&1
