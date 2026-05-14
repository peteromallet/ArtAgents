# Seinfeld LoRA training plan

End-to-end plan for the multi-LoRA inference stack: what's built, what to
train, in what order, and how to validate at each step. Decisions
grounded in Banodoco hivemind community findings (Kijai, Ablejones,
oumoumad, zlikwid, crinklypaper, mamad8, 42hub, fredbliss). Cross-refs:
`DATASET_QUALITY.md` (clip-quality policy), `CAPTIONING.md`
(caption-shape contract).

---

## 1. Current state — what's already built

### v3 strict no-cuts dataset

Three hero sources, all processed through the strict pipeline
(`scene>0.15` upstream, paranoid VLM verifier, `conf>=0.0` reject-on-cut):

| Source | Episode | Bucket | Clips |
|---|---|---|---|
| `BYgFmP03biw` "Elaine Needs $5K" | S2E8 The Apartment | jerrys_apt | 71 |
| `VMplMXoqnaY` "Kramer Tries Mousse" | S2E8 The Apartment | jerrys_apt | 30 |
| `uEvOU2HKhzw` (from 2:30) | hero diner scene | monks_diner | 30 |
| **Total** | | | **131** |

Two apt sources are deliberately from the **same episode** so wardrobe /
lighting / cinematography are deterministic across them. The diner source
contributes a separate setting; future work may add a second diner hero
scene for additional cinematic variety.

### Pair dataset for IC-LoRA training

Post-process step walks accepted clips ordered by (`video_id`,
`scene_idx`, `window_idx`) and pairs each clip with its
chronologically-prior accepted clip in the same source:

| Pair type | Count | Use |
|---|---|---|
| **intra-scene** (same PySceneDetect scene_idx) | 33 | Angle-pair IC-LoRA: image of moment M → new-angle 5s of same moment |
| **cross-scene** (different scene_idx) | 95 | Transition IC-LoRA: smooth cinematic cut between moments |
| **Total** | 128 | (131 clips − 3 first-of-source clips) |

Reference images are extracted at the target clip's resolution (IC-LoRA
dimension-match requirement). Each target clip has a co-located
`<id>.previous_frame.jpg`. Manifest at `pairs.manifest.json` with
`intra_scene` filter.

### Artifacts on disk (per accepted clip)

```
runs/seinfeld-dataset/accepted/<bucket>/
  <clip_id>.mp4                 # the 5s training video
  <clip_id>.caption.json        # rich 4-section caption (Scene / Speech / Sounds / Style)
  <clip_id>.previous_frame.jpg  # last frame of immediately-prior accepted clip (IC-LoRA reference)
  <clip_id>.verify.json         # VLM scene-verify sidecar (debugging)
```

Manifests at the dataset root:

```
runs/seinfeld-dataset/
  state.json                       # pipeline-local state
  provisional.manifest.json        # single-clip manifest (scene-LoRA training)
  pairs.manifest.json              # pair manifest (IC-LoRA training)
```

---

## 2. Architecture — the multi-LoRA inference stack

The pack is built for a **stacked-LoRA** inference flow, not a single
all-purpose LoRA. One dataset produces all the data needed for several
LoRA types; each LoRA trains separately; at inference, the user composes
the ones they need for the task.

### Why stacking instead of one mega-LoRA

A single scene/character LoRA learns *identity, style, set, shot-type
vocabulary*. It cannot learn *transformations*:

