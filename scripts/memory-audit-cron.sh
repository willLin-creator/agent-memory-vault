#!/bin/bash
# Periodic vault health check. Point cron / launchd / systemd at this on whatever cadence
# fits your vault's churn (monthly is plenty for a slow-growing personal vault).
#
# It runs the deterministic auditor and appends the report to a log. When action is
# recommended (over budget / dangling link / stale entry), it writes a loud ACTION-NEEDED
# banner, so a glance at the log tail tells you whether the vault needs a 30-second review.
#
# Config (env):
#   AGENT_MEMORY_DIR   vault to audit (else the auditor's bundled example-vault)
#   AGENT_MEMORY_LOG   log file (default ~/.agent-memory-audit.log)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${AGENT_MEMORY_LOG:-$HOME/.agent-memory-audit.log}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
{
  echo ""
  echo "########## memory audit $STAMP ##########"
  python3 "$HERE/memory-reindex.py"
  rc=$?
  if [ "$rc" -eq 1 ]; then
    echo ">>> ACTION NEEDED: run  python3 $HERE/memory-reindex.py  and clear the punch-list above."
  else
    echo ">>> healthy, no action."
  fi
} >> "$LOG" 2>&1
