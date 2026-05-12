# seinfeld.aitoolkit_train

Runs ai-toolkit training on the live RunPod pod against `/workspace/config.yaml` (placed by `seinfeld.aitoolkit_stage`). Streams the remote training log into a local mirror file under the produces directory so the log survives pod teardown. On completion, walks `/workspace/output` and emits `checkpoint_manifest.json` — one entry per saved checkpoint with `step` and `remote_path`. Tails the log for `CUDA out of memory`, `NaN detected`, and `RuntimeError`; on a match it captures the last 200 log lines to `training.failure.log`, marks `status: failed`, and exits non-zero so the orchestrator short-circuits to teardown.

**Invocation**:

```bash
python3 -m astrid.packs.seinfeld.aitoolkit_train.run \
  --pod-handle runs/seinfeld-lora/000-provision/produces/pod_handle.json \
  --produces-dir runs/seinfeld-lora/020-train/produces
```
