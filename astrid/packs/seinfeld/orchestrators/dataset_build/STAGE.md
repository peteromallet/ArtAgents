---
name: seinfeld_dataset_build
description: Bucket-fill loop that builds the Seinfeld LoRA training set from YouTube — living doc tracking what exists, what's missing, and the running plan.
---

# Seinfeld Dataset Build — Living Doc + Skill Map

This is BOTH the orchestrator STAGE.md AND the running planning doc for the
dataset-collection phase. Edit it as we work — don't keep a parallel notes file.

The canonical project plan is `/project.md` at repo root. This doc dives into
the dataset phase specifically and maps it to concrete tools.

## What we're building

A bucket-fill loop that produces a Seinfeld LoRA training set:

```
read criteria (locked vocab + bucket targets)
└── repeat.until(all buckets full):
    ├── search YouTube for N candidates                [needs new exec — youtube_search]
    ├── download top-N video files                    [✅ builtin.youtube_audio --mode video]
    ├── segment each video into scenes                [✅ builtin.scenes]
    ├── cheap pre-filter (length, transcript words)   [code, in run.py]
    ├── VLM judge each scene → bucket assignment      [✅ builtin.visual_understand --response-schema]
    ├── VLM caption each accepted clip (locked vocab) [✅ builtin.visual_understand --response-schema]
    └── update bucket counts
human review ~50 random pairs                          [attested human gate]
manifest export                                        [needs new exec — seinfeld.dataset_manifest]
```

**As of this commit, the only genuinely-new executors we still need to build
are `seinfeld.youtube_search` and `seinfeld.dataset_manifest`.** Everything
else is covered by extending two existing builtins.

## Proven end-to-end (2026-05-11)

The full inner loop ran successfully on one clip:

```
builtin.youtube_audio --mode video --query "..."
  → runs/seinfeld-dataset/candidates/clip-01.mp4    (95s, 7MB, vp9 480p)

builtin.scenes --video clip-01.mp4
  → 11 scenes detected; top 5 by duration kept for judging.

builtin.visual_understand --response-schema bucket_judge.json (×5, mode=fast)
  → 4/5 accepted as jerrys_apt; 1 correctly rejected (closeup of feet).
    All 5 returned strict-JSON matching the schema.

builtin.visual_understand --response-schema caption.json (×1, mode=best)
  → Vocab-locked caption produced. Sample:
    "A wide shot in jerrys_apt. george in polo_chinos and jerry in
     jeans_buttondown. george stands by the door while jerry naps on
     the couch. Seinfeld sitcom style, 90s NBC sitcom lighting,
     multi-cam look."
```

Schemas live at `astrid/packs/seinfeld/schemas/{bucket_judge,caption}.json`.
The orchestrator skeleton in `run.py` is what we wire those calls into next.

Output: a `manifest.json` mapping clip-file → caption, ready for ai-toolkit ingest.

## Existing tools we use as-is

Found via `python3 -m astrid executors list`:

| What we need | Tool | Notes |
|---|---|---|
| Scene segmentation | `builtin.scenes` | Takes `--video`, writes `scenes.json` with boundary timestamps. Already cached on `scenes.json` sentinel. |
| VLM on images / frames | `builtin.visual_understand` | OpenAI vision via `/v1/responses`. Takes `--query`, `--video --at` or `--image`. Cheap first-pass judge. |
| VLM on video+audio | `builtin.video_understand` | Heavier model with built-in response schema. Use as fallback when visual_understand isn't enough. |
| Bucket-fill reference | `builtin.pool_build` | Read its run.py — it's the canonical model for "fill buckets from candidate clips with a criteria spec". |
| YouTube downloading (audio or video, by query or URL) | `builtin.youtube_audio` | `yt-dlp` wrapper. Now supports `--mode video` (MP4 download, no audio extraction) and `--url` (skip search). Top-hit search only — for multi-result lists use `seinfeld.youtube_search`. |
| VLM with structured output | `builtin.visual_understand` + `--response-schema PATH` | Now accepts a JSON schema and constrains the model's reply to match it (OpenAI Responses API strict json_schema). Use a vocabulary-derived schema for bucket-judge and caption steps — no project-specific wrapper needed. |

Read STAGE.md inside each pack before invoking — that's the source of truth.

## New executors we still need to build

Two. Keep each ONE concrete unit of work. Slugs live as siblings under `astrid/packs/seinfeld/`.

