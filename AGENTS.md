# ArtAgents Agent Entry Point

Start here when an agent or contributor opens the repository.

## First Commands

Run from the repository root:

```bash
git status --short
python3 -m artagents doctor
python3 -m artagents orchestrators list
python3 -m artagents executors list
python3 -m artagents elements list
python3 -m artagents setup
```

`setup` is dry-run by default. It may plan managed element sync and local
element dependency commands, but it does not mutate the workspace unless
`--apply` is passed.

## Canonical Terms

- **Orchestrators** coordinate workflows.
- **Executors** run concrete work.
- **Elements** are render/custom building blocks such as effects, animations, and transitions.

## Entry Point Rule

Use `python3 -m artagents` as the executable package gateway for normal work.
Reach workflows through
`python3 -m artagents orchestrators ...`, concrete tools through
`python3 -m artagents executors ...`, and render building blocks through
`python3 -m artagents elements ...`. The `bin/*.py` files are thin direct
launchers for specialized/manual use; do not treat them as a separate public
API.

Use canonical imports and commands for new work:

```bash
python3 -m artagents --help
python3 -m artagents orchestrators inspect builtin.hype --json
python3 -m artagents executors inspect builtin.render --json
python3 -m artagents elements inspect effects text-card --json
```

Treat the JSON inspect/list output as the runtime index. It points to the
folder root and `skill_file` for folder-backed orchestrators and executors, so
load the ArtAgents entry point plus the one relevant folder-level `SKILL.md`;
do not concatenate all executor/orchestrator skills into one prompt.

Runnable implementations have exactly one public folder format:
`artagents/orchestrators/<slug>/{orchestrator.yaml,SKILL.md,run.py}` for
orchestrators and `artagents/executors/<slug>/{executor.yaml,SKILL.md,run.py}`
for executors, with optional local `src/` modules. Top-level `artagents/*.py`
files are shared libraries or system commands, not alternate runnable
implementations.

## Creating Missing Capabilities

Read `docs/creating-tools.md` before adding a reusable public capability.
Create an executor for one concrete unit of work, an orchestrator for a
workflow, and an element for a reusable render building block. Start from the
templates in `docs/templates/executor/`, `docs/templates/orchestrator/`, or
`docs/templates/element/`.

Do not chain pipeline internals by hand unless you are debugging one specific
stage. If the user gives a topic instead of a brief, add or use a
brief-generation executor and coordinate it from an orchestrator; do not fake
source media just to enter the source-video path. Render requires the
`hype.timeline.json` and `hype.assets.json` pair produced by cut, so do not
skip cut unless both files already exist.

## Defaults

Default orchestrators include `builtin.hype`, `builtin.event_talks`,
`builtin.thumbnail_maker`, and `builtin.understand`.

Default executors include the built-in pipeline stages such as
`builtin.transcribe`, `builtin.cut`, `builtin.render`, and `builtin.validate`,
plus external executors such as `external.moirae` and
`external.vibecomfy.run`. VibeComfy is an executor only,
not an orchestrator.

Default elements are bundled in `artagents/elements/bundled` and can be synced
into `.artagents/elements/managed`. User-editable forks and custom overrides go
under `.artagents/elements/overrides`:

```bash
python3 -m artagents elements sync --dry-run
python3 -m artagents elements fork effects text-card
python3 -m artagents elements update --dry-run
```

Element source priority is active theme, then `.artagents/elements/overrides`,
then `.artagents/elements/managed`, then bundled defaults.

`python3 -m artagents doctor` enforces canonical repository structure. Public
executor folders must include `executor.yaml`, `run.py`, and `SKILL.md`; public
orchestrator folders must include `orchestrator.yaml`, `run.py`, and
`SKILL.md`. Do not place executor metadata in orchestrator folders, or
orchestrator metadata in executor folders.

## Generated Files

Keep normal outputs under `runs/` or another ignored output directory. Do not
commit source media, rendered videos, local dependency environments, or secrets.

When changing element code, keep generated Remotion registry siblings in sync:

```bash
python3 scripts/gen_effect_registry.py
rg "@workspace-|workspace-effects|workspace-animations|workspace-transitions" remotion/src scripts remotion -n
```

Generated registry families include `.ts`, `.js`, `.d.ts`, and `.map` files in
`remotion/src`.

## Dirty-File Caution

Do not revert unrelated work. This repository often has active generated files
and local skill edits. In particular, treat these curated executor skill files
as protected unless the user explicitly asks to edit them:

- `artagents/executors/moirae/SKILL.md`
- `artagents/executors/vibecomfy/SKILL.md`

## Validation

Run focused tests for the files you changed, then run the full suite when the
batch requires it:

```bash
pytest tests/test_doctor_setup.py tests/test_canonical_cli.py
pytest --tb=no -q --no-header
```
