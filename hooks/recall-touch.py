#!/usr/bin/env python3
"""
recall-touch.py: a Claude Code PostToolUse hook that records a memory when recall reads it.

This is the piece that closes the coldness loop. The auditor reads usage signals
(`last_accessed`, `access_count`) and memory-touch.py writes them, but something has to call
the writer at the moment a memory is actually used. In a Claude Code agent, "recall" is
physically a `Read` of a topic file: the file's content is pulled into the model's context.
Wire this script as a PostToolUse hook on `Read` and every such recall stamps the file.

Contract (fail-open, do-nothing-by-default):
  - reads the hook payload as JSON on stdin (Claude Code passes tool_name + tool_input),
  - does nothing unless AGENT_MEMORY_DIR is set AND the read file lives inside it,
  - skips the index file (MEMORY.md) itself; it loads every session and is not a recall,
  - only touches Markdown files, and only ones that already have frontmatter,
  - ALWAYS exits 0. A memory hook must never block or fail the tool it observes.

It captures active recall (a file the agent chose to open), not the passive session-start
load of the index. That is the strongest usage signal a hook can see.

Wiring (in .claude/settings.json):

  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Read",
          "hooks": [
            {
              "type": "command",
              "command": "AGENT_MEMORY_DIR=/path/to/vault python3 /path/to/agent-memory-vault/hooks/recall-touch.py"
            }
          ]
        }
      ]
    }
  }
"""

import importlib.util
import json
import os
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent


def _load_toucher():
    spec = importlib.util.spec_from_file_location(
        "memory_touch", HERE.parent / "scripts" / "memory-touch.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def target_path(payload, vault_dir):
    """Return the vault file this recall should stamp, or None if it should be ignored.

    Kept pure (no I/O beyond path resolution) so it can be unit-tested directly."""
    if not vault_dir:
        return None
    if payload.get("tool_name") != "Read":
        return None
    fp = ((payload.get("tool_input") or {}).get("file_path") or "").strip()
    if not fp.endswith(".md") or os.path.basename(fp) == "MEMORY.md":
        return None
    try:
        vault = pathlib.Path(vault_dir).expanduser().resolve()
        target = pathlib.Path(fp).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if vault != target and vault not in target.parents:
        return None
    return str(target)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    target = target_path(payload, os.environ.get("AGENT_MEMORY_DIR"))
    if not target:
        return 0
    try:
        _load_toucher().touch_file(target, date.today().isoformat())
    except Exception:
        pass  # a memory hook must never break the tool it observes
    return 0


if __name__ == "__main__":
    sys.exit(main())
