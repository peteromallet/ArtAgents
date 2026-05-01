---
name: "artagents"
description: "Use for the ArtAgents repo: file-based hype-cut/video pipeline work, source analysis, transcript/event-talk splitting, pure-generative Remotion timelines, Reigh-compatible timeline/assets JSON, validation/review loops, and GPT Image asset generation via generate_image.py."
---

# ArtAgents

ArtAgents is a file-based toolkit for producing Reigh-compatible video edits and generative timelines. Use repo-local CLIs from the repository root. `pipeline.py` stays at the root as the primary entry point; direct stage launchers live under `bin/` and call `artagents/*` modules.

## First Checks

Run these before editing:

```bash
git status --short
rg --files
```

Do not overwrite unrelated local changes. Large source media and generated artifacts should stay out of git under `runs/` or another ignored output directory.

## Upstream Friction

When a workflow is awkward, brittle, undocumented, or requires a local workaround, tell the user directly. Suggest the smallest durable fix and, when the issue belongs in an original upstream repository rather than ArtAgents, recommend creating a PR there with the concrete file or behavior to change.

## Core Workflows

Source video hype cut:

```bash
python3 pipeline.py --video SRC.mp4 --brief brief.txt --out runs/<name> --render
```

Audio-only or pure-generative timeline:

```bash
python3 pipeline.py --audio rant.wav --brief brief.txt --out runs/<name> --render
python3 pipeline.py --brief brief.txt --theme <theme-id> --out runs/<name> --render --target-duration 28
```

Event talk splitting:

```bash
python3 bin/transcribe.py --audio talk.wav --out runs/event/transcript --env-file /path/to/.env
python3 bin/event_talks.py ados-sunday-template --out runs/event/talks.json
python3 bin/event_talks.py search-transcript --transcript runs/event/transcript/transcript.json
python3 bin/event_talks.py render --manifest runs/event/talks.json --out-dir runs/event/rendered
```

ArtAgents has two first-class workflow roles: conductors and performers. Conductors are the coordination layer. Performers are the human-facing actions a conductor can call. Use `performers` for executable units such as rendering, external tools, and uploading to YouTube. Do not introduce another workflow role for this layer; coordination belongs to conductors, execution belongs to performers. New code should import from `artagents.performers`.

```bash
python3 pipeline.py performers list
python3 pipeline.py performers inspect builtin.render --json
python3 pipeline.py performers run builtin.render --out runs/<name> --brief brief.txt --dry-run
python3 pipeline.py performers inspect upload.youtube
python3 pipeline.py performers run upload.youtube --dry-run --video-url https://cdn.example.com/talk.mp4 --title "Talk" --description "Description"
python3 pipeline.py conductors list
python3 pipeline.py conductors inspect builtin.hype --json
python3 pipeline.py conductors validate
python3 pipeline.py conductors run builtin.hype --out runs/<name> --brief brief.txt --dry-run -- --target-duration 12 --from cut
python3 pipeline.py conductors run builtin.event_talks --out runs/event --dry-run -- ados-sunday-template --out runs/event/talks.json
```

## Reigh Data Tool

Use `artagents/skills/reigh-data/SKILL.md` before fetching live Reigh project, shot, task, timeline, image, or video data. The canonical command is:

```bash
python3 pipeline.py reigh-data --project-id <PROJECT_UUID> --shot-id <SHOT_UUID> --out runs/reigh/shot.json
```

This calls the PAT-authenticated `reigh-data-fetch` Edge Function in `reigh-app`; do not add direct Supabase table queries in ArtAgents for this data.

The main root launcher remains supported, and direct stage launchers live under `bin/`:

```bash
python3 pipeline.py --video SRC.mp4 --brief brief.txt --out runs/<name> --render
python3 bin/event_talks.py render --manifest runs/event/talks.json --out-dir runs/event/rendered
```

For polished long event-talk videos, keep `bin/event_talks.py render` on its default `--renderer remotion-wrapper`: Remotion renders the animated intro/outro cards, while ffmpeg handles the long media pass, lower-third, corner logo, and final concat. Card renders are cached beside the card MP4s and are invalidated by talk metadata, dimensions, duration, and brand asset mtimes; use `--force-card-render` when iterating on card animation code. Full `--renderer remotion` writes Reigh-style timeline/assets JSON and renders the whole talk through `bin/render_remotion.py`, but it can be slow and disk-heavy for 10+ minute talks and now preflights free disk. `--renderer ffmpeg-proof` is only for quick boundary/proof checks, not final branded output.

## Remotion Renderer

Official Remotion agent skill: `remotion-best-practices`.

```bash
npx skills add remotion-dev/skills
npx remotion skills add
```

