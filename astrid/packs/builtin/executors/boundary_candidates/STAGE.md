# Boundary Candidates Executor

Use `builtin.boundary_candidates` to package likely start/end frame candidates
for visual review after transcript, scene, shot, or quality-zone analysis.

## Run

All executor inputs are passed with `--input NAME=VALUE`:

```bash
python3 -m astrid executors run builtin.boundary_candidates \
  --out runs/boundary-review \
  --input video=source.mp4 \
  --input manifest=runs/boundary-review/boundary_manifest.json
```

The manifest must contain a `talks` array. Each talk should provide enough
timing data for candidate windows, for example start/end seconds plus a label or
title. Keep the window smaller than very short source clips; the default window
is designed for real talk footage and can extend candidates beyond tiny test
fixtures.

Useful optional inputs supported by the underlying CLI include `asset_key`,
`transcript`, `scenes`, `shots`, `quality_zones`, `holding_screens`, `kind`,
`window`, and `max_candidates`.
