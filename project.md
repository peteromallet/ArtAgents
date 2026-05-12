# Seinfeld Scene Generator — Project Plan

A demo of LTX 2.3 that generates Seinfeld-style scenes from a concept. Built on top of a fine-tuned LoRA, agent-written scripts, and Astrid's timeline composition.

## The spine: a shared vocabulary

One thing connects every stage: a **locked vocabulary** of scenes, characters, costumes, and shot types. Captions use it. Training learns it. Script-to-shot decomposition emits it. Inference prompts consume it. Get this right once, in a single element, and every downstream stage stops being a separate consistency problem.

Concretely: ~3 scenes (Jerry's apt, Monk's diner, one more), ~4 characters with 1–2 outfit variants each, ~4 shot types. Small, formulaic, Seinfeld-shaped.

## Four orchestrators in Astrid

### 1. `dataset_build` — produce the training set
Owns the bucket-fill loop. Reads a **criteria element** (bucket targets + per-bucket inclusion rules + caption template + output schemas), runs until full.

Steps, in order, wrapped in `repeat.until(buckets_full)`:
- `code`: YouTube search → candidate URLs
- `code`: yt-dlp video download (extend existing audio util)
- `code`: scene-segment (reuse `packs/builtin/scenes`)
- `code`: cheap pre-filter (length, transcript keywords)
- `attested` (agent): VLM judge → bucket assignment, schema-checked
- `attested` (agent): VLM caption using locked vocabulary, schema-checked
- **`attested` (human): review ~50 random clip+caption pairs** before training kicks off
- `code`: manifest export

