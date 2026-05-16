# fal Hunyuan-Video Foley Executor

Use `external.fal_foley` to score one short video clip with a Foley track via
fal.ai's `fal-ai/hunyuan-video-foley` model. Network-bound. One clip in, one
audio file out, prompt-conditioned.

Inspect first:

```bash
python3 -m astrid executors inspect external.fal_foley --json
```

Run:

```bash
python3 -m astrid executors run external.fal_foley \
  --input clip=runs/tile_video/example/tiles/0_0.mp4 \
  --out runs/foley/0_0.wav \
  -- --prompt "underwater turbulence, dense bubbles, organic motion"
```

Direct invocation:

```bash
python3 -m astrid.packs.external.executors.fal_foley.run \
  --clip runs/tile_video/example/tiles/0_0.mp4 \
  --prompt "underwater turbulence, dense bubbles, organic motion" \
  --out runs/foley/0_0.wav \
  --env-file .env
```

Inputs:

- `--clip` mp4/mov/webm/m4v/gif, ≤15s recommended.
- `--prompt` short natural-language description of what should sound.

Output: one audio file at `--out`. Format follows whatever fal returns
(typically wav). A sidecar `<out>.fal.json` records the request id, model id,
prompt, and source URL.

Cost: ~$0.10 per 10s of input video. Requires `FAL_KEY` (env var or `.env`).
