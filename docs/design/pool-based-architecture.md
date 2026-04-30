# Pool-Based Architecture for Hype-Cut Runs

This document proposes a pool-first redesign for the `tools/` hype-cut pipeline so source analysis is separated from brief-specific composition. The goal is to replace timestamp-coupled Gemini picks with a deterministic asset pool plus ID-based arrangement handoffs. It preserves the existing ingest and render primitives while introducing a reusable `pool.json` pivot per source and an `arrangement.json` pivot per brief.

## 1. Problem Statement

The current `transcribe -> scenes -> shots -> gemini_picks -> cut -> render -> validate` flow breaks down at the picks step in four structural ways. First, Gemini can hallucinate timing because it sees a video clip but has no reliable internal clock for exact source placement; the motivating ADOS failure was: "caption said Pom's motivation quote; src range pointed to interviewer's next question". That specific mismatch should be treated as prior authoring evidence from an earlier ADOS export, not as something reproducible from `runs/ados_2026/picks.json` today, where `clip_004` at `:26-33` is the moth visual (`"Glowing white moth flying"`, `5015.5-5017.0`).

Second, picks are structure-blind. Upstream already computes transcript segments, scene boundaries, and shot/keyframe artifacts, but `gemini_picks.py` still queries on raw subclip MP4s and returns flat captioned picks, so an ADOS dialogue pick like `clip_003` and a visual pick like `clip_004` arrive without segment IDs, scene IDs, or any explicit link to the upstream structure the pipeline already paid to derive.

Third, picks couple audio and video into one source range. In the ADOS file, every entry in `runs/ados_2026/picks.json` is a single clip record with `keep_audio=true` and `caption_kind=null`, which means the current handoff cannot express "take dialogue from one source span while covering it with b-roll from another" or any real multitrack edit.

Fourth, analysis is coupled to composition. The current ADOS-style `plan.json` drives `gemini_picks.py` directly, so a new brief means rerunning the expensive pick generation step instead of reusing one source-grounded inventory; that prevents a single source run from supporting multiple editorial cuts cheaply and consistently.

## 2. Architecture Overview

The proposed design splits per-source analysis from per-brief composition and makes both LLM stages return stable IDs instead of numeric time fields. `pool.json` becomes the reusable per-source pivot, and `arrangement.json` becomes the per-brief pivot.

```text
INGEST [deterministic: Whisper / PySceneDetect / ffmpeg]
  transcribe.py -> transcript.json
  scenes.py     -> scenes.json
  shots.py      -> shots.json
        |
        v
POOL BUILDER [per-source, brief-agnostic]
  triage.py         [Claude Haiku]   keyframe grids -> triage signals
  scene_describe.py [Gemini]         survivor clips -> deep visual tags
  quote_scout.py    [Claude Sonnet]  transcript only, no brief input -> quote candidates
  pool_build.py     [deterministic]  merge + resolve source ranges
        |
        +--> pool.json  [per-source pivot]
        |
        v
ARRANGE [per-brief]
  arrange.py        [Claude Sonnet]  pool.json + brief.txt -> arrangement.json
        |
        +--> arrangement.json  [per-brief pivot]
        |
        v
ASSEMBLE [deterministic]
  cut.py (extended) -> hype.timeline.json + hype.assets.json + hype.metadata.json
        |
        v
RENDER [deterministic]
  Remotion -> hype.mp4
        |
        v
VALIDATE [deterministic]
  validate.py -> validation.json
```

This preserves the existing deterministic ingest and render endpoints but moves selection into a two-level handoff: source analysis first, brief composition second. Claude is used where text, image, and structure reasoning matter; Gemini is kept for dense short-clip visual description; deterministic code remains responsible for timestamps, artifact writing, and final assembly.

## 3. pool.json Schema

`pool.json` is a flat per-source array of reusable candidate assets. Every entry uses the same deterministic envelope, and only kind-specific descriptive fields vary. Brief-specific relevance is never persisted here; `arrange.py` computes that in memory against `brief.txt`.

