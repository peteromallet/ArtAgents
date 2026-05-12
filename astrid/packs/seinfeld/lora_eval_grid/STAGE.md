# seinfeld.lora_eval_grid

Builds a fixed 3-6 prompt set from `vocabulary.yaml` (covering both scenes and at least two characters), runs baseline LTX inference plus inference with each checkpoint from `checkpoint_manifest.json` on the live pod via `external.runpod.exec`, downloads the MP4s into `eval_grid/baseline/` and `eval_grid/<step>/`, and writes a static `index.html` viewer that lays each prompt out as a row of side-by-side `<video>` tags. In `--smoke` mode runs only the 3-prompt baseline (no per-checkpoint comparison). This is the artifact the human reviews at the gate before picking a checkpoint.

**Invocation**:

```bash
python3 -m astrid.packs.seinfeld.lora_eval_grid.run \
  --pod-handle runs/seinfeld-lora/000-provision/produces/pod_handle.json \
  --checkpoint-manifest runs/seinfeld-lora/020-train/produces/checkpoint_manifest.json \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --produces-dir runs/seinfeld-lora/030-eval/produces
```
