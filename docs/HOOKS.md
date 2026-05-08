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

1. **cwd-ancestor walk** — climb from the current working directory up
   through its parents; if any ancestor `D` is a direct child of the
   projects root and contains `active_run.json`, treat `D.name` as the
   project slug.
2. **projects-root scan** — if no ancestor matched, iterate the projects
   root (`$ARTAGENTS_PROJECTS_ROOT`, default
   `~/Documents/reigh-workspace/astrid-projects/`) and pick every
   subdirectory whose name is a valid project slug and that contains an
   `active_run.json`.

For each discovered slug (sorted), the hook re-prints `astrid next`
output (the prohibition preamble plus the current step) so Claude Code
re-injects it into the next turn. If no slugs are discovered the hook exits
silently with status 0 — your normal Claude Code sessions are unaffected.

The hook does **not** require Claude's cwd to be the project state directory.
The projects-root scan means it works from any cwd, including a sibling repo
checkout where you actually edit code.
