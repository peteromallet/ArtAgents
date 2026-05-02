# Generate Image Executor

Use `builtin.generate_image` when an agent needs bitmap image assets for timelines,
collages, pitch frames, visual treatments, or fallback art packs.

This executor wraps `artagents.executors.generate_image.run` and expects a prompt file. Put one
prompt per line, or provide a JSON/JSONL list accepted by the underlying CLI.

## Commands

Inspect:

```bash
python3 -m artagents executors inspect builtin.generate_image
```

Dry-run:

```bash
python3 -m artagents executors run builtin.generate_image \
  --out runs/example-images \
  --input prompts_file=runs/example-images/prompts.txt \
  --dry-run
```

Run:

```bash
python3 -m artagents executors run builtin.generate_image \
  --out runs/example-images \
  --input prompts_file=runs/example-images/prompts.txt
```

## Outputs

- Images are written under `{out}/images`.
- The generation manifest is written to `{out}/manifest.json`.

## Requirements

Requires `OPENAI_API_KEY` in the environment or a supported local env file.

If one prompt is rejected by the image API, the current underlying CLI stops at
that failure. For batch work, prefer smaller prompt files so a single blocked
prompt does not waste earlier planning.
