# Understand Executor

Use `builtin.understand` when an agent wants one dispatch point for source
understanding across audio, still-image, and video modalities. It is a thin
switch over the three underlying executors:

- `--mode audio` → `builtin.audio_understand`
- `--mode image` or `--mode visual` → `builtin.visual_understand`
- `--mode video` → `builtin.video_understand`

All arguments after `--mode <modality>` are forwarded unchanged to the
selected executor. Inspect the underlying executors for their input flags:

```bash
python3 -m astrid executors inspect builtin.audio_understand
python3 -m astrid executors inspect builtin.visual_understand
python3 -m astrid executors inspect builtin.video_understand
```

## Examples

The gateway form passes only the `mode` selector through the executor
registry. Modality-specific flags (`--video`, `--image`, `--at`, `--query`,
…) are not declared as registry inputs, so for any non-trivial call invoke
the dispatcher module directly:

```bash
# Gateway form — useful for `--dry-run`, scripting, and CI shape checks.
python3 -m astrid executors run builtin.understand --input mode=video --dry-run

# Canonical form — full modality-specific flag passthrough.
python3 -m astrid.packs.builtin.understand.run --mode image --image frame.jpg
python3 -m astrid.packs.builtin.understand.run --mode audio --audio clip.wav
python3 -m astrid.packs.builtin.understand.run --mode video --video source.mp4 --at 01:20
```
