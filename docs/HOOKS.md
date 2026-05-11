# Claude Code Stop hook — `astrid hook stop`

## Why

Long Claude Code sessions decay context: the prohibition preamble printed at
run start is gradually pushed out of the model's working context, and the
agent forgets the task-mode rules. SD-023 requires re-injecting the preamble
on every "stop" boundary so the rules stay live for the entire run. The
mechanism is a [Claude Code Stop hook](https://docs.claude.com/en/docs/claude-code/hooks)
that re-prints `astrid next` (preamble + current step) into the stream
Claude reads back on its next turn.

## Setup

Add the following snippet to your project's `.claude/settings.json` (create
the file if it does not exist). No matcher is needed — Stop hooks always fire
when Claude finishes a turn:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "astrid hook stop"
          }
        ]
      }
    ]
  }
}
```

## Behavior

`astrid hook stop` is a no-op unless an active run exists somewhere it can
discover. Discovery runs in two tiers:

1. **session-bound resolution** (Sprint 1) — if ``ASTRID_SESSION_ID`` is
   set and resolves to a session record whose ``project`` has a live
   ``current_run.json`` + ``lease.json`` pair, that's the active run.
2. **cwd-ancestor walk** — climb from the current working directory up
   through its parents; if any ancestor `D` is a direct child of the
   projects root and contains `current_run.json` (the Sprint 1
   replacement for the legacy `active_run.json`), treat `D.name` as the
   project slug. The legacy `active_run.json` filename is no longer
   written; Sprint 1's `scripts/migrations/sprint-1/migrate_active_run_to_current_run.py`
   converts on-disk state.
3. **(deferred)** the previous projects-root scan was retired in Sprint 1
   — it surprised users who happened to have unrelated projects with
   stale state. The session-bound + cwd-ancestor paths together cover
   every supported workflow.

For each discovered slug (sorted), the hook re-prints `astrid next`
output (the prohibition preamble plus the current step) so Claude Code
re-injects it into the next turn. If no slugs are discovered the hook exits
silently with status 0 — your normal Claude Code sessions are unaffected.

When the agent is running with `ASTRID_SESSION_ID` exported, the hook works
from any cwd because session-bound resolution wins regardless of working
directory. Without a session bound, the cwd-ancestor walk is the only
fallback — running from an unrelated repo checkout silently no-ops.