Use it for general Remotion background, but follow ArtAgents contracts first. The Remotion project is `remotion/`; normal ArtAgents renders go through `python3 bin/render_remotion.py`, not raw `npx remotion render`, because the wrapper builds props, resolves themes, serves assets with HTTP Range support, and avoids bundling large media.

```bash
python3 bin/render_remotion.py \
  --timeline runs/<name>/briefs/<brief>/hype.timeline.json \
  --assets runs/<name>/briefs/<brief>/hype.assets.json \
  --out runs/<name>/briefs/<brief>/render.mp4
```

```bash
cd remotion
npm run typecheck
npm run smoke
npm run gen-types
```

Run `gen-types` after effect/theme primitive changes. For long event talks, prefer `bin/event_talks.py render --renderer remotion-wrapper`; use full `--renderer remotion` only when the whole talk must go through timeline/assets rendering.

Guardrails: `TimelineComposition` lives in `remotion/src/Root.tsx`; use `calculateMetadata` for timeline/theme-derived duration, dimensions, fps, or props; keep props JSON-serializable; use explicit frame math and clamped `interpolate()` timing; consume registry URLs prepared by `bin/render_remotion.py`; preserve `_reference/README.md` semantics; do not put large media in `remotion/public/` or commit generated renders.

## Generate Image Tool

Use `bin/generate_image.py` for GPT Image API asset generation inside ArtAgents:

```bash
python3 bin/generate_image.py \
  --prompt "A minimal editorial still of a red triangle on white" \
  --n 2 \
  --size 1024x1024 \
  --quality low \
  --output-format png \
  --out-dir runs/images \
  --manifest runs/images/manifest.json
```

Prompt-list files are supported:

- Plain text: one prompt per non-empty line.
- JSON array: `["prompt one", {"prompt": "prompt two", "n": 3, "size": "1536x1024"}]`
- JSONL: one string or object per line.

Use `--dry-run` before expensive batches. API keys are read from the process environment, `this.env`, nearby workspace `.env` files, or an explicit `--env-file /path/to/.env`. Do not print or hardcode API keys.

Current GPT Image defaults:

- model: `gpt-image-2`
- size: `1024x1024`
- quality: `medium`
- output format: `png`

`gpt-image-2` size rules: `WIDTHxHEIGHT` must use multiples of 16, max edge <= 3840, aspect ratio <= 3:1, and total pixels between 655,360 and 8,294,400.

## Visual Understanding Tool

Use `bin/visual_understand.py` when you need a cheap visual read on one image or a batch of sampled video frames. It can pass a single image directly, or build a numbered contact sheet from up to 20 images/frames before querying an OpenAI vision model.

```bash
python3 bin/visual_understand.py \
  --video source.mp4 \
  --at 0,20,40,60,80,100,120,140 \
  --query "Which numbered frames are holding/title screens to remove, and which should be kept?" \
  --out runs/visual-understanding/review.json \
  --env-file /path/to/.env
```

Defaults: `--mode fast` (`gpt-4o-mini`), `detail=low`, `cols=4`, `max-images=20`. Use fast first for normal review and boundary checks. If the answer is not detailed enough, the visual evidence is ambiguous, or the cut decision needs higher confidence, rerun with `--mode best` (`gpt-5.4`). Use `--model MODEL` only for explicit one-off overrides, `--compare-model MODEL` to compare additional models on the same contact sheet, and `--detail high` only for small text or dense visual evidence. Keep generated frames, contact sheets, and JSON answers under `runs/`.

Use crop review when deciding vertical/social framing from one image or sampled frame:

```bash
python3 bin/visual_understand.py \
  --video source.mp4 \
  --at 140 \
  --crop-aspect 9:16 \
  --crop-position left,center,right \
  --query "Which crop works best for 9:16 and keeps the speaker most readable?"
```

`--crop-aspect` accepts repeated or comma-separated aspects such as `9:16,1:1`; `--crop-position` accepts alignments such as `left,center,right` or `top,center,bottom`. Crop review requires exactly one source image/frame and creates a numbered contact sheet of variants.

If you do not know which frames to query, do not guess manually. Reuse or generate asset-level analysis first:

```bash
python3 bin/scenes.py --video source.mp4 --out runs/event/scenes.json
python3 bin/shots.py --video source.mp4 --scenes runs/event/scenes.json --out runs/event/shots
python3 bin/event_talks.py find-holding-screens --video source.mp4 --out runs/event/holding-screens.json
python3 bin/boundary_candidates.py \
  --asset-key main \
  --video source.mp4 \
  --manifest runs/event/talks.json \
  --transcript runs/event/transcript/transcript.json \
  --scenes runs/event/scenes.json \
  --shots runs/event/shots/shots.json \
  --holding-screens runs/event/holding-screens.json \
  --out runs/event/boundary-candidates.json
```

