# ArtAgents

![ArtAgents architecture: orchestrators route work to executors and render elements](docs/assets/artagents-orchestration.png)

ArtAgents is a file-based toolkit for producing Reigh-compatible video edits,
event-talk renders, generative timelines, and image/video assets.

The public model has three canonical concepts:

- **Orchestrators** coordinate workflows.
- **Executors** run concrete work.
- **Elements** are render/custom building blocks such as effects, animations, and transitions.

Use canonical commands for new work.

`python3 -m artagents` is the executable package gateway and single command gateway.
Use it to discover, inspect, validate, install, and run every
orchestrator, executor, and element. `python3 pipeline.py` remains a
compatibility launcher, and the `bin/*.py` scripts are thin direct launchers for
specialized/manual use.

## Agent Prompt

Copy this into a coding agent:

```text
Use the ArtAgents repo:
https://github.com/banodoco/ArtAgents

First read AGENTS.md, README.md, and SKILL.md, then run:
git status --short
python3 pipeline.py doctor

Use canonical terms and commands: orchestrators, executors, and elements.

Keep generated files under runs/ unless the task explicitly touches generated
Remotion registries. Do not commit secrets or media. Before editing, check for
dirty user files and do not overwrite unrelated changes.
```

## First Commands

Run these from the repository root before making changes:

```bash
python3 pipeline.py --help
python3 -m artagents --help
git status --short
python3 pipeline.py doctor
python3 pipeline.py orchestrators list
python3 pipeline.py executors list
python3 pipeline.py elements list
python3 pipeline.py setup
```

`setup` is dry-run by default. It reports the managed default element sync and
local dependency-install plan without mutating the workspace. Use
`python3 pipeline.py setup --apply` only when you intend to materialize defaults
and run local element install helpers.

## Quick Start

```bash
# Source-video hype cut
python3 pipeline.py --video source.mp4 --brief brief.txt --out runs/example --render

# Audio-backed timeline
python3 pipeline.py --audio rant.wav --brief brief.txt --out runs/audio --render

# Pure-generative timeline
python3 pipeline.py --brief brief.txt --theme 2rp --out runs/generative --render --target-duration 28

# Pure-generative sample brief
python3 pipeline.py --brief examples/briefs/cinematic.txt --out runs/cinematic --render --target-duration 15

# Event-talk render
python3 bin/event_talks.py render --manifest runs/event/talks.json --out-dir runs/event/rendered
```

Generated outputs belong under `runs/`. That directory is ignored by git and can
contain frames, JSON files, audits, and rendered videos from local experiments.

## Discovery

```bash
python3 pipeline.py orchestrators list
python3 pipeline.py orchestrators inspect builtin.hype --json
python3 pipeline.py executors list
python3 pipeline.py executors inspect builtin.render --json
python3 pipeline.py elements list
python3 pipeline.py elements inspect effects text-card --json
```

Use these JSON commands as the runtime index for agents. The registry output
includes each folder-backed orchestrator or executor root and its `skill_file`,
so agents should load only the entrypoint repo skill plus the specific
folder-level `SKILL.md` needed for the task. Do not merge every executor and
orchestrator skill into one large runtime prompt.

Runnable implementations have exactly one public folder format:
`artagents/orchestrators/<slug>/{orchestrator.yaml,SKILL.md,run.py}` for
orchestrators and `artagents/executors/<slug>/{executor.yaml,SKILL.md,run.py}`
for executors, with optional local `src/` modules. Top-level `artagents/*.py`
files are shared libraries or system commands, not alternate runnable
implementations.

When ArtAgents is missing a reusable capability, use `docs/creating-tools.md`
before adding files. Create an executor for one concrete unit of work, an
orchestrator for a workflow, and an element for a reusable render building
block. Copy from `docs/templates/executor/`, `docs/templates/orchestrator/`, or
`docs/templates/element/` so new public tools keep the expected shape.

Default orchestrators include `builtin.hype`, `builtin.event_talks`,
`builtin.thumbnail_maker`, and `builtin.understand`. Default executors include the built-in pipeline
stages such as `builtin.transcribe`, `builtin.cut`, `builtin.render`, and
`builtin.validate`, plus external executors such as `external.moirae` and
`external.vibecomfy.run`. VibeComfy is an executor only,
not an orchestrator.

