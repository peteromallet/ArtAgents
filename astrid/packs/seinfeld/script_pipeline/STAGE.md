# Seinfeld Script Pipeline

Use `seinfeld.script_pipeline` to generate a short Seinfeld-style scene script
through the three-pass DeepSeek pipeline:

1. Five high-temperature rough attempts.
2. One synthesis pass that threads the strongest beats into a coherent scene.
3. One voice/laugh pass that corrects character voice and adds sparse laugh tags.

Inspect first:

```bash
python3 -m astrid executors inspect seinfeld.script_pipeline --json
```

Run one candidate:

```bash
python3 -m astrid executors run seinfeld.script_pipeline --out runs/seinfeld-script
```

Run five complete candidates and select the best with a judge pass:

```bash
python3 -m astrid.packs.seinfeld.script_pipeline.run \
  --produces-dir runs/seinfeld-script/produces \
  --candidates 5 \
  --select-best \
  --open-result
```

The executor reads `DEEPSEEK_API_KEY` from the environment. By default it also
loads `~/.hermes/.env` if present.
