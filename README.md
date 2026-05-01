# ArtAgents

ArtAgents is a file-based toolkit for producing Reigh-compatible video edits,
event-talk renders, generative timelines, and image/video assets.

The main implementation lives in the `artagents/` Python package. `pipeline.py`
is kept at the repository root as the primary entry point; lower-level tool
launchers live under `bin/`.

## Quick Start

Copy this into your coding agent when you want it to run ArtAgents for you:

```text
Use the ArtAgents repo. Read README.md and SKILL.md first, run git status --short, keep generated files under runs/, do not commit secrets or media, and run: python3 pipeline.py --brief brief.txt --out runs/example --render. While working, call out friction points, suggest fixes, and recommend PRs to the original upstream repos when the right fix belongs there rather than as a local workaround.
```

Create a source-video hype cut:

```bash
python3 pipeline.py --video source.mp4 --brief brief.txt --out runs/example --render
```

Create an audio-backed or pure-generative timeline:

```bash
python3 pipeline.py --audio rant.wav --brief brief.txt --out runs/audio --render
python3 pipeline.py --brief brief.txt --theme 2rp --out runs/generative --render --target-duration 28
```

Render an event-talk manifest:

```bash
python3 bin/event_talks.py render --manifest runs/event/talks.json --out-dir runs/event/rendered
```

Generated outputs belong under `runs/`. That directory is ignored by git and can
contain thousands of frames, JSON files, audits, and rendered videos from local
experiments.

## Repo Map

```text
artagents/                 Real Python implementation
artagents/performers/      Executable actions a conductor can call
artagents/conductors/      Workflow orchestration layer
reviewers/                 Focused audio/visual review helpers
remotion/                  Remotion renderer project
scripts/                   Development and code-generation scripts
bin/                       Compatibility launchers for direct tool commands
examples/                  Small Reigh-compatible timeline examples
_reference/                Reference files copied from Reigh contracts
runs/                      Ignored local outputs and generated artifacts
```

`pipeline.py` and the `bin/*.py` launchers just call matching modules under
`artagents/`. Prefer `pipeline.py` for normal workflows and `bin/<tool>.py` when
you need to run a single stage directly.

## Conductors And Performers

ArtAgents has two first-class workflow roles:

- **Conductors** orchestrate a workflow.
- **Performers** execute one human-facing action.

They are source-controlled package code, so they live under `artagents/`:

```text
artagents/conductors/
  curated/
    event_talks/
    hype/
    thumbnail_maker/

artagents/performers/
  curated/
    moirae/
    vibecomfy/
```

List and inspect performers:

```bash
python3 pipeline.py performers list
python3 pipeline.py performers inspect builtin.render --json
python3 pipeline.py performers validate
python3 pipeline.py performers run builtin.render --out runs/example --brief brief.txt --dry-run
```

List and inspect conductors:

```bash
python3 pipeline.py conductors list
python3 pipeline.py conductors inspect builtin.hype --json
python3 pipeline.py conductors validate
python3 pipeline.py conductors run builtin.hype --out runs/example --brief brief.txt --dry-run -- --target-duration 12
```

Fetch canonical Reigh data through the app Edge Function:

```bash
python3 pipeline.py reigh-data --project-id <PROJECT_UUID> --shot-id <SHOT_UUID> --out runs/reigh/shot.json
```

Repo-local installed external assets and environments belong under `.artagents/`,
which is ignored by git. Built-in and curated definitions belong under
`artagents/conductors/` and `artagents/performers/`.

## Pipeline Outputs

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

Use `--from <step>` to rerun a stage and everything after it:

```bash
python3 pipeline.py --video source.mp4 --brief brief.txt --out runs/example --from cut --render
```

Run audit reports for a pipeline run:

```bash
python3 pipeline.py audit --run runs/example
python3 pipeline.py audit --run runs/example --json
```

## Event Talk Splitting

Typical event-talk workflow:

```bash
python3 bin/transcribe.py --audio talk.wav --out runs/event/transcript --env-file /path/to/.env
python3 bin/event_talks.py ados-sunday-template --out runs/event/talks.json
python3 bin/event_talks.py search-transcript --transcript runs/event/transcript/transcript.json
python3 bin/event_talks.py render --manifest runs/event/talks.json --out-dir runs/event/rendered
```

For polished long-form event videos, keep the default
`bin/event_talks.py render --renderer remotion-wrapper`. It renders intro/outro
cards through Remotion and uses ffmpeg for the long media pass.

## Understanding Tools

Use these tools when editorial decisions need model help:

```bash
python3 bin/visual_understand.py --video source.mp4 --at 0,20,40 --query "Which frames are title cards?"
python3 bin/audio_understand.py --audio quote.wav --query "Is this quote strong enough for an opener?"
python3 bin/video_understand.py --video source.mp4 --at 01:20,03:45 --window-sec 20 --query "Which moment works better?"
```

Outputs should be written under `runs/`, for example:

```bash
python3 bin/visual_understand.py \
  --video source.mp4 \
  --at 0,20,40 \
  --query "Which frames should be cut?" \
  --out runs/visual/review.json
```

## Asset Generation

Generate GPT Image assets:

```bash
python3 bin/generate_image.py \
  --prompt "A clean editorial still of a red triangle on white" \
  --n 2 \
  --size 1024x1024 \
  --quality low \
  --output-format png \
  --out-dir runs/images \
  --manifest runs/images/manifest.json
```

Generate and slice a sprite sheet:

```bash
python3 bin/sprite_sheet.py \
  --animation "8-frame idle bounce" \
  --subject "small black five-point star mascot" \
  --frames 8 \
  --frame-width 256 \
  --frame-height 256 \
  --fps 8 \
  --out-dir runs/sprites/star-idle
```

## Rendering

Normal renders go through the wrapper, not raw `npx remotion render`:

```bash
python3 bin/render_remotion.py \
  --timeline runs/example/briefs/my-brief/hype.timeline.json \
  --assets runs/example/briefs/my-brief/hype.assets.json \
  --out runs/example/briefs/my-brief/render.mp4
```

The wrapper builds props, resolves themes, serves assets with HTTP Range support,
and avoids bundling large media.

Useful Remotion checks:

```bash
cd remotion
npm run typecheck
npm run smoke
npm run gen-types
```

Run `npm run gen-types` after effect, animation, or theme primitive changes.

## Publishing

Publish a rendered talk video through the shared YouTube/Zapier integration:

```bash
export ZAPIER_YOUTUBE_URL="https://hooks.zapier.com/hooks/catch/..."

python3 pipeline.py upload-youtube \
  --video-url "https://cdn.example.com/renders/talk.mp4" \
  --title "Rendered talk" \
  --description "A rendered talk video." \
  --privacy-status unlisted
```

The video input must already be a reachable `http(s)` URL. Local rendered files
are rejected with a clear error.

## Development

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run focused tests:

```bash
pytest tests/test_performers_cli.py tests/test_conductors_cli.py tests/test_compatibility_wrappers.py
```

Run the full Python suite:

```bash
pytest
```

Local secrets belong in `.env`, `.env.*`, or `this.env`; these are ignored by
git. Large source media and generated artifacts should stay under `runs/` or
another ignored output directory.

## License

Open Source Native License (OSNL) v0.2. See `LICENSE` for the full terms.
