# Understand Orchestrator

Use `builtin.understand` when an agent wants one dispatch point for source
understanding across audio, still-image, and video modalities.

The first runtime argument chooses the modality:

```bash
python3 pipeline.py orchestrators run builtin.understand -- image --image frame.jpg
python3 pipeline.py orchestrators run builtin.understand -- audio --audio clip.wav
python3 pipeline.py orchestrators run builtin.understand -- video --video source.mp4
```

For exact input flags, inspect the child executors:

```bash
python3 pipeline.py executors inspect builtin.visual_understand
python3 pipeline.py executors inspect builtin.audio_understand
python3 pipeline.py executors inspect builtin.video_understand
```
