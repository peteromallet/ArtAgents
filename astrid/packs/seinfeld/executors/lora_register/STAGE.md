# seinfeld.lora_register

Pure-local finalize step that runs after pod teardown. Reads `chosen_checkpoint.json` (written by the resume subcommand of `seinfeld.lora_train`), copies the chosen `.safetensors` into `<out>/registered/<lora_id>.safetensors`, and writes `registered_lora.json` with all 8 required fields: `lora_id`, `checkpoint_step`, `lora_file`, `config_used`, `base_model`, `vocabulary_hash` (SHA-256 of the vocabulary file at register time), `trained_at` (ISO-8601 UTC), `human_pick_notes`. Downstream orchestrators (`script_to_shots`, `scene_render`) look up this file to resolve the active scene-LoRA.

**Invocation**:

```bash
python3 -m astrid.packs.seinfeld.executors.lora_register.run \
  --chosen-checkpoint runs/seinfeld-lora/chosen_checkpoint.json \
  --lora-source runs/seinfeld-lora/020-train/produces/step_1500.safetensors \
  --staged-config runs/seinfeld-lora/010-stage/produces/staged_config.yaml \
  --vocabulary astrid/packs/seinfeld/vocabulary.yaml \
  --produces-dir runs/seinfeld-lora/040-register/produces
```
