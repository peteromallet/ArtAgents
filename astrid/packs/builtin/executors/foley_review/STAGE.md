# Foley Review Executor

Use `builtin.foley_review` after Foley generation to eyeball each tile clip
paired with its generated audio. Output is a single static `review.html` that
can be opened directly in a browser. Each tile has thumbs-up / thumbs-down
buttons; pressing a button writes a per-tile flag to `flagged.json` next to
`review.html` (via a tiny `download` step — no server required).

Inspect first:

```bash
python3 -m astrid executors inspect builtin.foley_review --json
```

Run:

```bash
python3 -m astrid.packs.builtin.executors.foley_review.run \
  --manifest runs/foley_map/example/tiles.json \
  --out runs/foley_map/example/review.html
```

Open `runs/foley_map/example/review.html` in your browser. Audio paths in the
manifest are resolved relative to the manifest file's parent directory.
