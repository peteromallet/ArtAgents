# Foley Map Orchestrator

Use `builtin.foley_map` to turn one video into a spatial Foley soundscape: the
original video plays in the browser, with N Foley tracks anchored to spatial
regions of the frame, mixed by viewport position.

Pipeline:

1. **`builtin.tile_video`** — split the video into an MxN grid of overlapping
   tile clips + first-frame PNGs.
2. **`builtin.visual_understand`** on the global first frame → one-paragraph
   scene description used as shared context.
3. **`builtin.visual_understand`** on each tile's first frame, with the global
   context injected → a focused Foley prompt per tile.
4. **`external.fal_foley`** for each tile clip + prompt → one audio file per
   tile.
5. **`builtin.foley_review`** → static review page for sense-checking. Pause
   here, eyeball the tracks, optionally re-run with `--retry-flagged`.
6. **`builtin.spatial_audio_page`** → final viewer page.

Inspect first:

```bash
python3 -m astrid orchestrators inspect builtin.foley_map --json
```

Dry-run (no API calls; writes the plan + tile crops + frames):

```bash
python3 -m astrid orchestrators run builtin.foley_map -- \
  --video ~/Downloads/DeepSeaBaby_444_TurbulentDisplace.mp4 \
  --out runs/foley_map/deepsea \
  --grid 4x4 --overlap 0.25 --trim 15 \
  --dry-run
```

Run end-to-end:

```bash
python3 -m astrid orchestrators run builtin.foley_map -- \
  --video ~/Downloads/DeepSeaBaby_444_TurbulentDisplace.mp4 \
  --out runs/foley_map/deepsea \
  --grid 4x4 --overlap 0.25 --trim 15 \
  --env-file .env
```

Stop after Foley + review (skip the final viewer):

```bash
python3 -m astrid orchestrators run builtin.foley_map -- \
  --video ... --out runs/foley_map/deepsea \
  --stop-after review
```

Re-roll only tiles flagged in `flagged.json` (downloaded from `review.html`):

```bash
python3 -m astrid orchestrators run builtin.foley_map -- \
  --video ... --out runs/foley_map/deepsea \
  --retry-flagged runs/foley_map/deepsea/flagged.json
```

Cost: 16 tiles × ~$0.10 per 10s ≈ ~$30/pass at trim=15, plus 17 cheap VLM
calls. Reruns are content-cached: tiles with unchanged `(clip_hash, prompt)`
won't re-call fal.

Outputs (under `--out`):

```
tiles.json              # final manifest with prompts and audio paths
tiles/<r>_<c>.mp4       # per-tile video (input to Foley)
frames/<r>_<c>.png      # per-tile first frame (input to VLM)
frames/global.png       # global first frame
prompts.json            # global context + per-tile prompts
audio/<r>_<c>.wav       # per-tile Foley audio
review.html             # sense-check page
page/index.html         # final spatial-audio viewer
```
