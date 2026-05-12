# Seinfeld dataset — quality guardrails

## Retrospective: what v0 + v1 got wrong, what v2 fixes

Captured here so the next project doesn't repeat these mistakes.

### v0 misses (Brief Tier — pre-quality-gates)

1. **`min_scene_s = 2.5`, `max_scene_s = 15.0` were picked from intuition,
   not from LTX 2.3's trainer-bucket constraints.** The actual constraint
   is the `1 + 8N` frame rule: training samples are 49 (~2s), 73 (~3s),
   97 (~4s), or 121 (~5s) frames at 24 fps. **121 frames (5s) is the
   practical max** several practitioners cite as the upper bucket; above
   that the trainer subsamples or chunks. Our 9s average clips meant the
   trainer was seeing a slice the caption oversold.
2. **PySceneDetect was trusted without verification.** It misses
   within-set cuts (wide-to-medium angle changes in the same lighting)
   and gets thrown off by YouTube compilation re-encoding artifacts. v1
   added the VLM verifier; v0 didn't have it.
3. **Schemas were hand-written.** They drifted from `vocabulary.yaml` on
   the first edit. v1 introduced `vocab_compile.py` as the single source
   of truth.
4. **Hivemind wasn't consulted upfront.** The `1 + 8N` rule, the typical
   bucket sizes (49/73/97/121 frames), and the community floor on
   per-bucket clip counts (~50, not 15) were knowable before we ran the
   first pass. Asking sooner would have saved an iteration.

### v1 misses (Caption Tier — pre-trainer-alignment)

5. **Caption sections assumed the whole clip was one semantic unit.** The
   `speech_transcription` field transcribed all ~9s of dialogue. When
   the trainer subsamples a ~2s window, the caption claims dialogue the
   training data doesn't contain. The static parts (scene, anchors,
   style suffix) stayed aligned; the dialogue and sounds did not.
6. **No trainer-bucket alignment in the orchestrator.** Even after the
   verifier trimmed cuts, surviving clips ran 4–14s — outside the LTX
   training bucket. Captions and trainer-window were guaranteed to
   misalign on dynamic content.

### v2 fixes (this rebuild)

1. **`--max-scene-s = 5.0`** (= 121 frames @ 24fps, the LTX bucket
   ceiling) and **`--min-scene-s = 2.0`** (= 49 frames) become the new
   defaults. Every accepted clip lies inside one trainer bucket.
2. **Long scenes get split into multiple aligned sub-clips.** A 9s scene
   becomes two ~4.4s sub-clips (with a small gap to avoid duplicate
   boundary frames). Each sub-clip is independently verified,
   transcribed, and captioned. Side effect: same source footage produces
   ~2× the training samples.
3. **Caption prompt updated** (`CAPTION_PROMPT_VERSION = v3_window_local`)
   to instruct the captioner to **describe ONLY what is in this
   window** — not the surrounding scene's context. Dialogue may start
   or end mid-sentence; that's expected and correct for a window-local
   transcript.
4. **No re-download required** — the rebuild operates on the source
   mp4s already in `runs/seinfeld-dataset/candidates/`, using the
   verified bounds from state. Cost is just `verify + transcribe +
   caption` per sub-clip (~$0.030 each, ~60 sub-clips ≈ $2).

### v3 fixes — hero scenes + strict no-cuts mode

After v2 we observed two remaining issues:

7. **Bucket-judging was unreliable on compilation footage.** Multi-episode
   compilation channels splice scenes from different sets together; even
   with the per-window VLM verifier catching cuts, the wardrobe / lighting
   variance across episodes made the LoRA's character anchors fight
   themselves at training time. Solution: switch from compilation
   ingestion to **hero-scene ingestion** — hand-pick 1-3 long continuous
   scenes per setting from the *same* episode, where wardrobe / lighting
   / camera setup are deterministic. v3 uses two scenes from S2E8 "The
   Apartment" + one diner scene as anchor footage.

