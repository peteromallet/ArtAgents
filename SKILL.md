---
name: "artagents"
description: "Use for the ArtAgents repo: a file-based toolkit for agents to make art and creative work alongside a human. Video edits, generative timelines, image/audio/video understanding and generation — all behind one CLI gateway."
---

# ArtAgents

A file-based toolkit for agents to make art and creative work alongside a human.

Three kinds of beings live here:

- **Executors** — perform one piece of work
- **Orchestrators** — combine executors together
- **Elements** — reusable render pieces used by both

Every summons passes through one gate: `python3 -m artagents`.

## Using tools

Find an id:

```bash
python3 -m artagents [executors|orchestrators|elements] list
```

Inspect to see inputs, outputs, and intent:

```bash
python3 -m artagents [executors|orchestrators|elements] inspect <id>
```

Run it:

```bash
python3 -m artagents [executors|orchestrators] run <id> -- <args>
```

Each tool has its own `SKILL.md` next to its `run.py`. That is the source of truth for the tool — read it before invoking.

## Forge a new tool

Copy from `docs/templates/[executor|orchestrator|element]/`, then read `docs/creating-tools.md`.

## Rules that aren't in `inspect`

- Generated files live under `runs/` and stay out of git.
- Don't print or hardcode API keys; use `--env-file` or nearby `.env` files.
- Preserve local edits in curated tool skill files such as `artagents/executors/moirae/SKILL.md` and `artagents/executors/vibecomfy/SKILL.md` unless asked to edit them.
- Orchestrators may call declared child orchestrators; executors must not call orchestrators.
- Element resolution order: active theme → `.artagents/elements/overrides` → `.artagents/elements/managed` → `artagents/elements/bundled`.
- After adding or renaming effects, animations, transitions, or theme elements:

  ```bash
  python3 scripts/gen_effect_registry.py
  cd remotion && npm run gen-types
  ```

- `python3 -m artagents setup` is dry-run by default; only run `--apply` when the user wants local element sync.

## Upstream friction

When a workflow is awkward, brittle, or undocumented, tell the user directly. Suggest the smallest durable fix; if the issue belongs upstream, recommend a PR there.

## Begin

Ask the maker what they want to make or learn. If they want ideas, see `docs/ideas.md`.