- Cross-shot **state continuity** ("Kramer was on the stool in the wide;
  on the cut back to wide, he's still on the stool")
- Cinematic **angle-pair cuts** (wide → over-shoulder of the same moment,
  with character state preserved)
- Smooth **scene transitions** (cut from one conversation moment to
  another)

These are different transformations that share a base scene-LoRA but
need their own specialized weights.

### LoRA types and what each needs

| LoRA | Job | Conditioning | Pair shape | Dataset filter |
|---|---|---|---|---|
| **scene-LoRA** | identity, set, style, shot-type vocab | text only | single clip + caption | `provisional.manifest.json` |
| **angle-pair IC-LoRA** | image of moment M → new-angle 5s of same moment | last frame of prior shot | (image, video, caption) | `pairs.manifest.json` where `intra_scene=true` |
| **transition IC-LoRA** | smooth cinematic cut between scenes | last frame of clip N | (image, video, caption) | `pairs.manifest.json` where `intra_scene=false` |
| **continuation IC-LoRA** _(future)_ | extend a 5s clip into next 5s of same shot | last 8N+1 frames of clip A | (video tail, video, caption) | adjacent windows, same scene_idx |

### Inference workflow shape

Per Lightricks' shipped IC-LoRA templates (HDR / LipDub / Upscale —
isomorphic graphs, confirmed by zlikwid in hivemind):

```
Load LTX 2.3 base
  ↓
Load LoRA stack: scene-LoRA  +  angle-pair-IC-LoRA  (+ transition-IC-LoRA, +continuation-IC-LoRA, etc.)
  ↓
Load reference image: previous_shot_last_frame.jpg
  ↓
LTXVAddGuide(frame_index=-1)   # reference relevant to all frames
  ↓
Prompt: "close_up of Kramer in jerrys_apt, wearing vintage shirt and pleated pants"
  ↓
EmptyLTXVLatentVideo → KSampler → VAE Decode → 5s mp4
```

The workflow JSON ships with `ComfyUI-LTXVideo`; we don't build from
scratch. Per zlikwid: *"It's literally the default LTX hdr ic-lora
workflow. VHS load video press go."* Drop in our LoRA weights, point at
the reference image, run.

**Multi-shot scene assembly:**

```
shot_1 = generate_with_scene_lora(prompt_1)
ref_1 = last_frame(shot_1)
shot_2 = generate_with_scene_lora_and_angle_pair_ic_lora(prompt_2, reference=ref_1)
ref_2 = last_frame(shot_2)
shot_3 = generate_with_scene_lora_and_angle_pair_ic_lora(prompt_3, reference=ref_2)
...
```

Stitch in editor or with Jonathan's multi-shot workflow.

---

## 3. Training plan

### Hyperparameters (hivemind-validated)

**Scene-LoRA** (standard LTX 2.3 LoRA training):
- Tool: Lightricks `LTX-2` training scripts (per cseti007 in hivemind)
- Or: ai-toolkit / musubi
- Rank: 32 or 64 (Kijai: rank 32 generally safer, rank 64 + `cosine_with_min_lr` scheduler also works)
- LR: 2e-5 @ 2000 steps **or** 5e-5 @ 1500 steps
- Caption format: existing `v3_window_local` 4-section captions
- Validation cadence: every 500 steps

**Angle-pair IC-LoRA** (new training):
- Tool: ai-toolkit (zlikwid used this for upscale IC-LoRA)
- Or: official LTX IC-LoRA training scripts in Lightricks' repo
- Rank: **32** (Kijai: 64 caused overfitting like "arms appearing from ears")
- LR: 2e-5 @ 2000 steps **or** 5e-5 @ 1500 steps
- Reference placement: match the training convention to inference — most
  IC-LoRAs use `frame_index=-1` ("reference for last frame") or
  initial-8-frames placement
- **Critical:** `reference_downscale` parameter must match between
  training and inference (Kijai community finding 2026-05-04)
- Caption format: **minimal** — `"<shot_type> of <characters> in <scene>"`.
  Per oumoumad: *"a fixed caption like 'clean footage' or probably
  nothing at all would've still worked"* — IC-LoRAs lean on the
  reference image, not text. We'll keep our minimal captions and skip
  the rich 4-section format.
- Dataset: 33 intra-scene pairs (likely sufficient — crinklypaper got
  results with 26 motion-blur pairs)

**Transition IC-LoRA** (optional later):
- Same as angle-pair, but dataset = 95 cross-scene pairs
- Lower priority — only train if multi-shot generation needs
  scene-level transitions vs same-moment angle changes

