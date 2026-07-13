# Hooks

Integration glue between the vault and an agent runtime. Optional: the auditor and the
toucher work without any of this. Hooks are how you make usage tracking automatic instead of
a manual step.

## `recall-touch.py`: stamp a memory when recall reads it

The coldness signal (see `../docs/ARCHITECTURE.md`) weighs `last_accessed` and `access_count`.
Something has to write those at the moment a memory is used. In a Claude Code agent, using a
memory is physically a `Read` of its topic file, so this script hangs off the `Read` tool as a
PostToolUse hook and stamps whatever vault file was just read.

It is fail-open by design: it does nothing unless `AGENT_MEMORY_DIR` is set and the read file
lives inside it, it never touches the `MEMORY.md` index, and it always exits 0 so it can never
block or break the `Read` it observes.

### Wire it (Claude Code `.claude/settings.json`)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "AGENT_MEMORY_DIR=/absolute/path/to/vault python3 /absolute/path/to/agent-memory-vault/hooks/recall-touch.py"
          }
        ]
      }
    ]
  }
}
```

Use absolute paths. Point `AGENT_MEMORY_DIR` at the folder that holds your topic files, the
same value the auditor uses.

### What it captures, and what it does not

It records **active recall**: a memory the agent deliberately opened. It does not see the
passive session-start load of the index (`MEMORY.md`), because that is not a per-note event a
hook can observe. So `access_count` measures deliberate reuse, and a low count means "not
opened on its own in a while," not "never seen." Tune patience with `AGENT_MEMORY_COLD_DAYS`,
`AGENT_MEMORY_COLD_MAX_HITS`, and `AGENT_MEMORY_IMPORTANT_MIN` (see the architecture doc).

### Cost

The hook runs once per `Read`. The common path (a read outside the vault) is a JSON parse and
a prefix check, then it exits. It only loads the toucher and writes when a real vault file is
read, so the steady-state overhead on unrelated reads is a single short-lived process.