Store source-derived analysis at asset level. `hype.metadata.json` already uses `sources[asset_key].transcript_ref`, `scenes_ref`, `shots_ref`, and `quality_zones_ref`; boundary candidate packages should mirror that with `asset_key`, `asset_analysis`, and `metadata_source_refs`. Do not embed this analysis into `hype.timeline.json` or `hype.assets.json`; those stay Reigh-compatible and timelines only reference assets and edits.

## Audio Understanding Tool

Use `bin/audio_understand.py` when the edit question depends on how something sounds, not just what was said: emotional force, excitement, speed, pauses, laughter, applause, music/SFX, clipping, echo, room tone, or whether a quote has a clean in/out.

Single source:

```bash
python3 bin/audio_understand.py \
  --audio quote.wav \
  --query "Is this quote emotionally strong enough for an opener? Is the speaker too slow?" \
  --out runs/audio-understanding/quote-review.json \
  --env-file /path/to/.env
```

Comparison sources:

```bash
python3 bin/audio_understand.py \
  --audio quote-a.wav \
  --audio quote-b.wav \
  --audio quote-c.wav \
  --query "Which numbered quote sounds the most emotional and exciting? Rank them and flag any pacing problems." \
  --out runs/audio-understanding/quote-comparison.json
```

For comparison, the tool builds a numbered audition reel: it says "Number 1", plays the first clip, says "Number 2", plays the second clip, and so on. This is the audio equivalent of a visual contact sheet: the model hears the candidates in one context and can compare delivery, pace, intensity, and production quality directly.

For video, pass `--video source.mp4 --at 01:20,03:45 --window-sec 20` to extract windows around candidate moments. Multiple windows also default to a numbered audition reel. Use `--audition-reel never` when you want per-window independent analysis.

Philosophical rule: transcript is factual text evidence; direct audio understanding is listening evidence. Use `bin/transcribe.py` for exact words and speaker timing, then use `bin/audio_understand.py` for embodied editorial judgment: urgency, hesitation, charm, tension, crowd response, music shape, and whether the cut feels alive.

## Video Understanding Tool

Use `bin/video_understand.py` when the edit question depends on synchronized picture and sound rather than frames alone or audio alone: gestures, speaker presence, camera movement, visual continuity, crowd reaction, music shape, production quality, and whether the moment lands as a complete video beat.

```bash
python3 bin/video_understand.py \
  --video source.mp4 \
  --at 01:20,03:45 \
  --window-sec 20 \
  --query "Which moment works better as an opener? Consider picture, sound, energy, and clean in/out points." \
  --out runs/video-understanding/opener-review.json \
  --env-file /path/to/.env
```

Defaults: `--mode fast` (`gemini-2.5-flash`) with extracted upload clips under `runs/video-understanding/video-windows`. Use `--mode best` (`gemini-2.5-pro`) when the synchronized evidence is subtle or high-stakes. If no `--at` or `--start/--end` is provided, the tool chunks the source into bounded windows. Keep generated clips and JSON answers under `runs/`.

Use the unified `bin/understand.py` dispatcher when you want one entry point:

```bash
python3 bin/understand.py image --image frame.jpg --query "What is happening here?"
python3 bin/understand.py audio --audio quote.wav
python3 bin/understand.py video --video source.mp4 --at 01:20
```

Philosophical rule: visual understanding is frame/contact-sheet evidence, audio understanding is listening evidence, video understanding is synchronized sight-and-sound evidence, and transcript remains factual text evidence.

## Sprite Sheet Setting

Use `bin/sprite_sheet.py` when the user wants an animation asset, sprite sheet, chopped frames, or a preview video:

```bash
python3 bin/sprite_sheet.py \
  --animation "8-frame idle bounce: squash down, stretch up, settle back to neutral" \
  --subject "small black five-point star mascot" \
  --cols 4 \
  --rows 2 \
  --frame-width 256 \
  --frame-height 256 \
  --fps 8 \
  --quality medium \
  --out-dir runs/sprites/star-idle \
  --env-file /path/to/.env
```

The workflow:

1. Compute exact sheet size from grid: `cols * frame_width` by `rows * frame_height`.
2. Generate `layout_guide.png`, an outline image that marks cell boundaries and safe areas.
3. Query GPT Image with technical sprite-sheet specs and the layout guide.
4. Save `sprite_sheet.png`.
5. Validate the returned PNG dimensions exactly match the planned sheet.
6. Slice cells into `frames/frame_001.png`, `frames/frame_002.png`, etc.
7. Optionally normalize/recenter frames and run AI upscaling on the transparent frame sequence.
8. Assemble `sprite_preview.mp4` for quick review and `sprite_preview_prores.mov` as a higher-quality animation master.
9. Write efficient web assets under `web/`: a WebP atlas, WebP frame sequence, web MP4 preview, and `sprite_web_manifest.json`.
10. Save `sprite_manifest.json` with prompt, layout, frame positions, outputs, FPS, and usage metadata.