8. **"Trim to longer half" still left within-clip cuts in survivor
   clips.** When the verifier said "cut at 1.2s of a 5s clip, conf=0.95",
   we trimmed to the 3.8s post-cut half — but if the verifier's *time
   estimate* was off, the cut still survived in the kept half. Empirically
   ~10-15% of trimmed clips still contained a visible cut. Solution:
   **strict mode** rejects any clip with a detected cut, no trimming.
   Trade-off: smaller dataset, but every kept clip is single-shot.

#### v3 strict-mode policy (current default)

| Parameter | Lenient (v2/early-v3) | Strict (current) |
|---|---|---|
| ffmpeg scene threshold | `scene > 0.3` | `scene > 0.15` |
| Verifier confidence threshold | `conf >= 0.6` | `conf >= 0.4` |
| On detected cut | trim to longer half | **REJECT** |

Why each lever moves:
- **Lower scene threshold** surfaces more shot boundaries upfront, so
  fewer aligned 5s windows accidentally span a cut. The scene boundaries
  ffmpeg returns become natural split points; we keep them.
- **Lower confidence threshold** widens the rejection net — fewer false
  negatives at the cost of more false positives. False positives are
  cheap (lose a 5s clip we'd have kept); false negatives are expensive
  (a contaminated clip in training).
- **Reject not trim** because the verifier's cut-timestamp estimate is
  approximate. Trimming based on it ≈ 10% of the time still leaves a
  cut in the kept half.

---

## Cuts policy — when, why, and what's appropriate

Scene-LoRAs (what we're building) want **zero within-clip cuts**:

- The LoRA's training objective is "this 5s clip is what `jerrys_apt`
  looks like." A within-clip cut tells the LoRA that `jerrys_apt`
  spontaneously transitions, which it then reproduces at inference as
  uncontrollable mid-clip jumps.
- LTX 2.3's base model is trained on continuous shots. A scene-LoRA
  with cuts fights the base prior, which is a waste of training capacity.
- "Cut variety" is captured at inference via multi-shot workflows (see
  hivemind notes: Jonathan's WhatDreamsCost FFLF Custom Audio Workflow),
  not via training data.

Different objectives that *do* benefit from cut data:

- **Cut-control IC-LoRAs.** A separate LoRA whose explicit purpose is to
  produce a cinematic cut between two input shots. Training data is
  pairs of shots, not single-shot clips, and the caption explicitly
  describes the cut.
- **Trailer/montage LoRAs.** A LoRA learning the *editing style* of
  trailers (rapid cuts, hard transitions). Different problem; train on
  full montage sequences with cut-aware captions.

For scene/character/style LoRAs (90% of use cases): **strict no-cuts
is the right policy**. If you find yourself wanting cuts in training,
re-examine — usually the right answer is a multi-shot inference
workflow + a clean scene-LoRA, not a contaminated single LoRA.

### Future work: `--cuts` setting in the orchestrator CLI

Once the strict mode pipeline is validated, expose this as a top-level
setting that abstracts the underlying tuning:

```
--cuts strict    # default. scene>0.15, conf>=0.0, reject on cut. Smallest, cleanest dataset.
--cuts balanced  # scene>0.3, conf>=0.6, trim on cut. Larger dataset, occasional cut survives.
--cuts allow     # scene>0.3, no verifier rejection. For training cut-aware LoRAs.
```

Most users should use `--cuts strict`. The `balanced` and `allow` modes
exist for advanced users who know which downstream LoRA type they're
building.

---

## Multi-LoRA architecture: one dataset, several LoRA types

The pack is designed for a stacked-LoRA inference flow, not just a single
scene-LoRA. The dataset_build pass produces *all* the artifacts needed
for several LoRA types in one collection; each LoRA trains separately;
at inference, the user composes the ones they need.

### Why scene-LoRAs alone are insufficient

A scene-LoRA learns *identity*, *style*, and *shot-type vocabulary* —
"this is what Kramer looks like in jerrys_apt as a `close_up`." It cannot
learn *transformations*:

- **Cross-shot state continuity** ("Kramer was on the stool in the wide;
  on the cut back to wide, he's still on the stool"). Requires a
  reference-image conditioning signal at inference.
- **Cinematic cuts** (the angle-pair from wide-to-over-shoulder that
  makes sitcom editing readable). The scene-LoRA can produce each shot
  type in isolation; it cannot produce the *transition* between them
  with state preservation.

These are what IC-LoRAs (image-conditioned LoRAs) are for.

### LoRA-type taxonomy and what each one needs from the dataset

| LoRA type | Job | Conditioning | Pair shape |
|---|---|---|---|
| **scene-LoRA** | identity, set, style, shot-type vocab | text only | single clip + caption |
| **angle-pair IC-LoRA** | image of moment M → new-angle 5s of same moment | last frame of prior shot | (image_A, video_B, caption_B) |
| **transition IC-LoRA** | smooth cinematic cut between two scenes | last frame of clip N | (image_A, video_B, caption_B) — cross-scene |
| **continuation IC-LoRA** | extend a 5s clip into the next 5s of the SAME shot | last 8N+1 frames | (video_A_tail, video_B, caption_B) — same scene_idx, adjacent windows |

The first three are addressable from our current dataset shape. The
fourth needs a slight extraction tweak (tail frames vs last frame) but
no new VLM calls.

### Pair-data extraction (current implementation)

After the main strict-mode pipeline writes single-clip artifacts under
`accepted/<bucket>/<id>.mp4` + `.caption.json`, a post-process step
walks the accepted clips ordered by (`video_id`, `scene_idx`,
`window_idx`) and:

1. Extracts the **last frame** of clip N as `<clip_N+1>.previous_frame.jpg`
   — same resolution as the target clip (IC-LoRA dimension match).
2. Records the pair in `runs/seinfeld-dataset/pairs.manifest.json` with
   metadata: `target_clip_id`, `reference_source_clip_id`, `intra_scene`
   (whether prior and current share a PySceneDetect scene_idx).

`intra_scene=true` pairs are the **angle-pair training set**.
`intra_scene=false` pairs are the **transition training set**.

The same dataset feeds both LoRA types; the training script filters on
`intra_scene` to pick the right subset.

### Convergence targets (per hivemind: Kijai, oumoumad, crinklypaper, zlikwid)

- **Rank 32 > rank 64** for IC-LoRAs (rank 64 overfits)
- **LR 2e-5 @ 2k steps** or **5e-5 @ 1.5k steps** — both fine
- Captions can be minimal for IC-LoRAs; reference-side augmentation is
  the biggest win
- Small specialized datasets converge: 26-500 pairs is the working range
- Our ~80-150 pair sizes per LoRA type are well inside this band

### Long-term: stacked inference

Goal is a ComfyUI workflow that exposes named LoRA slots ("scene",
"angle-pair", "transition", ...) plus a single "what shall I generate"
input. Users pick which LoRAs to stack; the workflow wires conditioning
appropriately. Not yet built — currently every workflow is hand-wired
per Kijai/Ablejones/Jonathan templates from hivemind.

### Why we keep prior dataset versions on disk

For now all versions coexist:
- `runs/seinfeld-dataset/archive-v2-variety/` — v2 (lenient, multi-episode compilation)
- `runs/seinfeld-dataset/archive-v3-trim/` — v3 with trim-on-cut policy
- `runs/seinfeld-dataset/accepted/` — current (v3 strict no-cuts on 3 hero scenes)

This means we can A/B train if we want — but the current `accepted/`
tree is the intended training corpus.

---


CAPTIONING.md is the caption-shape contract. This file is the
*clip-quality* contract: the rules that make sure every clip going into
training is one continuous shot, in-domain, and not contaminated by
boundary artifacts. If you change quality policy, change THIS file first,
then `dataset_build/run.py` follows.

## Principle: a training clip is one continuous shot, period

The LoRA's objective tells it "this 8-second video is what `jerrys_apt`
looks like." If frame 7.5 of an 8-second clip is suddenly Monk's diner,
the LoRA bakes that visual surprise into its representation of
`jerrys_apt`. We will not ship training data that contains within-clip
scene changes, even small ones.

## Why PySceneDetect alone is not enough

`builtin.scenes` runs PySceneDetect's `ContentDetector` on the source
video. It's reliable on clean broadcast footage but has documented failure
modes on the kind of YouTube material we ingest:

1. **Compilation re-encoding artifacts.** Compilation channels often add a
   ~10-frame cross-dissolve or fade-to-black at splice points. ContentDetector
   reads this as gradual frame-by-frame change that never crosses its absolute
   threshold, so it doesn't fire. The actual new content then trips a
   boundary a few frames LATE, so the previous "scene" `end` ends up past
   the real cut.
2. **Variable framerate / dropped frames.** YouTube re-encodes can produce
   VFR or stretched frames that read as low frame-to-frame difference even
   across hard cuts.
3. **Within-set continuity.** A hard wide-to-medium cut on the same set
   with the same lighting may stay under threshold and never get detected.

Net effect: a non-trivial fraction of "scenes" returned by PySceneDetect
contain a trailing visual cut. Frame-diff heuristics are the wrong tool
for clips sourced from compilations.

## The fix: VLM verify + trim or reject

After cutting a candidate clip from the scenes-detector boundaries, the
orchestrator asks a video-native VLM (`builtin.video_understand` with
`--response-schema schemas/scene_verify.json`):

> "Does this clip contain a scene change? If yes, at what timestamp?"

The response schema is tiny and Gemini-compatible:

```json
{
  "has_cut": bool,
  "cut_at_s": number,           // 0 if no cut
  "cut_kind": "none|hard|soft_dissolve|fade|multiple",
  "confidence": 0-1,
  "reasoning": "short"
}
```

Decision table:

| Verifier says                                | Action                                                                                |
|----------------------------------------------|---------------------------------------------------------------------------------------|
| `has_cut: false`                             | Keep clip as-is. Proceed to transcribe + caption.                                     |
| `has_cut: true, confidence < 0.6`            | Keep clip — verifier wasn't confident enough to act on.                               |
| `has_cut: true, confidence ≥ 0.6, cut_at_s` | Re-cut from the source mp4 to the LONGER of `[clip_start, cut-margin]` or `[cut+margin, clip_end]`. Margin = 0.15s. |
| Both halves of the split below `--min-scene-s` (default 2.5s) | Reject the clip. Free the bucket slot. Continue to next scene. |

Cost: one `video_understand --mode fast` call per accepted clip
(~$0.005). On a 30-clip dataset that's about $0.15 — trivial against the
cost of training on contaminated data.

## Where this lives in the orchestrator

In `dataset_build/run.py`'s inner loop, the order is now:

```
1. _cut_clip      — first cut from PySceneDetect boundaries
2. _verify_clip_clean — VLM scene-change check (NEW)
3. _trim_to_longer_side — recut from source if verifier saw a cut (NEW)
4. _transcribe_clip — Whisper
5. _caption_clip_via_video_understand — 4-section LTX caption
```

The verifier writes a sidecar `<clip>.verify.json` so re-runs cache the
result. Content-addressed: hash includes (clip fingerprint, prompt
version, schema content). Changing any of these forces re-verification.

Trimming a clip overwrites the mp4 in place AND deletes the clip's
`.meta.json` sidecar. The caption hash already includes the clip
fingerprint, so a trimmed clip auto-invalidates its existing caption on
the next caption pass.

## What this does NOT cover

The verifier checks *within-clip* boundary contamination. It does not
catch:

- Scenes that PySceneDetect treated as one but where the clip is *entirely
  the wrong scene* (e.g., a long montage tagged as `jerrys_apt` but
  actually opening credits). The bucket-judge step is responsible for this.
- Watermarks, channel logos, lower-thirds. Add a separate executor for
  this if needed (see future-work in this doc).
- Audio anomalies (music covering dialogue, dub mismatches). Whisper
  catches some of these by producing empty / garbled transcripts; the
  caption step can flag.

## When to revisit this policy

If we move to a non-compilation source (e.g., licensed full episodes,
local DVD rips), reconsider — PySceneDetect may be fully sufficient on
clean broadcast footage and the verifier is then wasted cost. For our
current YouTube-compilation pipeline, the verifier is permanently on.

Override with `--no-scene-verify` if you need a fast path that skips it
(e.g., during pipeline development on a tiny dataset).