```jsonc
[
  {
    "id": "string",
    "kind": "dialogue | visual | reaction | applause | music",
    "asset": "string",
    "src_start": 0.0,
    "src_end": 0.0,
    "duration": 0.0,
    "source_ids": {
      "segment_ids": ["segment_id", "segment_id"],
      "scene_id": "scene_id"
    },
    "scores": {
      "triage": 0.0,
      "deep": 0.0,
      "quotability": 0.0
    },
    "excluded": false,
    "excluded_reason": null
  }
]
```

Required envelope fields:

- `id`: stable pool handle. This is the sole identifier that `arrangement.json` references, and `hype.metadata.json` entries point back to it via `pool_id` as defined in section 8.a.
- `kind`: one of `dialogue`, `visual`, `reaction`, `applause`, or `music`.
- `asset`: source asset key.
- `src_start`, `src_end`, `duration`: deterministic timing values resolved by code, never written by an LLM.
- `source_ids`: source grounding. Dialogue entries use `segment_ids`; visual entries use `scene_id`; mixed cases may carry both.
- `scores`: brief-agnostic scoring only. Persisted keys are `triage`, `deep`, and `quotability`, each optional by kind.
- `excluded`, `excluded_reason`: pool-level filtering state without deleting the candidate from the inventory.

Kind-specific fields:

- `dialogue`: `text`, `speaker?`, `quote_kind`
- `visual`: `motion_tags[]`, `mood_tags[]`, `subject`, `camera`
- `reaction` / `applause`: `intensity`, `event_label`
- `music`: `bed_kind`, `energy`

Worked entries:

`runs/ados_2026/picks.json` clip_003 (`"It began a couple of years ago..."`) becomes a dialogue entry:

```json
{
  "id": "dialogue_ados_clip_003",
  "kind": "dialogue",
  "asset": "ados",
  "src_start": 2891.5,
  "src_end": 2899.5,
  "duration": 8.0,
  "source_ids": {
    "segment_ids": ["segment_legacy_clip_003"],
    "scene_id": "scene_legacy_clip_003"
  },
  "scores": {
    "quotability": 0.86
  },
  "excluded": false,
  "excluded_reason": null,
  "text": "It began a couple of years ago with just Peter, me, his brother, and a stranger from Twitter in our living room",
  "speaker": null,
  "quote_kind": "origin_story"
}
```

`runs/ados_2026/picks.json:26-33` (`"Glowing white moth flying"`, `5015.5-5017.0`) becomes a visual entry:

```json
{
  "id": "visual_ados_clip_004",
  "kind": "visual",
  "asset": "ados",
  "src_start": 5015.5,
  "src_end": 5017.0,
  "duration": 1.5,
  "source_ids": {
    "scene_id": "scene_legacy_clip_004"
  },
  "scores": {
    "triage": 4.0,
    "deep": 0.78
  },
  "excluded": false,
  "excluded_reason": null,
  "motion_tags": ["flying", "gliding"],
  "mood_tags": ["ethereal", "high-contrast"],
  "subject": "glowing white moth",
  "camera": "single-subject close visual"
}
```

`runs/ados_loose/transcript.json` segments 185-186 (`"Round of applause for Kajai."`) becomes an applause entry:

```json
{
  "id": "applause_ados_loose_seg_185_186",
  "kind": "applause",
  "asset": "ados",
  "src_start": 3152.637698,
  "src_end": 3160.637698,
  "duration": 8.0,
  "source_ids": {
    "segment_ids": ["185", "186"]
  },
  "scores": {},
  "excluded": false,
  "excluded_reason": null,
  "intensity": 0.62,
  "event_label": "round_of_applause_for_kajai"
}
```

## 4. Per-Stage Specs

**1. Triage (`triage.py`)**

- Purpose: Cheap first-pass visual filtering so only promising scenes reach the expensive deep-vision stage.
- Tier: Per-source.
- Inputs: `shots.json` plus `scenes.json`, rendered as scene grids of roughly 3 scenes x 3 keyframes each.
- Outputs: `triage.json` with `{scene_id, keep_score, suggested_mood_tags[]}` where `keep_score` is `0-5`.
- Model: Claude Haiku.
- Prompt sketch:

```text
Review this grid of scene keyframes and score each scene's keep potential from 0 to 5.
Return JSON objects keyed by scene_id only with keep_score and suggested_mood_tags.
Prefer concise descriptive tags over editorial prose.
The output schema forbids timestamps, seconds, or source ranges.
```

