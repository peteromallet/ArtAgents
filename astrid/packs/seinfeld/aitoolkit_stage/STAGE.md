# seinfeld.aitoolkit_stage

Generates an ai-toolkit (ostris) job config from the dataset manifest + vocabulary, writes a `bootstrap.sh` that symlinks the dataset into `/workspace/dataset/`, drops `/workspace/config.yaml` on the pod, and starts the AI Toolkit UI on port 8675. Hivemind defaults bake in LTX 2.3, 512×768, 97 frames @ 24fps, LR 2e-5, rank 32, save/sample every 250 steps, bucketing on. The trigger token `seinfeld scene` is prepended at inference and training via the config's `trigger_word`; on-disk caption files are not mutated. In `--dry-run`, no pod is required and only the local config + bootstrap are written.

**Invocation**:

```bash
python3 -m astrid.packs.seinfeld.aitoolkit_stage.run \
  --manifest runs/seinfeld-dataset/provisional.manifest.json \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --produces-dir runs/seinfeld-lora/010-stage/produces \
  --dry-run
```
