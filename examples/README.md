# Examples

The `examples/` directory contains committed schema fixtures and small sample
briefs. Generated media does not belong here.

## Briefs

`examples/briefs/` contains human-readable pure-generative briefs that are safe
to commit and useful for manual smoke runs:

```bash
python3 pipeline.py --brief examples/briefs/cinematic.txt --out runs/cinematic --render --target-duration 15
python3 pipeline.py --brief examples/briefs/surreal.txt --out runs/surreal --render --target-duration 15
```

## Media Fixtures

Generate local sample media on demand with:

```bash
ffmpeg -f lavfi -i testsrc=duration=42:size=1920x1080:rate=30 -c:v libx264 examples/main.mp4
ffmpeg -f lavfi -i testsrc=duration=18:size=1280x720:rate=24 -c:v libx264 examples/broll.mp4
```

Notes:

- `main.mp4`, `broll.mp4`, and other generated media are not committed.
  Generate them locally when you need a real fixture render.
- `hype.timeline.full.json` and `hype.assets.full.json` are schema-only fixtures consumed by the smoke test and `tools/tests/test_schema_contract.py`.
- The full fixture `file` paths point at the on-demand media names, but those files do not need to exist for bundle-only smoke checks.