### Ostris tutorial findings (LTX-2.3 character LoRA, YouTube `JQIl8DFTL1M`)

Ostris's own end-to-end recipe for an LTX-2.3 character LoRA in AI Toolkit
(the same workflow behind his George Costanza LoRA). Cross-checked against
our hivemind defaults; deltas folded into `aitoolkit_stage/run.py`:

- **`cache_latents_to_disk: true` — non-negotiable for video LoRAs.** Ostris:
  "+9 seconds extra to the training step" without it. Applied.
- **Multi-bucket resolution `[512, 768]` from the start**, add `1024` for a
  later/overnight pass. Applied (was `[512]`).
- **121 frames @ 24fps** (`frames = sec*24 + 1`), matching our 5s clip length.
  Was 97. Applied.
- **Timestep schedule: high-noise first, switch to balanced near the end** —
  "don't go to low-noise, it'll break down your high-noise." Our template
  uses `noise_scheduler: flowmatch` with no explicit timestep weighting;
  TODO: verify whether ai-toolkit's LTX2 backend exposes a `timestep_type`
  / high-noise toggle and wire it in.
- **Steps**: he sampled to 5000, said 3000 already looked good. Our default
  is 2000 — fine for smoke, but plan to bump to 3000 for full runs and
  validate at 1500/2000/3000.
- **Quantization**: `float8` (our template has `quantize: true` — verify the
  active dtype on a real run).
- **Burn-in vs describe** (caption principle): omitted things get burned
  into the LoRA; described things stay free. He omits clothing/scene to
  burn them in. **We deliberately do the opposite** — describing scene
  and outfit keeps `jerrys_apt`/`monks_diner` as inference-time switches.
  See `CAPTIONING.md`.
- **Inference**: train on base LTX 2.3, generate with **distilled (turbo)**.
  Captions also influence: don't normalize "gonna" → "going to", caption
  verbatim so disfluencies can be prompted out later.

