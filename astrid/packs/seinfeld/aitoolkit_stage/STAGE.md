# seinfeld.aitoolkit_stage

Generates an ai-toolkit (ostris) job config from the dataset manifest + vocabulary, writes a `bootstrap.sh`, drops `/workspace/config.yaml` on the pod, uploads the manifest-listed dataset clips + caption sidecars, and starts the AI Toolkit UI on port 8675. Hivemind defaults bake in LTX 2.3, 512x768, 97 frames @ 24fps, LR 2e-5, rank 32, save/sample every 250 steps, bucketing on. The trigger token `seinfeld scene` is prepended at inference and training via the config's `trigger_word`; on-disk caption files are not mutated. In `--dry-run`, no pod is required and the executor prints the dataset upload it would perform.

Dataset upload runs after the config/bootstrap `external.runpod.exec` call succeeds. It uses a copy farm under `<produces>/_dataset_staging/`: each manifest clip and `.caption.json` sidecar is copied into a bucket directory, then uploaded with `external.runpod.exec --upload-mode sftp_walk`. This avoids symlink-following ambiguity and keeps `--smoke` predictable by copying only the first five manifest clips. The default remote path is `/workspace/dataset`, matching the generated ai-toolkit config; override it with `--dataset-remote-path`.

**Invocation**:

```bash
python3 -m astrid.packs.seinfeld.aitoolkit_stage.run \
  --manifest runs/seinfeld-dataset/provisional.manifest.json \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --produces-dir runs/seinfeld-lora/010-stage/produces \
  --dataset-remote-path /workspace/dataset \
  --dry-run
```

## Verified image layout

Verified on 2026-05-12 against `ostris/aitoolkit:latest` on a RunPod `NVIDIA A40` pod (`jib9xczr0j2y0v`, terminated after inspection).

- Toolkit root: `/app/ai-toolkit`.
- Training entrypoint: `cd /app/ai-toolkit && python3 run.py /workspace/config.yaml --log /workspace/training.log`.
- UI startup: container PID 1 runs `/start.sh`, which starts `cd /app/ai-toolkit/ui && npm run start`. That expands to `node dist/cron/worker.js` plus `next start --port 8675`; the UI was already serving HTTP 200 on `127.0.0.1:8675`.
- CUDA check: `nvidia-smi` saw one `NVIDIA A40` and Python reported `torch 2.9.1+cu128`, `torch.cuda.is_available() == True`.
- Environment: `run.py` loads `.env`, sets `HF_HUB_ENABLE_HF_TRANSFER=1`, `NO_ALBUMENTATIONS_UPDATE=1`, and `DISABLE_TELEMETRY=YES`, accepts optional `SEED` and `DEBUG_TOOLKIT`, and model code reads `HF_TOKEN` from `os.getenv()`. The bootstrap sources `/etc/rp_environment`, falls back to `/proc/1/environ`, and writes the runtime `HF_TOKEN` value into `/app/ai-toolkit/.env` without embedding secrets in `bootstrap.sh`. The UI job launcher adds `AITK_JOB_ID`, `CUDA_VISIBLE_DEVICES`, `IS_AI_TOOLKIT_UI`, and optional UI-stored `HF_TOKEN` for UI-launched jobs.
