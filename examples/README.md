# Examples

The `examples/` directory contains the committed Sprint 1 golden fixtures plus the full-surface Sprint 2 schema fixture used by the Remotion smoke test and the Python schema-contract suite.

Generate local sample media on demand with:

```bash
ffmpeg -f lavfi -i testsrc=duration=42:size=1920x1080:rate=30 -c:v libx264 examples/main.mp4
ffmpeg -f lavfi -i testsrc=duration=18:size=1280x720:rate=24 -c:v libx264 examples/broll.mp4
```

Notes:

- `main.mp4` and `broll.mp4` are not committed. Generate them locally when you need a real fixture render.
- `hype.timeline.full.json` and `hype.assets.full.json` are schema-only fixtures consumed by the smoke test and `tools/tests/test_schema_contract.py`.
- The full fixture `file` paths point at the on-demand media names, but those files do not need to exist for bundle-only smoke checks.