Transcript reference: video ID `JQIl8DFTL1M` ("How to Train a LTX-2.3
Character LoRA with AI Toolkit"). Auto-captions can be re-pulled with
`PYENV_VERSION=3.11.11 yt-dlp --write-auto-sub --sub-lang en --skip-download
--convert-subs srt -o ostris.%(ext)s "https://www.youtube.com/watch?v=JQIl8DFTL1M"`.

### Reference-side augmentation (Kijai: "the main win")

Per Kijai (2026-05-06 daily summary): *"dataset augmentation on the
reference side was the main win for IC-LoRA training, rather than
training parameter adjustments."*

Plan: produce 3-5 reference variants per pair before training:

- Time variants: `T-0.0s` (last frame), `T-0.2s`, `T-0.5s`, `T-1.0s` from
  the prior clip
- Spatial variants: center-crop 90%, slight brightness/contrast jitter
- **No** horizontal flips (would mirror character faces)

For 33 intra-scene pairs × 5 variants = ~165 effective training samples.

### Estimated training cost

| LoRA | Steps | GPU hours (A100) | Approx $ |
|---|---|---|---|
| scene-LoRA | 1500-2000 | 4-6 | $5-10 |
| angle-pair IC-LoRA | 1500-2000 | 3-5 | $5-10 |
| transition IC-LoRA | 1500-2000 | 3-5 | $5-10 |

All three: ~$15-30 total on RunPod A100. Modest.

### Training order

1. **scene-LoRA first** — foundation. Lock the identity / style / shot-type
   vocab. Validate on text-only prompts.
2. **angle-pair IC-LoRA second** — only after scene-LoRA passes
   validation. Builds on top of scene-LoRA's character/setting priors.
3. **transition IC-LoRA last** — and only if angle-pair + scene-LoRA
   together fall short on cross-moment cuts.

---

## 4. Inference plan — Layer 1 vs Layer 3

### Important caveat from hivemind (mamad8, 2026-05-05)

> *"the i2v capability is much stronger than the ic-lora guidance for
> reference following"*

This is a real finding from the community. **The base LTX 2.3 i2v
capability may already do what we want, without a custom IC-LoRA.**

We should test **Layer 1** (cheap, no new training) before committing
GPU hours to Layer 3 (angle-pair IC-LoRA).

### Layer 1 — i2v + scene-LoRA + reference image

```
Load LTX 2.3 base + scene-LoRA  (no IC-LoRA)
Load reference image: previous_shot_last_frame.jpg
LTXVImgToVideoInplaceKJ (image, prompt) → produces 5s video
   ↑
   Use the KJ variant (not core LTXVImgToVideoInplace) per Ablejones —
   the core node clobbers noise masks and doesn't clone latents properly
```

This is essentially "image-to-video" with the reference image as the
start. The scene-LoRA provides character identity. The prompt drives the
shot_type / framing.

**If Layer 1 produces high-quality multi-shot continuations with state
preservation → we don't need the IC-LoRA.**

### Layer 2 — Multi-shot orchestration workflow

Jonathan's `WhatDreamsCost FFLF Custom Audio Workflow`
(`https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/blob/main/example_workflows/LTX%20I2V%20FFLF%20Custom%20Audio%20Workflow%20-%20SUPPORTS%20LATEST%20COMFYUI%20VERSION%20-%20V3.json`):

- Multiple image+prompt slots in one workflow run
- Output: one continuous video with controlled cuts at specified frame times
- Compose with our scene-LoRA loaded

Useful for batch generation of multi-shot scenes. Doesn't require any
IC-LoRA either.

### Layer 3 — Angle-pair IC-LoRA (only if needed)

Only train and deploy this if Layer 1 + Layer 2 fall short on:

- Reverse-angle cuts where Layer 1's i2v can't infer the camera flip
- Specific TV-editing styles (e.g., consistent OTS↔reverse-OTS pairs)
- Same-moment state preservation that i2v's prior doesn't capture

If we get to Layer 3, the inference shape is the same as Layer 1 but
with the IC-LoRA stacked on top of the scene-LoRA, and reference
injection through `LTXVAddGuide(frame_index=-1)` instead of
`LTXVImgToVideoInplaceKJ`.

---

## 5. Validation gates

### Gate 1 — Pre-training: dataset quality review

Before starting any training:

- [ ] Spot-check 20-30 clips in the human_review reviewer
- [ ] Confirm zero within-clip cuts (the v3 strict mode's whole point)
- [ ] Confirm captions match the visual content (no bucket mis-labels)
- [ ] Confirm anchor phrases are consistent within character across clips
- [ ] Reject any obvious failures via reviewer

### Gate 2 — Post-scene-LoRA: text-only inference

After scene-LoRA training:

- [ ] Generate 5s clips for each shot_type × each character combination
- [ ] Confirm character identity is preserved
- [ ] Confirm scene token (`jerrys_apt`, `monks_diner`) drives the right set
- [ ] Confirm shot_type tokens (`close_up`, `wide`, `two_shot`, etc.) produce the right framing
- [ ] Compare against base LTX 2.3 with the same prompts — should be qualitatively more "Seinfeld"

If this fails, the dataset has problems and Phase 2+ doesn't help.

### Gate 3 — Layer 1 (i2v) reference-following test

Before training angle-pair IC-LoRA, test Layer 1:

- [ ] Pick 5 intra-scene pairs from our dataset
- [ ] For each: feed the reference frame + the target's caption into
      `LTXVImgToVideoInplaceKJ` with scene-LoRA loaded
- [ ] Compare the generated clip to the original target clip
- [ ] Score state preservation: is Kramer in the same position? Same outfit?
      Same lighting?
- [ ] If 4/5 are acceptable → Layer 1 is enough. Skip Phase 3.
- [ ] If ≤2/5 → Phase 3 (angle-pair IC-LoRA) is justified.

### Gate 4 — Post-IC-LoRA (if trained): comparison

- [ ] Generate the same 5 test pairs through Layer 1 (i2v) and Layer 3 (IC-LoRA)
- [ ] A/B compare. IC-LoRA should be measurably better on state preservation.
- [ ] If not measurably better → roll back. The base i2v wins on simplicity.

---

## 6. Open decisions

1. **Training tooling**: Lightricks `LTX-2` repo vs ai-toolkit vs musubi.
   ai-toolkit has known IC-LoRA support (zlikwid used it for upscale).
   Lightricks docs are the canonical reference. **Default: try the
   official Lightricks training scripts first.**
2. **Compute provider**: RunPod (A100) is the community default. Could
   also try Colab/local if available.
3. **More dataset variety**: do we need a second diner hero scene
   (currently 30 clips, half the apt count)? Likely yes for a balanced
   bucket distribution. But for the first training pass, ~30 clips is
   fine.
4. **Caption strategy for IC-LoRA**: minimal vs rich vs reference-aware
   ("the same scene from a different angle: ..."). Per oumoumad's
   finding, minimal probably works. Easy to A/B test.
5. **Astrid project wiring**: currently the dataset lives in
   `runs/seinfeld-dataset/` as a plain pack-output dir. Not registered
   as an Astrid project (`project.json`). Defer until sprint work on the
   project schema stabilizes.

---

## 7. Next steps for the user

In order:

### Right now (no compute needed)

1. **Review the v3 dataset in the reviewer** (currently open at the most
   recent token in `runs/seinfeld-dataset/reviewer.log`). Spot-check
   ~20-30 clips. Reject any with surviving cuts or misaligned captions.
2. **Decide whether to add more diner footage.** Current monks_diner
   bucket = 30 clips. If you want bucket balance, find one more diner
   hero scene from the same era and re-run the strict pipeline pointing
   at it (same `/tmp/process_hero_scenes_strict.py` mechanism, just add
   to `SOURCES`).

### Before any training (lightweight prep)

3. **Pick training tooling**: clone Lightricks' `LTX-2` repo, or set up
   ai-toolkit. The pack already produces the right manifest shapes;
   pointing the trainer at `provisional.manifest.json` is the integration
   point.
4. **Get GPU compute**: RunPod A100 spot is ~$1.50/hr. Budget ~$15-30
   for the full sequence (scene-LoRA + angle-pair IC-LoRA + transition
   IC-LoRA if needed).
5. **Implement reference-side augmentation** (optional Phase 2.5): a
   small extension of `/tmp/extract_pairs.py` to produce time-offset and
   crop variants. Per Kijai, this is the biggest IC-LoRA quality lever.

### Phase 1 — scene-LoRA

6. **Train scene-LoRA** on `provisional.manifest.json`. Rank 32, LR 2e-5,
   2000 steps. Validate at every 500 steps.
7. **Pass Gate 2** (text-only inference test). If fail → review dataset,
   probably caption mis-alignment issues.

### Phase 2 — Layer 1 reference-following test

8. **Test i2v + scene-LoRA + reference image** on 5 intra-scene pairs.
9. **Pass Gate 3** decision: ≥4/5 acceptable → ship Layer 1, skip
   Phase 3. ≤2/5 → train IC-LoRA.

### Phase 3 — angle-pair IC-LoRA (conditional)

10. **Augment reference images** if not already done.
11. **Train angle-pair IC-LoRA** on `pairs.manifest.json` filtered to
    `intra_scene=true`. Rank 32, LR 2e-5, 2000 steps.
12. **Pass Gate 4** A/B test against Layer 1.

### Phase 4 — Multi-shot inference

13. **Wire up Jonathan's multi-shot workflow** with the LoRA stack
    (scene + angle-pair IC if trained).
14. **Generate full Seinfeld-style scenes**: 3-5 shots, one continuous
    moment, mixed shot_types.

### Astrid pack integration (deferred)

15. After the LoRA stack is proven, formalize the inference flow as an
    Astrid pack (`astrid/packs/seinfeld/infer/`) with the workflow
    template and CLI wrapper. Tie into the project schema once the
    sprint-X reshape stabilizes.