### `seinfeld.youtube_search`
- **In:** `--query`, `--max-results N`
- **Out:** `urls.json` list of `{url, title, duration_s, channel}` candidates
- **How:** `yt-dlp ytsearch{N}:<query> --flat-playlist --dump-json`. No download.
- **Why new:** `builtin.youtube_audio` does top-1 by design — search-as-list is a genuinely different unit of work.

### `seinfeld.dataset_manifest`
- **In:** directory of accepted clips + per-clip caption JSONs (the structured output from `visual_understand --response-schema`)
- **Out:** `manifest.json` in whatever shape ai-toolkit ingests (TBD — check ai-toolkit docs in Phase 2).
- **How:** Glob + write. Pure code, no network.
- **Why new:** Project-specific output schema.

## Vocabulary → JSON schema

Two schemas live next to `vocabulary.yaml`:

- `schemas/bucket_judge.json` — enums sourced from `vocabulary.yaml`'s `scenes`
  and `characters`. Fields: `accept`, `bucket`, `confidence`, `reasons`.
- `schemas/caption.json` — enums for `scene`, per-character `outfit`,
  `shot_type`; free-text `action`. Matches the `caption_template` shape.

Both schemas are passed to `builtin.visual_understand --response-schema`.

Generating them from `vocabulary.yaml` is a small build step inside
`dataset_build.run` (or a one-shot script next to it). Don't hand-edit both
in parallel — the yaml is the source of truth.

## Orchestrator logic (run.py shape)

```
1. Load criteria from --vocabulary and --bucket-targets.
2. Track per-bucket counts in a state file (resumable).
3. While any bucket < target:
   a. Pick under-filled buckets, derive search queries.
      (e.g., for bucket "monks_diner × jerry+george", query = "seinfeld monk's diner jerry george scene").
   b. seinfeld.youtube_search → candidate URLs.
   c. For each URL not already processed:
      - seinfeld.youtube_video → mp4
      - builtin.scenes → scenes.json
      - cheap_filter (in-process): drop scenes <2s or >12s, transcript keyword check if available.
      - For each surviving scene clip:
        - seinfeld.vlm_bucket_judge → reject or assign bucket
        - if accepted and bucket not full:
          - seinfeld.vlm_caption → schema-checked caption
          - record clip + caption
   d. Persist state.
4. Attested human gate: review N random clip+caption pairs.
   Produces `human_review.json` with approve/reject per sampled pair.
   If reject-rate > threshold, rewind and retune queries/judge.
5. seinfeld.dataset_manifest → manifest.json.
```

## Inputs / outputs

```bash
python3 -m astrid orchestrators run seinfeld.dataset_build -- \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --bucket-targets '{"jerrys_apt": 80, "monks_diner": 80, ...}' \
  --out runs/seinfeld-dataset
```

Output tree:
```
runs/seinfeld-dataset/
  state.json
  candidates/                       # downloaded mp4s, scene jsons
  accepted/<bucket>/<clip-id>.mp4
  accepted/<bucket>/<clip-id>.caption.json
  human_review.json
  manifest.json
```

## What's NOT in scope here

- Training itself — that's `seinfeld.lora_train`.
- RunPod lifecycle — separate cross-cutting refactor (see project.md "Cross-cutting infra").
- Anything to do with rendering or script generation.

## Open questions / blockers

Surface these to the user before implementing:

1. **Pack location: gitignored or committed?**
   Currently `astrid/packs/seinfeld/` is gitignored (matches `project.md`).
   If this is real ongoing infra, flip — just drop the line in `.gitignore`.

2. **VLM cost.** A naïve loop sends every scene clip to the API. Order of
   magnitude: 300 buckets × ~5 candidates_per_accept × $0.005/judge ≈ $7.50
   on `visual_understand` fast mode, more on `video_understand`. Budget OK?

3. **Cheap pre-filter contents.** Length-only is too weak. Options:
   transcript keyword match (needs `builtin.transcribe` first), or
   `visual_understand` on the middle frame as a sub-cent first-gate.

4. **Source legality.** project.md mentions YouTube ToS. For a demo this is
   fine; if it goes public we need a different sourcing plan.

5. **Bucket target shape.** Per-scene? Per (scene × character)? Per
   (scene × character × outfit)? Drives query count and dataset size.

6. **Caption template stability.** `vocabulary.yaml` is a draft. Phase 0
   (write 10 inference prompts, reverse-engineer enums) must precede any
   real run, otherwise we'll burn VLM budget on the wrong taxonomy.

## How to use this doc

- Treat the **tables above** as the current source-of-truth list of tools.
  When we build a new executor, move it from "we need to build" to "exists".
- Treat **Open questions** as a live punch list — close them as we go.
- Cross-link to `project.md` for the big picture, not the implementation details.
