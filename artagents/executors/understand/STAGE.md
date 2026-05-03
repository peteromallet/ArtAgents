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
python3 -m artagents executors inspect builtin.audio_understand
python3 -m artagents executors inspect builtin.visual_understand
python3 -m artagents executors inspect builtin.video_understand
```

## Examples

Run via the executor module directly (the gateway is configured for the
underlying single-modality executors):

```bash
python3 -m artagents.executors.understand.run --mode image --image frame.jpg
python3 -m artagents.executors.understand.run --mode audio --audio clip.wav
python3 -m artagents.executors.understand.run --mode video --video source.mp4 --at 01:20
```
