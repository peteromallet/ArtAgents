---
name: seinfeld_lora_train
description: Train an LTX 2.3 LoRA on the Seinfeld dataset via ai-toolkit on RunPod — orchestrator with a human checkpoint-pick gate.
---

# Seinfeld LoRA Train

Provisions a RunPod GPU pod, stages the dataset + ai-toolkit config, runs
training, generates an eval-sample grid (baseline LTX vs each checkpoint),
**pauses** for human checkpoint selection, then (`resume`) tears the pod
down and registers the chosen LoRA.

Canonical project plan: `/project.md`.

## Pipeline

| # | Step | Executor | Notes |
|---|------|----------|-------|
| 0 | Init ai-toolkit submodule (idempotent) | `seinfeld.repo_setup` | preflight |
| 1 | Provision RunPod GPU | `external.runpod.provision` | `--ports 8675/http,22/tcp` |
| 2 | Stage manifest + ai-toolkit config; start UI | `seinfeld.aitoolkit_stage` | prints UI URL |
| 3 | Run ai-toolkit training; mirror remote log; list checkpoints | `seinfeld.aitoolkit_train` | crash-detect on CUDA OOM / NaN / RuntimeError |
| 4 | Side-by-side eval grid (baseline vs each ckpt) | `seinfeld.lora_eval_grid` | writes `index.html` |
| 5 | **Human gate** — orchestrator writes `last_run.json` with `status: PAUSED` and **exits 0** | (no executor) | user opens `eval_grid/index.html`, picks a step |
| 6 | (resume) Pull chosen `.safetensors` off the pod via `external.runpod.exec`, then teardown | `external.runpod.exec` + `external.runpod.teardown` | |
| 7 | (resume) Register chosen LoRA | `seinfeld.lora_register` | writes `registered_lora.json` |

## Human gate — exit-0 + PAUSED semantics

After step 4, the orchestrator writes `<out>/last_run.json`:

```json
{
  "status": "PAUSED",
  "pod_handle": "<abs path>",
  "staged_config": "<abs path>",
  "checkpoint_manifest": "<abs path>",
  "eval_grid_index": "<abs path>",
  "vocabulary": "<abs path>",
  "base_model_name": "ltx-2.3",
  "lora_id": "seinfeld-scene-v1",
  "out": "<abs path>"
}
```

and exits 0. The pod stays alive (the 12h `--max-runtime-seconds` ceiling
is the only guardrail — pick your checkpoint promptly). The user reviews
`eval_grid/index.html` and resumes with the chosen step.

### Resume subcommand

```bash
python3 -m astrid.packs.seinfeld.lora_train.run resume \
  --out runs/seinfeld-lora \
  --pick 1500 \
  --notes "step 1500: cleanest character identity, no over-fit"
```

Resume reads `last_run.json`, writes `chosen_checkpoint.json`, pulls the
`.safetensors` off the pod, **terminates the pod**, and invokes
`seinfeld.lora_register`.

## Tradeoff: 12-hour pod ceiling

The orchestrator passes `--max-runtime-seconds 43200` to provisioning. This
caps a single PAUSED state at 12 hours of pod time. If the human gate sits
longer (e.g. overnight + a meeting), RunPod will reap the pod and the
chosen `.safetensors` will not be recoverable on resume — the user must
re-run from scratch. The alternative is to download every checkpoint
during training (significantly slower) or extend the ceiling (more $).
12h is the chosen balance for this sprint.

## Inputs

```bash
python3 -m astrid orchestrators run seinfeld.lora_train -- \
  --manifest runs/seinfeld-dataset/provisional.manifest.json \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --out runs/seinfeld-lora
```

Notable flags:

- `--smoke` — 5-clip subset, 100 training steps, 3-prompt baseline-only eval (≈$0.50 verification run).
- `--dry-run` — preflight + local config generation; no pod work, no spend.
- `--gpu rtx-6000-ada` (default) — override with `--gpu a100-80g` etc.
- `--steps N` — override the hivemind default (2000 / smoke 100).
- `--seed 42` (default) — recorded in `registered_lora.json` for reproducibility.

## Output layout

```
runs/seinfeld-lora/
  last_run.json                # orchestrator state (PAUSED → REGISTERED on resume)
  repo_setup/                  # seinfeld.repo_setup produces
  provision/pod_handle.json
  stage/staged_config.yaml
  stage/bootstrap.sh
  stage/ui_url.txt
  train/training.log           # mirrored from pod
  train/checkpoint_manifest.json
  eval_grid/<bucket>/*.mp4
  eval_grid/index.html         # human reviews this
  chosen_checkpoint.json       # written by `resume --pick <step>`
  teardown/teardown_receipt.json
  register/registered_lora.json
```

## Notes

- ai-toolkit by ostris: https://github.com/ostris/ai-toolkit (pinned at SHA in `seinfeld.repo_setup`).
- The eval grid is what makes the human gate trustworthy — don't skip it
  even if a quick visual on one prompt looks good. `project.md` risk #3
  (character identity across cuts) is exactly what the grid is checking for.
