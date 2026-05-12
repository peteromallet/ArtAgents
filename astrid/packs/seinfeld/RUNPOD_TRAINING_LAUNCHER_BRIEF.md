# Brief — Fill in `seinfeld.lora_train` on RunPod via ai-toolkit

**Megaplan profile**: `thoughtful//medium +prep`

Fill in the existing `astrid/packs/seinfeld/lora_train/` skeleton so that
`python3 -m astrid orchestrators run seinfeld.lora_train` takes the
existing `runs/seinfeld-dataset/` (131 accepted clips +
`provisional.manifest.json`) and trains an LTX 2.3 scene-LoRA on a
RunPod GPU pod using Ostris's `ai-toolkit`, with the AI Toolkit UI
exposed for live sample review and a human-gated checkpoint pick.

This sprint implements **lora_train (Phase 2)** from `project.md`. It
does **not** implement the broader `seinfeld_demo` umbrella that chains
`dataset_build → lora_train → script_to_shots → scene_render`; that is
a separate follow-up sprint (see "Out of scope" below).

## Goal

After this sprint:

1. `python3 -m astrid orchestrators run seinfeld.lora_train --manifest runs/seinfeld-dataset/provisional.manifest.json --vocabulary astrid/packs/seinfeld/vocabulary.yaml --out runs/seinfeld-lora` provisions a pod, uploads dataset + config, starts the AI Toolkit UI, prints the URL, runs training, generates an eval-sample grid (baseline LTX vs each checkpoint on the same prompts), waits at the human checkpoint-selection gate, tears the pod down, and registers the chosen LoRA.
2. A `--smoke` flag runs the same pipeline against a 5-clip subset for 100 steps so the wiring can be verified for ~$0.50 before committing $10+.

## Brief amendments — must address (added after prep)

These items were identified as gaps after the initial brief was written. The plan must address each; the critique should explicitly flag any that the plan misses.

### Blockers (live run will fail without these)