- Failure modes: Over-pruning subtle but useful scenes, or inflating generic conference coverage because the grid looks visually clean without enough context.
- Cost/wall-clock: On the ADOS source (`2h`, `704` scenes), about `235` Haiku grid calls; expected low single-digit dollar cost and tens-of-minutes wall-clock with batching.

**2. Deep visual (`scene_describe.py`)**

- Purpose: Rich visual tagging for the triage survivors so composition can reason over motion, mood, subject, and camera language.
- Tier: Per-source.
- Inputs: Survivor scenes only, typically those with `triage_score >= 3`; ADOS projects to roughly `70` scenes.
- Outputs: `scene_describe.json` with `{scene_id, deep_score, motion_tags[], mood_tags[], subject, camera}`.
- Model: Gemini.
- Prompt sketch:

```text
Describe the surviving scene at the scene_id level, not at the timestamp level.
Return JSON with deep_score, motion_tags, mood_tags, subject, and camera.
Focus on motion, mood, and shot character that matter for later arrangement.
The output schema forbids timestamps, seconds, or source ranges.
```

- Failure modes: Tag drift across visually similar scenes, or overconfident deep scores on noisy stage footage.
- Cost/wall-clock: On ADOS, about `70` Gemini clip calls after triage; expected low single-digit dollar cost and roughly `10-20` minutes wall-clock.

**3. Dialogue scout (`quote_scout.py`)**

- Purpose: Find reusable dialogue candidates that are quotable before any brief-specific composition happens.
- Tier: Per-source, brief-agnostic.
- Inputs: `transcript.json` only.
- Outputs: `quote_scout.json` with `{segment_ids[], quote_kind, speaker?, quotability}` where `quotability` is `0-1`.
- Model: Claude Sonnet.
- Prompt sketch:

```text
Read the transcript and identify self-contained quotes using segment_ids only.
Score generic quotability from sentence shape, closure, speaker attribution quality, and filler-word penalty.
Return JSON rows with segment_ids, quote_kind, speaker, and quotability.
The output schema forbids timestamps, seconds, brief_text, and source ranges.
```

- Failure modes: Missing a strong quote that spans awkward segment boundaries, or over-scoring incomplete lines that read better than they sound.
- Cost/wall-clock: On ADOS (`1015` segments), `1-2` Sonnet long-context calls paid once per source; expected low single-digit dollar cost and only a few minutes wall-clock.

**4. Pool writer (`pool_build.py`)**

- Purpose: Deterministically merge visual and dialogue analysis into the canonical per-source asset inventory.
- Tier: Per-source.
- Inputs: `triage.json`, `scene_describe.json`, `quote_scout.json`, plus `scenes.json` and `transcript.json` for deterministic range resolution.
- Outputs: `pool.json`.
- Model: Deterministic code.
- Prompt sketch:

```text
No LLM prompt: this stage is a deterministic merge.
Resolve src_start, src_end, duration, source_ids, and excluded flags from upstream artifacts.
Preserve only brief-agnostic fields in the written pool.
No time fields are generated by an LLM at this stage.
```

- Failure modes: Join mismatches between upstream IDs, or writing structurally valid entries whose source grounding is incomplete.
- Cost/wall-clock: Negligible model cost; usually under a minute on ADOS once upstream JSON exists.

**5. Arrange (`arrange.py`)**

- Purpose: Compose one brief-specific cut by selecting from the reusable pool instead of rerunning analysis.
- Tier: Per-brief.
- Inputs: `pool.json` plus `brief.txt`.
- Outputs: `arrangement.json`.
- Model: Claude Sonnet.
- Prompt sketch:

```text
Compose an ordered cut from pool.json against this brief using pool_id references only.
Choose dialogue spine clips, visual coverage, optional text overlays, and brief notes.
Compute relevance against the brief in memory; do not persist relevance into pool.json.
The output schema forbids timestamps, seconds, or source ranges.
```

- Failure modes: Selecting semantically right clips that do not cut cleanly together, or overfitting to the brief and dropping essential pacing coverage.
- Cost/wall-clock: One Sonnet call per brief; expected sub-dollar to low single-digit cost and typically under `2` minutes wall-clock.

