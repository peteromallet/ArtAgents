# Brief — Seinfeld training launcher on RunPod via ai-toolkit

**Megaplan profile**: `led//medium +prep`

Build the orchestration layer that takes the existing `runs/seinfeld-dataset/` (131 accepted clips + `provisional.manifest.json`) and trains an LTX 2.3 scene-LoRA on a RunPod GPU pod using Ostris's `ai-toolkit`, with the AI Toolkit UI exposed for live sample review.

## Goal

A single command — `python3 -m astrid orchestrators run seinfeld.train` — that:

1. Generates a valid `ai-toolkit` job config from `provisional.manifest.json`.
2. Provisions a RunPod GPU pod with the right docker image and port forwarding.
3. Uploads the dataset + config.
4. Starts the AI Toolkit UI and prints its public URL.
5. Runs training; user monitors live samples in the browser.
6. On clean teardown, downloads checkpoints + final samples.

This sprint covers Phase 1 of `astrid/packs/seinfeld/TRAINING_PLAN.md` (scene-LoRA). Phase 2 (angle-pair IC-LoRA) is explicitly **out of scope** but the architecture should leave a clean slot for a future `external.musubi.train_runpod` executor.

## Architecture (already decided — do not re-design)

Split by reuse boundary. Three new directories, one patch.

```
astrid/packs/
├── external/
│   ├── runpod/                    ← EXISTING — patch only (see below)
│   └── ai_toolkit/                ← NEW pack
│       ├── pack.yaml
│       ├── upstream/              ← git submodule: ostris/ai-toolkit
│       └── train_runpod/          ← NEW executor
│           ├── executor.yaml
│           ├── STAGE.md
│           └── run.py
└── seinfeld/
    └── training/                  ← NEW subdir of existing pack
        ├── config_gen/            ← NEW executor (seinfeld → ai-toolkit config)
        │   ├── executor.yaml
        │   ├── STAGE.md
        │   └── run.py
        └── train/                 ← NEW orchestrator
            ├── orchestrator.yaml
            ├── STAGE.md
            └── run.py
```