1. **`HF_TOKEN` secret**: LTX 2.3 weights are gated on HuggingFace (Lightricks). The orchestrator must:
   - Validate `HF_TOKEN` is set in the local env at pre-flight time (fail with a clear error pointing at where to set it).
   - Pass `HF_TOKEN` into the pod environment when launching ai-toolkit (via `external.runpod.exec`'s env-passthrough, or by writing a `.env` to `/workspace/` and sourcing it in `bootstrap.sh`).
   - Document in STAGE.md that `HF_TOKEN` is required.

2. **Image tag pinning**: `ostris/ai-toolkit:latest` is reproducibility quicksand. Prep must pick a specific tag (e.g., `ostris/ai-toolkit:0.X.Y`) or digest, and that pin must be hardcoded in `aitoolkit_stage`'s default. The latest tag is fine as an explicit override but not as the default.

3. **Datacenter default**: Bake in a sensible default (one known to have RTX 6000 Ada / A100 80GB inventory — prep verifies by calling `runpod_lifecycle.api.get_gpu_types(datacenter_id=...)` or equivalent). Provide a small ordered fallback list in `lora_train`'s code so the first available DC wins. Don't silently choose a DC without the requested GPU.

4. **Training-crash detection**: AI Toolkit can OOM, NaN out, or hit a Gemma3-OOM error (per hivemind: metaphysician). `seinfeld.aitoolkit_train` must:
   - Poll the remote process exit status (not just wall-clock).
   - Tail the remote training log for known failure patterns (`CUDA out of memory`, `NaN detected`, `RuntimeError`).
   - On detection: capture the last 200 lines of log to `<out>/training.failure.log`, mark `checkpoint_manifest.json` with `status: "failed"`, and **return non-zero so the orchestrator can short-circuit to teardown** — don't proceed to eval grid against a broken training run.

### Operational quality (will frustrate without these)

5. **`.env` auto-loading**: Pre-flight validation should auto-source the first available of:
   - `$PWD/.env.local`
   - `$PWD/.env`
   - `/Users/peteromalley/Documents/reigh-workspace/runpod-lifecycle/.env`
   - `~/.config/astrid/.env`
   
   …before checking that `RUNPOD_API_KEY`, `HF_TOKEN` are set. On failure, print the exact set/source-from command for each missing var.

6. **UI URL written to file**: After `seinfeld.aitoolkit_stage` returns the AI Toolkit UI URL, the orchestrator writes it to `<out>/ui_url.txt` and re-prints it on every subsequent step (so a user who closed the terminal can recover it from disk or from the live console).

7. **Total cost summary at end**: After teardown, the orchestrator reads every `cost.json` artifact produced by child steps and prints a `Total spend: $X.YY` line. Also write a `<out>/cost_summary.json` aggregating per-step costs.

8. **Concurrent-run guard + Ctrl-C cleanup**: 
   - **Lock file**: At orchestrator start, acquire `<out>/.lock` exclusively. If already locked, exit with a clear "another seinfeld.lora_train run is in progress at PID <X>; remove <out>/.lock if stale" error.
   - **Signal handling**: Register a SIGINT/SIGTERM handler in the orchestrator that, if a pod is alive (pod_handle.json exists and no teardown receipt), invokes `external.runpod.teardown` before exit. **Never** leave a pod running after the orchestrator dies. This is the same try/finally pattern `external.runpod.session` uses internally; we recreate it at the orchestrator level since we're not using `session`.

9. **Trigger token convention**: Decide once. Recommend: prepend `seinfeld scene, ` to every caption at training time (so inference can use `seinfeld scene, jerry in his apartment, wide shot, ...` to invoke the LoRA). The prepend happens inside `aitoolkit_stage`'s config-generation step (not by mutating the on-disk caption files). Document this in STAGE.md so downstream (`script_to_shots`, `scene_render`) knows to emit the same prefix.

10. **Reproducibility seed**: Default `seed: 42` in the ai-toolkit config. Expose `--seed` on `lora_train` so the human can vary it for the same dataset. Record the seed used in `registered_lora.json`.

## Architecture (aligned with `project.md` and the existing skeleton)

`project.md` defines four seinfeld orchestrators (`dataset_build`,
`lora_train`, `script_to_shots`, `scene_render`) plus a top-level
`seinfeld_demo` chaining them. The `lora_train` STAGE.md already
specifies the step list and target executor names. This brief fills
that in without re-designing it.

### Pod lifecycle: provision + exec + teardown (NOT session)

We need the pod alive across multiple steps (stage → train → eval grid → human gate → teardown). The existing `external.runpod.session` executor is wrong for this — it terminates when the inner script exits.

Instead, the orchestrator uses three separate executors from the existing pack:

- `external.runpod.provision` — launches the pod, returns `pod_handle.json`.
- `external.runpod.exec` — runs a script on the live pod. Called multiple times (stage, train kickoff, eval grid). The pod stays alive between calls.
- `external.runpod.teardown` — terminates the pod after the human gate.

The AI Toolkit UI starts during the stage step and stays live until teardown. Print its public URL prominently after `provision` returns.

### File layout

```
astrid/packs/seinfeld/
├── ai_toolkit/
│   └── upstream/                  ← NEW git submodule: ostris/ai-toolkit
├── lora_train/                    ← EXISTING skeleton — fill in
│   ├── orchestrator.yaml          (already exists; update child_executors)
│   ├── STAGE.md                   (already exists; update once implemented)
│   ├── run.py                     (REWRITE — currently a stub)
│   └── config_template.yaml       (NEW — ai-toolkit job config with hivemind defaults)
├── aitoolkit_stage/               ← NEW executor
│   ├── executor.yaml
│   ├── STAGE.md
│   └── run.py
├── aitoolkit_train/               ← NEW executor
│   ├── executor.yaml
│   ├── STAGE.md
│   └── run.py
├── lora_eval_grid/                ← NEW executor
│   ├── executor.yaml
│   ├── STAGE.md
│   └── run.py
└── lora_register/                 ← NEW executor
    ├── executor.yaml
    ├── STAGE.md
    └── run.py
```

The submodule lives under `seinfeld/ai_toolkit/upstream/` (not `external/`) because seinfeld is the only consumer for now. If a second domain needs ai-toolkit later, lift the submodule (and any shared executors) into a new `external/ai_toolkit/` pack at that time. YAGNI.

## Patch to `external/runpod/` (and `runpod-lifecycle` if needed)

The existing `astrid/packs/external/runpod/run.py` hardcodes `"ports": "8888/http,22/tcp"` at lines 192 and 461. Expose `ports` as a configurable input:

- Add `--ports` CLI argument to `provision` and `session` subparsers (default keeps current value, so existing callers are unaffected).
- Thread it into `handle["config_snapshot"]["ports"]`.
- Verify `runpod-lifecycle`'s `RunPodConfig` / `launch()` accepts a `ports` field. If not, **also patch `runpod-lifecycle`** — it's in scope for this sprint.
- Update `astrid/packs/external/runpod/executor.yaml` to declare `ports` as an input on the `external.runpod.provision` and `external.runpod.session` executors.

### `runpod-lifecycle` is in scope (sibling repo)

The user owns `runpod-lifecycle` (origin: `banodoco/runpod-lifecycle`). It is checked out locally as a sibling repo at:

```
/Users/peteromalley/Documents/reigh-workspace/runpod-lifecycle
```

Current version: v0.2 (latest commit `61c7f5c`). The Astrid pack pins `runpod-lifecycle>=0.2`.

**If prep determines `RunPodConfig` / `launch()` does not already accept a `ports` parameter:**

1. Read `runpod-lifecycle/src/` to understand the `RunPodConfig` dataclass and the `launch()` flow.
2. Add a `ports` parameter to `RunPodConfig` (e.g. `ports: str | None = None` with the existing `"8888/http,22/tcp"` as the implicit default if the field is None, so existing callers keep working).
3. Thread it through `launch()` and any internal GraphQL pod-create call so the requested ports are declared at pod creation time.
4. Add a unit test in `runpod-lifecycle/tests/` covering the new field.
5. Bump the version in `runpod-lifecycle/pyproject.toml` (v0.2 → v0.3).
6. Commit in `runpod-lifecycle/` with a clean message; do **not** push or tag — that's a manual user step after review.
7. Update Astrid's pin: `astrid/packs/external/runpod/requirements.txt` → `runpod-lifecycle>=0.3`.
8. Astrid-side: install the local sibling editable so the new code is picked up immediately for testing: `pip install -e /Users/peteromalley/Documents/reigh-workspace/runpod-lifecycle`.

**If prep determines `RunPodConfig` / `launch()` already accept ports** (under a different name, or implicitly via kwargs): skip the upstream patch entirely. The Astrid-side `--ports` plumbing is enough.

Either way: prep must read the upstream code, not guess. The patch should not be planned blind.

## The five new files in detail

### Submodule (executor must run this — not a manual pre-flight)

```bash
git submodule add https://github.com/ostris/ai-toolkit astrid/packs/seinfeld/ai_toolkit/upstream
cd astrid/packs/seinfeld/ai_toolkit/upstream && git checkout <SHA chosen during prep> && cd -
git add astrid/packs/seinfeld/ai_toolkit/upstream .gitmodules
```

Prep should pick a SHA confirmed to support LTX 2.3 (reference: the [LTX 2.3 on 5090 Reddit post](https://www.reddit.com/r/StableDiffusion/comments/1swrs76/) and recent ltx_training Discord activity). The submodule exists for config-schema reference at build time; the docker image on the pod has its own copy at runtime.

### `seinfeld.aitoolkit_stage` (executor)

One concrete unit: from a manifest + vocabulary, emit a valid ai-toolkit config + a `bootstrap.sh`, upload them and the dataset to the pod via `external.runpod.exec`, and start the AI Toolkit UI.

Inputs:
- `pod_handle`: path to `pod_handle.json` from `external.runpod.provision`.
- `manifest`: path to `provisional.manifest.json` (default).
- `vocabulary`: path to `vocabulary.yaml` (default).
- `config_out`: where to write the generated config locally (for the artifact dir).
- `smoke` (bool): if set, use only the first 5 clips and override `--steps 100`.

Outputs:
- `staged_config.yaml` (local copy of what was uploaded).
- `bootstrap.sh` (local copy).
- `ui_url`: the public URL of the AI Toolkit UI (e.g. `https://<pod-id>-8675.proxy.runpod.net`).
- `cost.json` (passthrough from `external.runpod.exec`).

ai-toolkit job YAML — hivemind-validated defaults (overridable via CLI flags):

| Setting | Value | Source |
|---|---|---|
| Model | LTX 2.3 | the brief — verify exact ai-toolkit model id during prep by reading `seinfeld/ai_toolkit/upstream/config/examples/` |
| Resolution | 512×768 | siraxe / SmaX (BNDC daily summary) |
| Frames per clip | 97 | LTX 1+8N rule, ≤5s @ 24fps |
| fps | 24 | Daviejg |
| LR | 2e-5 | community consensus for LTX LoRAs |
| Steps | 2000 (override: 100 in `--smoke`) | TRAINING_PLAN.md derived from hivemind |
| Save every / sample every | 250 steps | for quick visibility |
| Rank | 32 | Kijai — rank 32 > rank 64 for small datasets |
| Batch size | 1, grad accumulation 4 | standard |
| Bucketing | enabled, no crop | Xodroc — "ai-toolkit without needing to crop" |
| Captions | minimal, from `.caption.json` sidecars | oumoumad / crinklypaper |

**Prep should read `seinfeld/ai_toolkit/upstream/config/examples/` to nail down field names.** Don't invent fields. Note that the skeleton's `run.py` defaults `--steps 4000` and `--gpu a100-80g`; honor the new hivemind defaults (2000 / RTX 6000 Ada baseline, A100 80GB as `--gpu` override) and update the skeleton.

`bootstrap.sh` (runs on the pod):
- Sources the AI Toolkit env (verify entrypoint during prep — read Ostris's docker image docs).
- Symlinks `/workspace/dataset/` → uploaded dataset.
- Writes `/workspace/config.yaml`.
- Starts the AI Toolkit UI server (port 8675; verify exact port + start command during prep).
- Returns successfully — does not block on training. Training is kicked off by the next step.

### `seinfeld.aitoolkit_train` (executor)

Starts training via `external.runpod.exec`, polls remote log files, streams them to a local log file under `<out>/training.log` so the log survives pod teardown. Returns checkpoint paths on the pod.

Inputs: `pod_handle`, `config_path` (path on pod from staging), `local_log` (path on host to mirror the remote training log into).
Outputs: `checkpoint_manifest.json` listing each saved checkpoint with its step number and remote path.

### `seinfeld.lora_eval_grid` (executor)

Runs inference samples on the pod for both baseline LTX (no LoRA) and each checkpoint, against a fixed prompt set built from the vocabulary. Downloads MP4s into `<out>/eval_grid/`. Writes `<out>/eval_grid/index.html` — a static side-by-side viewer.

Inputs: `pod_handle`, `checkpoint_manifest`, `vocabulary` (for prompt construction), `prompts` (optional explicit list — defaults to deriving from vocabulary).
Outputs: `<out>/eval_grid/baseline/*.mp4`, `<out>/eval_grid/<step>/*.mp4`, `<out>/eval_grid/index.html`.

This step is what makes the human gate trustworthy. Don't skip it; per `project.md` risk #3, character identity across cuts is exactly what the grid is checking for.

### `seinfeld.lora_register` (executor)

Pure local, runs after teardown. Reads a `chosen_checkpoint.json` (produced by the human gate — see below), downloads the LoRA file from the artifact_dir, and writes `<out>/registered_lora.json`:

```json
{
  "lora_id": "seinfeld-scene-v1",
  "checkpoint_step": 1500,
  "lora_file": "runs/seinfeld-lora/registered/seinfeld-scene-v1.safetensors",
  "config_used": "runs/seinfeld-lora/staged_config.yaml",
  "base_model": "ltx-2.3",
  "vocabulary_hash": "<sha from vocab_compile>",
  "trained_at": "<iso8601>",
  "human_pick_notes": "<from chosen_checkpoint.json>"
}
```

This is the artifact downstream orchestrators (`script_to_shots`, `scene_render`) will look up.

### `seinfeld.lora_train` (orchestrator — replaces the stub)

Pipeline:

1. **Pre-flight validation** (local, in the orchestrator before any pod work):
   - Manifest exists, every clip's `clip_file` and `.caption.json` sidecar exists on disk.
   - `vocabulary.yaml` parses.
   - `RUNPOD_API_KEY` is set.
   - If `--smoke`: verify ≥5 clips present.
   - On any failure: exit non-zero with a clear error before spending any money.
2. `external.runpod.provision` with `--ports 8675/http,22/tcp`, `--storage-name seinfeld-dataset`, `--gpu-type` from `--gpu` (default RTX 6000 Ada — change from skeleton's a100-80g since RTX 6000 Ada is ~$0.79/hr vs A100 80GB's $1.89/hr; allow `--gpu a100-80g` override), `--container-disk-gb 200`, `--max-runtime-seconds 28800` (8hr ceiling).
3. `seinfeld.aitoolkit_stage` (uploads + starts UI). **Print the UI URL prominently** to stdout so the user can open it.
4. `seinfeld.aitoolkit_train` (kicks off training, mirrors logs locally).
5. `seinfeld.lora_eval_grid` (runs samples, downloads grid).
6. **Human gate** — orchestrator pauses and prints:
   - The eval grid path: `<out>/eval_grid/index.html`.
   - Instructions: "Open the grid, then run `astrid ack ...` with `--decision approve` and `--notes 'chose step <N>'`" — or, simpler for this sprint, a separate manual command `python3 -m astrid orchestrators run seinfeld.lora_train resume --pick <step> --pod-handle <path>`.
   - Pick the simpler "resume with --pick" path for this sprint. The full attested-gate wiring can come later when we build the umbrella.
7. `external.runpod.teardown`.
8. `seinfeld.lora_register`.

**Network volume**: `--storage-name seinfeld-dataset`. The runpod pack already supports it (`astrid/core/runpod/storage.py:ensure_storage()` find-or-creates idempotently; the executor passes it through). Use it so re-runs don't re-upload the dataset. The orchestrator should also accept `--storage-name <other>` for users who want a one-shot ephemeral run.

**Smoke mode**: `--smoke` flips `--steps 100`, uses 5 clips, skips the eval grid (or uses a 3-prompt eval). Goal: end-to-end pipeline verification under $1 of GPU.

**Resume**: write `<out>/last_run.json` after each step with the next-step input parameters (pod_handle path, checkpoint manifest path, etc.). Don't wire auto-resume in this sprint, but the data should be there for the umbrella sprint to use.

### `lora_train/orchestrator.yaml` updates

The current `child_executors: []` is empty. Populate it:

```yaml
child_executors:
  - "external.runpod.provision"
  - "external.runpod.exec"
  - "external.runpod.teardown"
  - "seinfeld.aitoolkit_stage"
  - "seinfeld.aitoolkit_train"
  - "seinfeld.lora_eval_grid"
  - "seinfeld.lora_register"
```

## Pattern to mirror (read these during prep)

- `astrid/packs/external/runpod/run.py` — especially `cmd_provision`, `cmd_exec`, `cmd_teardown` (lines 130-376). The new seinfeld executors should call `external.runpod.exec`'s helpers; do not re-implement shipping.
- `astrid/packs/external/runpod/executor.yaml` — schema for executor manifests.
- `astrid/packs/external/runpod/STAGE.md` — short STAGE.md form.
- `/Users/peteromalley/Documents/reigh-workspace/runpod-lifecycle/src/` — the upstream `RunPodConfig` and `launch()` you may need to patch. Read before deciding the patch shape.
- `astrid/packs/external/vibecomfy/` — another external-service wrapper, cross-reference for unclear cases.
- `astrid/packs/seinfeld/dataset_build/run.py` and `orchestrator.yaml` — pattern for seinfeld-internal orchestrators.
- `astrid/packs/seinfeld/lora_train/STAGE.md` — the spec we're implementing.
- `project.md` — the canonical project plan with the four-orchestrator architecture.
- The `ostris/ai-toolkit` upstream once submoduled — for the config schema.

## Constraints / non-goals

- **No IC-LoRA training.** AI Toolkit doesn't support it. Future sprint via musubi or LTX official scripts.
- **No new generic `external/ai_toolkit/` pack.** YAGNI — current consumer is seinfeld-only. Lift later when a second consumer appears.
- **No new RunPod template.** Use Ostris's public docker image (`ostris/ai-toolkit:latest` or pinned tag — prep confirms).
- **No `external.runpod.session` reuse.** Use `provision` + `exec` + `teardown` separately because the pod must outlive any single script execution.
- **No automated training-completion notification.** The human polls the AI Toolkit UI.
- **No full attested-gate wiring to `astrid ack`.** Use a manual `--pick <step>` resume invocation for this sprint. The full session-gate wiring can come when the umbrella `seinfeld_demo` orchestrator is built.
- **No CI tests beyond unit-level.** A smoke test that:
  - Runs `seinfeld.aitoolkit_stage` in `--dry-run` mode (no pod, just config generation) against the on-disk manifest.
  - Asserts the produced YAML parses and contains the hivemind-validated keys.
  - Asserts pre-flight validation correctly fails on a manifest with a missing caption sidecar.
- **Don't modify the upstream submodule.** Read it; don't patch it.
- **Don't refactor `dataset_build/`.** Done separately.

## Acceptance criteria

1. `python3 -m astrid executors list` shows: `seinfeld.aitoolkit_stage`, `seinfeld.aitoolkit_train`, `seinfeld.lora_eval_grid`, `seinfeld.lora_register`.
2. `python3 -m astrid orchestrators list` shows `seinfeld.lora_train` (existing skeleton id; now has populated `child_executors`).
3. `python3 -m astrid executors inspect seinfeld.aitoolkit_stage --json` returns a valid manifest.
4. `python3 -m astrid orchestrators run seinfeld.lora_train --dry-run` runs pre-flight validation, generates a config locally, and exits 0 without touching RunPod.
5. The generated config matches the schema of an ai-toolkit example config from `astrid/packs/seinfeld/ai_toolkit/upstream/config/examples/` (parses with the same YAML loader).
6. `external/runpod/`'s `--ports` argument is wired into the produced `pod_handle.json`. Existing callers that don't pass `--ports` get the same default they had before.
7. If the `runpod-lifecycle` upstream patch was needed: `runpod-lifecycle/pyproject.toml` reflects the bumped version; `runpod-lifecycle/tests/` has a new test covering `ports`; the change is committed in the sibling repo but not pushed; `astrid/packs/external/runpod/requirements.txt` pin is updated to match.
8. `pytest tests/packs/runpod/` still passes (no regressions in the existing RunPod test suite).
9. STAGE.md exists for every new executor + the updated orchestrator. Each has a one-paragraph description and a copy-pasteable invocation.
10. `python3 scripts/gen_capability_index.py` is re-run; `AGENTS.md` capability index reflects the new executors.
11. `.gitmodules` has the seinfeld/ai_toolkit/upstream submodule entry. Submodule SHA is pinned.
12. **Brief amendments are all addressed**: HF_TOKEN validation + passthrough; image tag pinned (no `:latest` default); datacenter default with fallback list; training-crash detection short-circuits to teardown; `.env` auto-loading on pre-flight; UI URL written to `<out>/ui_url.txt`; cost summary printed and written to `<out>/cost_summary.json`; orchestrator-level lockfile + SIGINT-cleans-up-pod; trigger token (`seinfeld scene, `) is documented in STAGE.md; `seed: 42` default with `--seed` override, recorded in `registered_lora.json`.

## Out of scope (next sprints)

- **`seinfeld_demo` umbrella orchestrator**: chains `dataset_build → lora_train → script_to_shots → scene_render` per `project.md`. Each stage is a discrete invocation; the umbrella shouldn't run the whole thing end-to-end in one shot (training takes hours and needs human review in the middle). Instead, it should expose a task-list-style entry point: `astrid seinfeld next` prints the next step the user should run, with copy-pasteable commands.
- **`script_to_shots`** and **`scene_render`** orchestrators (Phases 3 and 4 of `project.md`).
- **Live training-run smoke test on a real RunPod pod**: this brief gets acceptance criteria via dry-run + unit tests; verifying the end-to-end run works against a live pod is a separate manual step the human performs.
- **Auto-resume from `last_run.json`** (data is written but not consumed).
- **Multi-GPU training, distributed training, gradient checkpointing tuning.**
- **GPU-availability fallback** if the requested GPU isn't free in the chosen DC.
- **Moving the strict-mode pipeline scripts** from `/tmp/process_hero_scenes_strict.py`, `/tmp/extract_pairs.py`, `/tmp/build_manifest_from_disk.py` into the pack. Worth doing separately so they survive a reboot — not in this brief's scope.
- **Cost-cap webhook / alerts.** The 8-hour `--max-runtime-seconds` ceiling is the only guard this sprint.

## References (read these during prep)

- `astrid/packs/seinfeld/TRAINING_PLAN.md` — the broader plan this sprint implements Phase 1 (scene-LoRA) of.
- `astrid/packs/seinfeld/DATASET_QUALITY.md` — context on dataset construction.
- `astrid/packs/seinfeld/lora_train/STAGE.md` — the spec being filled in.
- `astrid/packs/external/runpod/run.py` — the lifecycle helpers to call.
- `astrid/core/runpod/storage.py` — `ensure_storage()` for the network volume.
- `project.md` — canonical four-orchestrator project plan.
- `AGENTS.md` — executors/orchestrators contract and build-order rule.
- `docs/creating-tools.md` — build-order rule expanded.
- `docs/templates/executor/`, `docs/templates/orchestrator/` — scaffolding.
- The `ostris/ai-toolkit` upstream once submoduled — config schema, run entrypoint, UI start command.

## Megaplan invocation

```bash
megaplan init astrid/packs/seinfeld/RUNPOD_TRAINING_LAUNCHER_BRIEF.md \
  --profile thoughtful \
  --depth medium \
  --with-prep
```

**Why `thoughtful` over `led`**: scope grew with the runpod-lifecycle patch path being in-scope (one repo to two), the eval-grid step, and the network-volume + port-forwarding plumbing. Cross-cutting enough that we want premium critique + review, not just a premium plan. Depth stays at `medium` (planner deliberates on architecture; critic and mechanical phases stay at `:low` per the asymmetry principle).

If during the run the plan still misses concerns after escalation, override mid-flight: `megaplan override set-profile --profile premium --plan <id>` or `megaplan override set-robustness --robustness robust`.