Default elements are bundled in this repository and can be synced into
`.artagents/elements/managed`. User-editable forks and overrides live under
`.artagents/elements/overrides`:

```bash
python3 pipeline.py elements sync --dry-run
python3 pipeline.py elements fork effects text-card
python3 pipeline.py elements install effects text-card
python3 pipeline.py elements update --dry-run
```

Element source priority is active theme, then `.artagents/elements/overrides`,
then `.artagents/elements/managed`, then bundled defaults in
`artagents/elements/bundled`.

## Main Commands

```bash
# Rerun a pipeline from a specific stage
python3 pipeline.py --video source.mp4 --brief brief.txt --out runs/example --from cut --render

# Audit a run
python3 pipeline.py audit --run runs/example
python3 pipeline.py audit --run runs/example --json

# Fetch canonical Reigh data through the app Edge Function
python3 pipeline.py reigh-data --project-id <PROJECT_UUID> --shot-id <SHOT_UUID> --out runs/reigh/shot.json

# Render a Reigh-compatible timeline/assets pair
python3 bin/render_remotion.py \
  --timeline runs/example/briefs/my-brief/hype.timeline.json \
  --assets runs/example/briefs/my-brief/hype.assets.json \
  --out runs/example/briefs/my-brief/render.mp4
```

## Repo Map

```text
artagents/                 Python implementation
artagents/orchestrators/   Canonical orchestrator folders, registry, runner, and CLI
artagents/executors/       Canonical executor folders, registry, runner, and CLI
artagents/elements/        Element schema, registry, CLI, and bundled defaults
.artagents/elements/       Local managed defaults and user overrides
bin/                       Direct launchers backed by canonical executor and orchestrator folders
agents/                    Agent configuration
remotion/                  Remotion renderer project
scripts/                   Development and code-generation scripts
docs/                      Architecture notes, creation guide, and templates
examples/                  Schema fixtures and committed sample briefs under examples/briefs/
_reference/                Copied Reigh contract references
runs/                      Ignored local outputs
```

`python3 -m artagents` is the package entry point. `pipeline.py` remains a
compatibility launcher, and `bin/*.py` launchers call the matching canonical
executor or orchestrator modules when you need a single stage directly.
`python3 pipeline.py doctor` also validates the canonical repo structure: public
executor folders must contain `executor.yaml`, `run.py`, and `SKILL.md`; public
orchestrator folders must contain `orchestrator.yaml`, `run.py`, and `SKILL.md`;
legacy public packages such as conductor/performer folders are rejected.

## Outputs

The main pipeline writes source-level artifacts into the run directory and
brief-level artifacts under `briefs/<slug>/`:

```text
runs/example/
  transcript.json
  scenes.json
  shots.json
  pool.json
  audit/
  briefs/
    my-brief/
      arrangement.json
      hype.timeline.json
      hype.assets.json
      hype.metadata.json
      hype.mp4
      validation.json
```

## Generated Files

Normal generated media, frames, intermediate JSON, and local reports belong
under `runs/` or another ignored output directory. Do not commit secrets, large
source media, rendered videos, or local dependency environments.

Generated Remotion registry files are source artifacts when element code
changes. Keep generated siblings synchronized across `.ts`, `.js`, `.d.ts`, and
`.map` outputs in `remotion/src`, and scan for stale element aliases after
regeneration:

```bash
python3 scripts/gen_effect_registry.py
rg "@workspace-|workspace-effects|workspace-animations|workspace-transitions" remotion/src scripts remotion -n
```

## Development

```bash
python3 -m pip install -r requirements.txt
pytest

cd remotion
npm run typecheck
npm run smoke
npm run gen-types
```

Run `npm run gen-types` after effect, animation, transition, or theme element
changes. Local secrets belong in `.env`, `.env.*`, or `this.env`; these are
ignored by git.

## Dirty-File Caution

Always inspect `git status --short` before editing. This repository often has
active generated artifacts and local skill edits. In particular, do not overwrite
unrelated changes in curated executor skill files such as
`artagents/executors/moirae/SKILL.md` or
`artagents/executors/vibecomfy/SKILL.md`.

## License

Open Source Native License (OSNL) v0.2. See `LICENSE` for the full terms.
