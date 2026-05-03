# Iteration Assemble Executor

`iteration.assemble` consumes the outputs from `iteration.prepare` and writes
the render adapter files for `builtin.render`.

Inputs:

- `iteration.manifest.json`
- `iteration.quality.json`

Outputs:

- `iteration.timeline.json`
- `iteration.manifest.json`
- `iteration.report.html`
- `iteration.quality.json`
- `hype.timeline.json`
- `hype.assets.json`

The executor does not re-walk provenance and does not summarize. It resolves
renderers by artifact `kind`, uses `generic_card` loudly for unsupported kinds,
and refuses `data_quality < 0.6` before adapter files are created unless
`--force` is supplied.

Only `--mode chaptered` is supported in v1. `--direction` is preserved as a
label; it is not parsed into structured creative instructions.
