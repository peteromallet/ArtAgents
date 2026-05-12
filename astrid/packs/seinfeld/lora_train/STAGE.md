---
name: seinfeld_lora_train
description: Train an LTX 2.3 LoRA on the Seinfeld dataset via ai-toolkit on RunPod — outline + executor map.
---

# Seinfeld LoRA Train — Outline

Skeleton orchestrator. Implementation is **Phase 2**; this doc exists so the
shape is captured while we work on `dataset_build`.

Canonical project plan: `/project.md`.

## Pipeline (steps in order)

| # | Step | Kind | Tool | Status |
|---|------|------|------|--------|
| 1 | Provision RunPod GPU | `code` | `external.runpod.provision` | **missing** — port from vibecomfy |
| 2 | Stage manifest + ai-toolkit config to pod | `code` | `seinfeld.aitoolkit_stage` | **missing** |
| 3 | Run ai-toolkit (ostris) training, stream logs, pull checkpoints | `code` | `seinfeld.aitoolkit_train` | **missing** |
| 4 | Generate side-by-side eval sample grid (baseline LTX vs each ckpt) | `code` | `seinfeld.lora_eval_grid` | **missing** |
| 5 | Human reviews grid, picks winning checkpoint | `attested` (human) | step-level gate, no executor needed | spec'd |
| 6 | Tear down pod | `code` | `external.runpod.teardown` | **missing** — port from vibecomfy |
| 7 | Register chosen LoRA | `code` | `seinfeld.lora_register` | **missing** |

## Dependencies on upstream work

- **`dataset_build`** must produce `manifest.json` in ai-toolkit's expected
  format (TBD — check ai-toolkit docs).
- **RunPod port from vibecomfy** is a hard prerequisite. project.md flags
  this as the foundational Phase 1 refactor. Don't start lora_train work
  until that's done.
- **Vocabulary lock.** Eval grid prompts come from the SAME locked vocab
  as captions, otherwise the grid doesn't measure anything meaningful.

## Inputs

```bash
python3 -m astrid orchestrators run seinfeld.lora_train -- \
  --manifest runs/seinfeld-dataset/manifest.json \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --base-model ltx-2.3 \
  --rank 32 --steps 4000 \
  --gpu a100-80g \
  --out runs/seinfeld-lora
```

## Output

```
runs/seinfeld-lora/
  pod_id.txt
  training.log
  checkpoints/<step>/*.safetensors
  eval_grid/<step>/<prompt>.mp4    # baseline LTX + each ckpt, same prompts
  eval_grid/index.html             # side-by-side viewer
  chosen_checkpoint.json           # human-produced via attested gate
  registered_lora.json             # final pointer for downstream orchestrators
```

## Notes

- ai-toolkit by ostris: https://github.com/ostris/ai-toolkit
- The eval grid is what makes the human gate trustworthy — don't skip it
  even if a quick visual on one prompt looks good. project.md risk #3
  (character identity across cuts) is exactly what the grid is checking for.