**Why this split** (don't re-litigate):

- `external/runpod/` is generic lifecycle and stays generic.
- `external/ai_toolkit/` is generic "ai-toolkit training on RunPod" — reusable for any future LoRA project (music videos, interviews, etc.). Its `train_runpod` executor **delegates to** `external.runpod.session` (importable from the same package); it does not re-implement provisioning.
- `seinfeld/training/config_gen/` is the only seinfeld-specific piece (vocab, bucket conventions, caption format).
- `seinfeld/training/train/` is the user-facing orchestrator that composes config_gen → external.ai_toolkit.train_runpod. Per `AGENTS.md`, orchestrators may call orchestrators or executors; executors must not call orchestrators.

## Files to create / modify

### Patch: `astrid/packs/external/runpod/` (small)

The current `run.py` hardcodes `"ports": "8888/http,22/tcp"` at lines 192 and 461. Surface `ports` as a configurable input on both `provision` and `session`:

- Add `--ports` CLI argument (default keeps current value).
- Thread it into the `handle["config_snapshot"]["ports"]` field.
- Verify how `runpod-lifecycle`'s `RunPodConfig` / `launch()` actually consumes ports — if `RunPodConfig` doesn't accept a `ports` field today, the patch may need a small upstream PR to `peteromallet/runpod-lifecycle`. **Prep phase should resolve this** before committing to an implementation.
- Update `executor.yaml` to list `ports` as an input on both `external.runpod.provision` and `external.runpod.session`.
- Do not change the default behavior for callers that don't pass `--ports`.

### New executor: `external/ai_toolkit/train_runpod/`

Delegates to `external.runpod.session` with ai-toolkit-shaped defaults:

- `image`: `ostris/ai-toolkit:latest` (prep should confirm the tag and the port the UI binds to on container boot — typically 8675; verify).
- `ports`: `<ui_port>/http,22/tcp` (passed through to the patched runpod executor).
- `gpu_type` default: `NVIDIA RTX 6000 Ada` (avoid Blackwell — hivemind flagged training-quality regressions on 50-series across multiple trainers).
- `container_disk_gb`: 200.
- `remote_script`: a generated `bootstrap.sh` that:
  - Writes `/workspace/config.yaml` from the input file.
  - Symlinks `/workspace/dataset/` to the uploaded dataset.
  - Starts the AI Toolkit UI (`python ai_toolkit/run.py` or whatever Ostris's entrypoint is — prep should confirm).
  - Launches the training job referencing the config.
- Inputs: `dataset_dir` (path), `config_file` (path to generated YAML), `gpu_type` (optional), `max_runtime_seconds` (optional).
- Outputs: `checkpoint_dir`, `sample_dir`, `cost`, plus the same `pod_handle.json` breadcrumb that `external.runpod.session` writes.
- Prints the AI Toolkit UI URL prominently after pod-ready: `https://<pod-id>-<ui_port>.proxy.runpod.net`.

The implementation should literally import and call the helpers used by `external.runpod.session` (look at `cmd_session` in `astrid/packs/external/runpod/run.py` — it uses `runpod_lifecycle.{launch, get_pod, ship_and_run_detached, RunPodConfig}` directly). Do not subprocess out to the runpod executor — call the same functions.

### New executor: `seinfeld/training/config_gen/`

Pure local. No network. Inputs:

- `manifest`: path to `runs/seinfeld-dataset/provisional.manifest.json` (default).
- `vocabulary`: path to `astrid/packs/seinfeld/vocabulary.yaml` (default).
- `out`: where to write `ai_toolkit_config.yaml`.

Reads the manifest's `clips[]` (each has `caption_file`, `clip_file`, `bucket`, `duration_s`, etc.) and produces an ai-toolkit job YAML. Bake in hivemind-validated defaults (overridable via CLI flags):

- **Model**: LTX 2.3 (verify the exact ai-toolkit model identifier in the upstream `config/examples/` directory during prep).
- **Resolution**: 512×768 (siraxe/SmaX recommendation).
- **Frames per clip**: 97 (LTX 1+8N rule, ≤5s at 24fps).
- **fps**: 24.
- **LR**: 2e-5.
- **Steps**: 2000.
- **Save every / sample every**: 250 steps.
- **Rank**: 32 (Kijai — rank 32 > rank 64 for small datasets).
- **Batch size**: 1, gradient accumulation 4.
- **Bucketing**: enabled, no crop (Xodroc).
- **Captions**: pull from each clip's `.caption.json` sidecar (already on disk).
- **Trigger / no trigger token**: caption-only (oumoumad confirmed minimal captions work).

The exact YAML schema must match what ai-toolkit accepts — **prep phase should read `external/ai_toolkit/upstream/config/examples/` to nail down field names and structure**. Don't invent fields.

### New orchestrator: `seinfeld/training/train/`

Thin composition:

1. Run `seinfeld.training.config_gen` → produces `ai_toolkit_config.yaml`.
2. Run `external.ai_toolkit.train_runpod` with `dataset_dir=runs/seinfeld-dataset/accepted/`, `config_file=<from step 1>`.
3. Print final summary (checkpoint location, sample URL while pod alive, total cost from cost.json).

Per `AGENTS.md` orchestrator template at `docs/templates/orchestrator/`.

### Submodule

```bash
git submodule add https://github.com/ostris/ai-toolkit astrid/packs/external/ai_toolkit/upstream
```

Pin to a recent commit confirmed to support LTX 2.3 (the [LTX 2.3 on 5090 Reddit post](https://www.reddit.com/r/StableDiffusion/comments/1swrs76/) is reference; prep should pick a specific SHA).

The upstream is used at **plan/build time** for config schema reference. The docker image on the pod has its own copy at runtime. Do not import ai-toolkit Python at runtime in this repo.

### AGENTS.md additions (small)

Three short subsections — not a rewrite:

1. **Vendored deps as submodules** — pattern: `astrid/packs/<scope>/<pack>/upstream/` is where a pack's upstream git submodule lives.
2. **Factoring threshold** — when a capability is reusable by a second domain identically, factor into its own pack now rather than nesting inside the first user.
3. **Long-running interactive sessions** — for executors that expose a port and stay alive (training UI, ComfyUI server, etc.): they're still executors; the open port is a side-effect of the run; teardown still flows through `try/finally`. Cross-reference `external.ai_toolkit.train_runpod` as the canonical example.

## Pattern to mirror

Read these files at prep time — they are the canonical examples to copy:

- `astrid/packs/external/runpod/run.py` — `cmd_session` (lines 384-583) is the lifecycle pattern. The new ai_toolkit executor mirrors this shape (provision → write breadcrumb → exec → download → finally teardown).
- `astrid/packs/external/runpod/executor.yaml` — the YAML schema for an executor.
- `astrid/packs/external/runpod/STAGE.md` — short STAGE.md form.
- `astrid/packs/external/vibecomfy/` — another external-service wrapper; cross-reference if anything's unclear.
- `astrid/packs/builtin/iteration_video/` — example of an orchestrator that composes multiple executors. Use as the orchestrator template reference.

## Hivemind defaults to bake in

From the conversation's hivemind queries — already validated against Banodoco Discord:

| Setting | Value | Source |
|---|---|---|
| Frames per clip | 97 | siraxe / SmaX via BNDC daily summary |
| Resolution | 512×768 | siraxe / SmaX |
| Rank | 32 | Kijai (rank 32 > rank 64 for these dataset sizes) |
| LR | 2e-5 | Standard for LTX LoRAs |
| Steps | 2000 | Daviejg / community consensus |
| fps | 24 | Daviejg |
| Bucketing | enabled | Xodroc — "I normally train with ai-toolkit without needing to crop" |
| Captions | minimal, per-clip | oumoumad / crinklypaper |
| GPU class | RTX 6000 Ada or A100 80GB | Avoid Blackwell — BNDC daily summary flagged training regressions |
| Min dataset | 50+ clips | cseti007 (we have 131 ✓) |

## Constraints / non-goals

- **No IC-LoRA training**. AI Toolkit doesn't support it; we're explicitly deferring. Don't try to wedge it in.
- **No new RunPod template**. Use Ostris's existing docker image / public template if applicable. Don't build our own.
- **No new orchestrator-level RunPod abstraction**. The existing `external.runpod.session` is the lifecycle primitive. The new ai_toolkit executor delegates to its helpers; don't re-invent.
- **No CI / no production-grade tests in this sprint**. A smoke test that runs `seinfeld.training.config_gen` against the on-disk manifest and asserts the output YAML parses is enough. The remote training run is verified manually by the human.
- **Don't modify the upstream submodule**. Read it; don't patch it.
- **Don't refactor `astrid/packs/seinfeld/dataset_build/`**. That pipeline is in flight separately.

## Acceptance criteria

1. `python3 -m astrid executors list` shows the three new ids: `external.ai_toolkit.train_runpod`, `seinfeld.training.config_gen`.
2. `python3 -m astrid orchestrators list` shows `seinfeld.train`.
3. `python3 -m astrid executors inspect seinfeld.training.config_gen --json` returns a valid manifest.
4. `python3 -m astrid executors run seinfeld.training.config_gen` against `runs/seinfeld-dataset/provisional.manifest.json` produces a YAML that parses and matches the schema of an ai-toolkit example config from `external/ai_toolkit/upstream/config/examples/`.
5. `astrid/packs/external/runpod/run.py`'s `--ports` argument is wired into the produced `pod_handle.json`, and existing callers (no `--ports`) get the same default they had before.
6. `pytest tests/packs/runpod/` still passes (no regressions in the runpod test suite).
7. STAGE.md exists for every new executor/orchestrator with a one-paragraph what-it-does and a copy-pasteable invocation.
8. `AGENTS.md` has the three new short subsections (vendored deps, factoring threshold, long-running sessions).
9. The capability index in `AGENTS.md` is regenerated (`python3 scripts/gen_capability_index.py`).

## Out of scope — explicitly

- The actual training run on a real RunPod pod. Acceptance is structural; verifying the launch works against a live pod is a separate manual step.
- Phase 2 (angle-pair IC-LoRA on musubi).
- Multi-shot inference workflow (also Phase 4 of TRAINING_PLAN.md).
- Cost guards / billing alerts beyond what `external.runpod.session` already provides.
- Network volume setup (rsync to ephemeral container disk per run is fine for now).

## References (read these during prep)

- `astrid/packs/seinfeld/TRAINING_PLAN.md` — the broader plan this sprint implements Phase 1 of.
- `astrid/packs/seinfeld/DATASET_QUALITY.md` — for context on how the dataset is built.
- `astrid/packs/external/runpod/run.py` — the lifecycle pattern to mirror.
- `AGENTS.md` — the executors/orchestrators/elements contract.
- `docs/creating-tools.md` — the build-order rule.
- `docs/templates/executor/`, `docs/templates/orchestrator/` — file scaffolding.
- The `ostris/ai-toolkit` upstream once submoduled — for the config schema.
