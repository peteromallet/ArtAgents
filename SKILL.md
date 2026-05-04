---
name: "artagents"
description: "Use for the ArtAgents repo: a file-based toolkit for agents to make art and creative work alongside a human. Video edits, generative timelines, image/audio/video understanding and generation — all behind one CLI gateway."
---

# ArtAgents

A file-based toolkit for agents to make art and creative work alongside a human.

Three kinds of beings live here:

- **Executors** — run one concrete unit of work
- **Orchestrators** — coordinate executors (and other orchestrators) into workflows
- **Elements** — reusable render building blocks (effects, animations, transitions)

`python3 -m artagents` is the executable package gateway. Every summons passes through this one gate.

## First commands

Run from the repository root:

```bash
git status --short
python3 -m artagents --help
python3 -m artagents doctor
python3 -m artagents orchestrators list
python3 -m artagents executors list
python3 -m artagents elements list
python3 -m artagents setup
```

`setup` is dry-run by default; pass `--apply` to mutate.

## Using tools

Find an id:

```bash
python3 -m artagents [executors|orchestrators|elements] list
```

Inspect to see inputs, outputs, and intent:

```bash
python3 -m artagents [executors|orchestrators|elements] inspect <id> --json
```

Run it:

```bash
python3 -m artagents [executors|orchestrators] run <id> -- <args>
```

Each tool has its own `STAGE.md` next to its `run.py`. That is the source of truth — read it before invoking. The JSON inspect output points at the folder root and `stage_file`; load only the one relevant `STAGE.md`, not all of them.

At the start of any session that will produce runs, run python3 -m artagents thread show @active first. The [thread] prefix on every command output is your continuous indicator; if it shows the wrong thread, run thread new or pass --thread @new to your next command. Selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers.

Before rendering an iteration video, run `python3 -m artagents.packs.builtin.iteration_video.run inspect <thread>` to see modalities, renderers, quality, cache counts, and estimated cost without rendering.

## Make something new

Read `docs/creating-tools.md`, then follow this build order — every step before falling back to the next:

1. **Compose existing executors first.** `python3 -m artagents executors list` and `inspect` the candidates. If existing executors can be wired together to do the job, build only an orchestrator that calls them.
2. **Create the missing executors next.** Each new executor must do *one* concrete, focused unit of work — independently runnable, inspectable, and testable. Don't pack workflow logic into an executor; that belongs in an orchestrator.
3. **Then write the orchestrator.** It composes the executors (existing + newly created) into the workflow. Orchestrators may call other orchestrators; executors must not.

Skipping step 1 to write a god-orchestrator that bakes in network calls and business logic is the anti-pattern. Suspect it whenever a `run.py` grows past a couple of hundred lines without delegating to executors.

Templates:

- `docs/templates/executor/` — one concrete unit of work
- `docs/templates/orchestrator/` — a workflow that combines executors
- `docs/templates/element/` — a reusable render building block

Public folders have exactly one format: `artagents/orchestrators/<slug>/{orchestrator.yaml,STAGE.md,run.py}` and `artagents/packs/<pack>/<slug>/{executor.yaml,STAGE.md,run.py}`, with optional local `src/` modules. Top-level `artagents/*.py` files are shared libraries or system commands, not alternate runnable implementations.

Do not chain pipeline internals by hand unless you are debugging one specific stage. If the user gives a topic instead of a brief, use a brief-generation executor coordinated by an orchestrator — don't fake source media just to enter a source-video path. Render requires the `hype.timeline.json` and `hype.assets.json` pair produced by cut; don't skip cut unless both files already exist.

## Defaults

Built-in orchestrators: `builtin.hype`, `builtin.event_talks`, `builtin.thumbnail_maker`.

Built-in executors include `builtin.transcribe`, `builtin.cut`, `builtin.render`, `builtin.validate`, `builtin.understand` (audio/visual/video dispatcher; pass `--mode {audio,visual,video}`), `builtin.generate_image` (with a `saint-peter-of-banodoco` preset for the onboarding portrait), and the rest of the pipeline. External executors include `external.moirae` and `external.vibecomfy.run` (executor only, not an orchestrator).

Element source priority: active theme → `.artagents/elements/overrides` → `.artagents/elements/managed` → `artagents/elements/bundled`.

```bash
python3 -m artagents elements sync --dry-run
python3 -m artagents elements fork effects text-card
```

## Rules

- Generated files live under `runs/` (or another ignored output directory) and stay out of git. Don't commit source media, rendered videos, local dependency envs, or secrets.
- Don't print or hardcode API keys; use `--env-file` or nearby `.env` files.
- Treat curated tool stages as protected unless explicitly asked to edit them — notably `artagents/packs/external/moirae/STAGE.md` and `artagents/packs/external/vibecomfy/STAGE.md`.
- Orchestrators may call declared child orchestrators; executors must not call orchestrators.

After adding or renaming effects, animations, transitions, or theme elements:

```bash
python3 scripts/gen_effect_registry.py
cd remotion && npm run gen-types
```

## Validate

```bash
pytest tests/test_doctor_setup.py tests/test_canonical_cli.py
pytest --tb=no -q --no-header
```

## Upstream friction

When a workflow is awkward, brittle, or undocumented, tell the user directly. Suggest the smallest durable fix; if the issue belongs upstream, recommend a PR there.

## Begin

Ask the maker what they want to make or learn. If they want ideas, see `docs/ideas.md`.