### 2. `lora_train` — train the LoRA
Takes the manifest, runs LTX 2.3 training using **[ai-toolkit by ostris](https://github.com/ostris/ai-toolkit)** as the training framework.

Steps:
- `code`: provision a RunPod GPU instance (see "Cross-cutting infra" below — this should use a shared `runpod` executor at the Astrid level, not the RunPod plumbing currently buried inside vibecomfy)
- `code`: stage manifest + ai-toolkit config to the pod
- `code`: kick off training, stream logs back, pull checkpoints
- `code`: generate eval sample grid — same prompts run against baseline LTX and each candidate checkpoint, side-by-side
- **`attested` (human): review the eval grid and pick the winning checkpoint.** This is the "evals" gate — a human looks at samples and selects the LoRA that best hits the vocabulary/style targets. The produced artifact is a `chosen_checkpoint.json` with the path + notes; the gate verifies it before downstream orchestrators can use it.
- `code`: tear down the pod, register the promoted LoRA

### 3. `script_to_shots` — concept → shot list
Two `attested` (agent) steps:
- Kimi K2.6: concept → script (dialogue + scene headers)
- Kimi K2.6: script → shot JSON, **constrained to the locked vocabulary** (only emits scenes/costumes that exist)

The vocabulary constraint is what keeps script generation aligned with what the LoRA can render. Schema-check the shot JSON.

### 4. `scene_render` — shots → final video

The per-shot generation isn't single-shot — it's an **iteration loop with automated quality judging**, using the existing `video_understand` / `visual_understand` executors as judges.

For each shot, wrapped in `repeat.until(passes_judge OR max_attempts)`:
- `code`: LTX+LoRA generates the clip via vibecomfy (`external.vibecomfy.run`), seed-varied per attempt
- `attested` (agent): `video_understand` judges the clip against the shot spec — does it show the right scene, character, costume, action? Does it look like Seinfeld? Returns a structured pass/fail + reasons, schema-checked.
- If fail and attempts remain: re-roll with a refined prompt (judge's reasons inform the refinement) or a new seed
- If max attempts hit: keep the best-scoring attempt and flag it for the human review gate

After all shots are rendered:
- `code`: optional TTS or on-screen text for dialogue
- `code`: assemble clips into timeline composition in order
- **`attested` (human): review final cut, flag any shots to re-render before final render** — the human is mainly looking at the flagged shots from the per-shot loop, plus overall scene coherence
- `code`: render final video

This is the same iteration pattern that ai-tooling generally needs: generate → automated judge → human gate on what the judge couldn't catch. `visual_understand` can be used the same way on extracted keyframes if you want a faster/cheaper first-pass judge before invoking the full `video_understand`.

## How they compose

A top-level `seinfeld_demo` orchestrator chains the four as `nested` steps:

```
dataset_build → lora_train → script_to_shots → scene_render
```

These aren't strictly serial in practice. `script_to_shots` and `scene_render` can be developed and iterated against the *baseline* LTX (no LoRA) before `lora_train` finishes — they only need the vocabulary, not the LoRA itself. That's the parallelization you want.

## Astrid primitives recap

- **Executor** = one unit of work (one network call, one transformation, one artifact in / one artifact out). The capability.
- **Orchestrator** = composes executors into a workflow. Owns loop logic, conditional branching, retries-across-stages.
- **Element** = reusable schema or render building block. The criteria spec and caption template live here.

At task-run time, every step in a plan is one of:

| Step kind | Who does it | How it advances |
|---|---|---|
| `code` | nobody — deterministic argv subprocess | runs, gate verifies `produces`, moves on |
| `attested` | an agent or a human | actor runs the work, acks with identity + evidence, gate verifies `produces` |
| `nested` | another orchestrator | delegates to a child plan |

Human steps are first-class. An `attested` step with `--actor <name>` is a human step: the human does the work, runs the ack, and the gate validates the produced artifact against a schema before the run advances. Self-acks and unpinned actors are rejected.

Loops/fan-out are `repeat.until` / `repeat.for_each` wrappers on any step.

## Cross-cutting infra: port RunPod up to Astrid

RunPod provisioning currently lives inside vibecomfy. For this project (and beyond), it should be lifted up to an Astrid-level shared executor — something like `external.runpod.{provision,run,teardown}` — so any orchestrator can request a GPU pod, run work on it, and tear it down with the same plumbing.

Why now:
- `lora_train` needs RunPod for ai-toolkit training runs
- `scene_render` needs RunPod for LTX+LoRA inference (when not local)
- Future GPU-bound executors (eval grids, larger captioning runs) will need the same
- Keeping it inside vibecomfy couples GPU lifecycle to one framework; making it a peer executor lets vibecomfy *consume* it like everything else

This is a small refactor that pays back across every other workstream. Worth doing early in Phase 1.

## What lives where

- **Astrid**: criteria/vocabulary element, all four orchestrators, RunPod lifecycle executors (newly lifted from vibecomfy), all executors except the LTX/Kimi inference calls themselves
- **vibecomfy**: LTX inference workflow (with and without LoRA), invoked by Astrid executors; consumes the Astrid-level RunPod executor instead of owning that lifecycle
- **ai-toolkit (ostris)**: LTX 2.3 LoRA training, invoked by `lora_train` on a RunPod pod
- **Existing tools to reuse**: `packs/builtin/scenes`, `packs/builtin/video_understand`, `packs/builtin/visual_understand` (both as automated judges in iteration loops), possibly `pool_build` as a model for `dataset_build`, the existing YouTube audio util (extend to video), existing VLM capability

## Sequencing

**Phase 0 (1 day):** Lock the vocabulary. Write 10 example inference prompts you want to work. Reverse-engineer the caption template from those. Cheapest, highest-leverage hour in the project.

**Phase 1 (parallel, ~1 week):**
- Lift RunPod lifecycle out of vibecomfy into a shared Astrid executor (foundational — unblocks training and inference)
- Build `dataset_build` orchestrator and missing executors
- Get baseline LTX 2.3 inference running through vibecomfy (now consuming the Astrid RunPod executor)
- Prototype `script_to_shots` against baseline LTX

**Phase 2 (~1 week):**
- Run `dataset_build` end-to-end, human-review the dataset
- Wire up `lora_train` against ai-toolkit by ostris on RunPod
- Train LoRA, human picks the winning checkpoint from the eval grid
- Refine `script_to_shots` based on what baseline taught you

**Phase 3 (~3–5 days):**
- Build `scene_render` with the per-shot iteration loop (`video_understand` as judge)
- Integrate timeline composition
- End-to-end demo: concept → finished scene

## Risks, ranked

1. **Vocabulary drift between caption and inference prompt.** Mitigation: same element generates both, no free-text prompts at inference.
2. **VLM cost on dataset construction.** Mitigation: aggressive pre-filter before VLM ever sees a clip (length, transcript keywords, scene-detect metadata).
3. **Character identity across cuts within one scene.** This is the one the LoRA may not fully solve. Mitigation: prompt-locking + small vocabulary. If still bad, accept as a known demo limitation or add per-character reference-image conditioning later.
4. **Script writes shots the LoRA can't render.** Mitigation: shot-JSON schema is enum-constrained to the vocabulary — Kimi physically can't emit out-of-vocabulary shots.

## Unifying idea

One small locked vocabulary, four orchestrators that all speak it, human gates at the two places that matter (dataset quality, final cut), everything else automated and verifiable through Astrid's `produces` checks.
