# Creating Tools

Use this guide when ArtAgents is missing a capability.

## Operating Level

Start with the highest-level command that fits the user request. For normal
video creation, run an orchestrator through `python3 -m artagents` instead of
chaining internal executors by hand.

Do not chain pipeline internals by hand unless you are debugging one specific
stage. Source-analysis executors intentionally pass file artifacts such as
transcripts, scenes, quote candidates, pools, timelines, and assets. Those files
make runs resumable and auditable, but they are not the right interface for a
creative request like "make a video about AI". Use the hype orchestrator or add
a new orchestrator for that workflow.

Current start points:

```bash
# Source-backed edit
python3 -m artagents --video source.mp4 --brief brief.txt --out runs/example --render

# Audio-backed edit
python3 -m artagents --audio voiceover.wav --brief brief.txt --out runs/audio --render

# Pure-generative edit from an existing brief
python3 -m artagents --brief examples/briefs/cinematic.txt --out runs/generative --render --target-duration 15
```

If the user gives a topic instead of a brief, create or use a brief-generation
executor, then coordinate it from an orchestrator. Do not fake source media just
to satisfy a source-video path.

## Build Order

Before adding anything, follow this order. Move to the next step only when the
previous one cannot satisfy the request.

1. **Try to compose existing executors.** Run `python3 -m artagents executors
   list` and `inspect` the likely candidates. If a workflow can be built by
   wiring existing executors together, write *only* an orchestrator that calls
   them. Do not duplicate logic that already lives in an executor.
2. **Create the missing executors.** Each new executor must do exactly one
   concrete unit of work — independently runnable, inspectable, testable. Keep
   it narrow: one network call, one transformation, one artifact in / one
   artifact out. Workflow shape, retries-across-stages, and conditional
   branching belong in the orchestrator, not the executor.
3. **Write the orchestrator that composes them.** It calls the executors
   (existing + new) and may call other orchestrators. Executors must not call
   orchestrators.

Anti-pattern: a single orchestrator `run.py` that opens HTTP sockets, parses
model output, downloads files, and assembles grids — all inline. That is three
or four executors hiding in a trench coat. Split them out so each piece is
discoverable, reusable, and individually testable.

## Decision Rule

Create an **executor** when the missing capability performs one concrete unit of
work. It should be independently runnable, inspectable, and testable. Examples:
fetch Reigh data, render a timeline, upload a video, inspect audio, build a
sprite sheet, generate a brief from a topic, or transform one artifact into
another.

Create an **orchestrator** when the missing capability coordinates a workflow.
It should call or plan child executors/orchestrators and keep business flow out
of individual tool implementations. Examples: hype pipeline, event-talk
workflow, thumbnail workflow, topic-to-video creation, or an understanding
dispatcher.

Create an **element** when the missing capability is a reusable render building
block consumed by timeline JSON. Effects, animations, and transitions are
elements. If the user needs an editable visual primitive, fork or create an
element instead of hard-coding behavior in an executor.

Create a **shared library** only when the code has no public runtime of its own.
Shared hype/editing concepts belong under `artagents/domains/hype`. Generic
plumbing belongs under `artagents/utilities`. Executor-specific helpers belong
inside that executor's optional `src/` package.

For a one-off experiment, keep outputs and scratch files under `runs/`. Do not
create a public executor, orchestrator, or element unless the behavior should be
discoverable and reusable.

## Common Friction Points

**Too many required file paths.** This is expected for low-level executors.
Those paths are the artifact contract. Solve it by using an orchestrator, adding
a small helper executor for the missing artifact, or adding an orchestrator that
owns the whole flow. Only add literal/stdin conveniences when direct executor
use is itself the product surface.

**Pool building rejects abstract or dialogue-light sources.** The source-video
hype path expects usable visual and dialogue candidates. If the goal is
abstract or purely generative, use the pure-generative path. If source-backed
abstract editing should be reusable, add an explicit orchestrator mode or a
focused executor change with tests rather than hand-editing triage and quote
JSON to force a pool.

**No brief file exists.** Briefs are first-class input artifacts today. Use
`examples/briefs/` as samples. If the user repeatedly asks from a topic, add a
`builtin.generate_brief` executor and call it from a topic-to-video
orchestrator.

**Render is missing assets.** Rendering consumes the timeline and assets pair
created by cut. Do not skip cut unless both `hype.timeline.json` and
`hype.assets.json` already exist for that brief.

**No one-command topic creation.** The current one-command path starts from a
brief file. A topic-only command should be an orchestrator that provisions the
brief and then delegates to the existing hype or render flow.

## Required Formats

Executor folders use:

```text
artagents/executors/<slug>/
  executor.yaml
  run.py
  STAGE.md
  src/              optional private helper package
```

Orchestrator folders use:

```text
artagents/orchestrators/<slug>/
  orchestrator.yaml
  run.py
  STAGE.md
  src/              optional private helper package
```

Element folders use:

```text
artagents/elements/bundled/<kind>/<id>/
  component.tsx
  schema.json
  defaults.json
  meta.json
```

User-editable forks go under `.artagents/elements/overrides/<kind>/<id>/` and
should be created with:

```bash
python3 -m artagents elements fork effects text-card
```

## Templates

Copy the closest template and replace the placeholder identifiers:

- `docs/templates/executor/`
- `docs/templates/orchestrator/`
- `docs/templates/element/`

Then run:

```bash
python3 -m artagents doctor
python3 -m artagents executors inspect builtin.example --json
python3 -m artagents orchestrators inspect builtin.example --json
python3 -m artagents elements inspect effects example-card --json
```

Run only the inspect command that matches the thing you created.

## Review Checklist

- The new capability is reachable through `python3 -m artagents`.
- The folder has the required manifest, `run.py`, and `STAGE.md` or element
  files.
- The `STAGE.md` says when to use it and gives the canonical command.
- Inputs, outputs, cache behavior, isolation, dependencies, and network use are
  declared in metadata.
- Runtime outputs go under `runs/` or another ignored directory.
- Focused tests cover registry discovery and the behavior that can break.