Use `--frames N` and let the tool auto-select rows/columns when possible. It chooses a compact valid sheet under `gpt-image-2` limits, preferring low wasted cells and near-square layouts. Default to `4x4` frames of `256x256` for a `1024x1024` sheet unless the user specifies otherwise. For short smoke tests, use `2x2` frames of `512x512` so the sheet is still `1024x1024` and valid for `gpt-image-2`.

Prompt the animation as a precise sequence: pose count, motion arc, camera consistency, scale consistency, background, and any forbidden artifacts. The generated sheet should contain no text, labels, grid lines, frame separators, watermarks, or gutters.

Transparent output defaults to chroma key for `gpt-image-2`: the prompt asks for a flat `--key-color` background, then ffmpeg removes that color into `sprite_sheet_alpha.png` and alpha PNG frames. Use `--no-transparent --background "..."` when a real background should remain. Native `background=transparent` works on transparent-capable GPT Image models such as `gpt-image-1.5`, but the sprite-sheet path uses chroma by default because it keeps the grid/dimension constraints deterministic.

To remove/slice after generation without another API call:

```bash
python3 bin/sprite_sheet.py \
  --input-sheet runs/sprites/star-idle/sprite_sheet.png \
  --animation "existing 30-frame run cycle" \
  --subject "same character" \
  --frames 30 \
  --frame-width 256 \
  --frame-height 256 \
  --fps 12 \
  --out-dir runs/sprites/star-idle-post
```

If grid lines or key color leak into the generated sheet, rerun with a stricter prompt, adjust `--key-similarity` / `--key-blend`, use a different `--key-color`, or slice with `--slice-trim 4` to remove cell-edge artifacts.

If characters drift out of frame after slicing, inspect `sprite_manifest.json` for `edge_warning_count`. Use `--normalize-frames --normalize-margin 18` to crop each frame to its alpha bounds, scale down only when necessary, and recenter it in the same frame size before building previews.

For proper high-quality upscaling, upscale after transparency extraction and normalization, not before slicing and not from the final video. Use FAL Clarity Upscaler:

```bash
python3 bin/sprite_sheet.py \
  --input-sheet runs/sprites/star-idle/sprite_sheet.png \
  --animation "existing 30-frame run cycle" \
  --subject "same character" \
  --frames 30 \
  --frame-width 512 \
  --frame-height 512 \
  --fps 12 \
  --normalize-frames \
  --ai-upscale-provider fal \
  --ai-upscale-factor 2 \
  --out-dir runs/sprites/star-idle-ai-upscaled \
  --force
```

The FAL path uploads each transparent PNG frame to `fal-ai/clarity-upscaler`, downloads the enhanced result, then re-applies an upscaled copy of the original alpha mask so the background remains clean. Defaults are tuned for sprite preservation: low creativity and high resemblance. It reads `FAL_KEY` or `FAL_API_KEY` from the process, `--fal-env-file`, or nearby workspace `.env` files. Do not print or hardcode FAL keys.

The local `--upscale-factor` path is only a deterministic ffmpeg fallback. Use it for fast previews, not final high-quality enlargement.

For web delivery, prefer the default WebP atlas plus `sprite_web_manifest.json` for CSS/canvas playback, or individual WebP frames for lazy-loaded animation systems. When frames are normalized or upscaled, the tool rebuilds `sprite_sheet_processed.png` before web conversion so the atlas matches the final processed frame size. Use `--web-max-dim` to cap runtime frame size and `--web-quality` to tune file size. Animated WebP is opt-in with `--web-animated`; for 20-30 frame sprites it is usually less efficient and less controllable than atlas/canvas playback.

## Important Contracts

- `pipeline.py --brief ...` is the canonical top-level flow.
- Performers execute one unit; conductors orchestrate performers and may call declared child conductors. Performers must not call conductors.
- `bin/cut.py` emits `hype.timeline.json`, `hype.assets.json`, `hype.metadata.json`, and `hype.edl.csv`.
- Reigh-facing JSON should round-trip through existing helpers and tests.
- Source-cut timelines preserve legacy `clipType="text"` overlays.
- Pure-generative timelines may use extended `clipType` values and `params`.
- Effects live under workspace-level `effects/<id>/` or theme-level `themes/<id>/effects/<id>/`.
- After adding or renaming effects, run:

```bash
cd remotion
npm run gen-types
```

## Validation

Use focused tests for changed behavior:

```bash
pytest tests/test_generate_image.py
pytest tests/test_schema_contract.py tests/test_pure_generative_pipeline.py
```

For render-related changes, also run the relevant Remotion or render smoke tests already in `tests/`.