## 5. arrangement.json Schema

`arrangement.json` is the per-brief composition handoff and lives under the brief-specific run directory described in section 8.c. It contains editorial order and source references only; there are no clip-level timestamps, source seconds, or timeline coordinates in this file.

```jsonc
{
  "brief_text": "string",
  "target_duration_sec": 60,
  "clips": [
    {
      "order": 1,
      "audio_source": "pool_id | null",
      "visual_source": "pool_id",
      "text_overlay": {
        "content": "string",
        "style_preset": "string"
      },
      "notes": "string"
    }
  ]
}
```

Example:

```json
{
  "brief_text": "Build a 60-second origin-to-spectacle cut for ADOS with one clean quote hook, one iconic b-roll insert, and one emphatic text beat.",
  "target_duration_sec": 60,
  "clips": [
    {
      "order": 1,
      "audio_source": "dialogue_ados_clip_003",
      "visual_source": "dialogue_ados_clip_003",
      "notes": "Open on the origin-story line as the dialogue spine."
    },
    {
      "order": 2,
      "audio_source": "dialogue_ados_clip_003",
      "visual_source": "visual_ados_clip_004",
      "notes": "Cover the middle of the quote with the moth shot as b-roll."
    },
    {
      "order": 3,
      "audio_source": "dialogue_ados_clip_003",
      "visual_source": "dialogue_ados_clip_003",
      "text_overlay": {
        "content": "From living room to main stage",
        "style_preset": "title_card"
      },
      "notes": "Land the line with a text beat while staying on speaker footage."
    }
  ]
}
```

## 6. Multitrack Timeline Mapping

> `tools/timeline.py:16,22`: `TrackKind = Literal['visual','audio']; ClipType = Literal['media','hold','text','effect-layer']. v1, v2, and text are local names in this doc only — no new reigh-app fields.`

Mapping rules:

- `a1`: audio track built from `audio_source` when it is not `null`.
- `v1`: primary visual track, usually the speaker footage that matches the dialogue spine.
- `v2`: overlay visual track used when `visual_source` differs from the dialogue clip's footage; the overlay clip is written with `volume: 0.0`.
- `text_overlay`: a `clipType: "text"` clip written on the highest-numbered active visual track, which means `v2` when b-roll is active and `v1` otherwise.

Round-trip example, mirroring the structure of `tools/examples/hype.timeline.full.json`:

```json
{
  "tracks": [
    {
      "id": "v1",
      "kind": "visual",
      "label": "Primary Visual"
    },
    {
      "id": "v2",
      "kind": "visual",
      "label": "Overlay Visual"
    },
    {
      "id": "a1",
      "kind": "audio",
      "label": "Dialogue Audio"
    }
  ],
  "clips": [
    {
      "id": "clip_001_v1",
      "at": 0.0,
      "track": "v1",
      "clipType": "media",
      "asset": "ados",
      "from": 2891.5,
      "to": 2899.5
    },
    {
      "id": "clip_001_a1",
      "at": 0.0,
      "track": "a1",
      "clipType": "media",
      "asset": "ados",
      "from": 2891.5,
      "to": 2899.5
    },
    {
      "id": "clip_002_v2",
      "at": 8.0,
      "track": "v2",
      "clipType": "media",
      "asset": "ados",
      "from": 5015.5,
      "to": 5017.0,
      "volume": 0.0
    },
    {
      "id": "clip_003_text",
      "at": 10.0,
      "track": "v1",
      "clipType": "text",
      "text": {
        "content": "From living room to main stage",
        "fontFamily": "IBM Plex Sans",
        "fontSize": 64.0,
        "color": "#f7f3e8",
        "align": "center",
        "bold": true
      }
    }
  ]
}
```

## 7. Scoring + Filtering Rubrics

Drafting in subsequent batches.

## 8. Migration Plan

Drafting in subsequent batches.

## 9. Cost + Time Estimates

Drafting in subsequent batches.

## 10. Failure Modes + Graceful Degradation

Drafting in subsequent batches.

## 11. Open Questions

Drafting in subsequent batches.

## 12. v1 Non-Goals

Drafting in subsequent batches.
