# Iteration Video

Chains `iteration.prepare`, `iteration.assemble`, and `builtin.render` to create an iteration recap from a thread.

The render handoff is explicit: assemble writes `hype.timeline.json` and `hype.assets.json`, `builtin.render` consumes those exact files and emits `hype.mp4`, then this orchestrator records `iteration.mp4` alongside the canonical iteration metadata.

Inspect first when provenance quality is uncertain:

```bash
python3 -m artagents.orchestrators.iteration_video.run inspect @active --no-content
```

Run through the canonical gateway:

```bash
python3 -m artagents orchestrators run builtin.iteration_video --out runs/iteration_video --thread @active -- --max-iterations 20
```

V1 supports chaptered mode only. `--direction` is a label, `--renderers` and `--clip-mode` are recorded as requested planning hints, and no generated music is created.

