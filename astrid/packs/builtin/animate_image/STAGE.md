# Animate Image

Restyle the **first frame** of a driver video to match a style reference image, then animate that styled frame using the original video as the motion driver. Two fal calls; one MP4 out.

## Pipeline

1. **Probe + extract** — `ffprobe` reads the video's WxH; `ffmpeg` writes `first_frame.png`. Target gpt-image-2 size is snapped from the video dimensions to the nearest multiples of 16 within gpt-image-2's pixel/edge bounds, so the styled frame matches the video's aspect ratio.
2. **Restyle** — fal `openai/gpt-image-2/edit` with `image_urls=[first_frame, style_image]` and a default prompt that says: *keep image 1's composition / pose / framing exactly; adopt image 2's style*. One PNG out.
3. **Animate** — fal `fal-ai/wan/v2.2-14b/animate/move` with `image_url=<styled image>` and `video_url=<driver video>`. Wan Animate Move replays the driver's motion onto the subject in the styled image.

Both calls inline files as base64 `data:` URIs (no separate upload). Requires `FAL_KEY`. Requires `ffmpeg` + `ffprobe` on PATH.

## Inputs

- `--style-image PATH` *(required)* — the look to adopt.
- `--ref-video PATH` *(required)* — driver video; first frame becomes the composition target.
- `--out PATH` *(required)* — output directory.
- `--prompt TEXT` — override the default style-transfer prompt.
- `--quality` — `low|medium|high|auto` (default `high`).
- `--output-format` — `png|jpeg|webp` (default `png`).
- `--resolution` — Wan Animate output: `480p|580p|720p` (default `720p`).
- `--num-inference-steps N` — default `20`. With `--use-turbo`, try `6`.
- `--guidance-scale F` — default `1`.
- `--shift F` — 1.0..10.0, default `5`.
- `--video-quality` — `low|medium|high|maximum` (default `high`).
- `--use-turbo` — fast/cheap path.
- `--seed N` — Wan Animate seed.
- `--env-file PATH` — env file with `FAL_KEY`.
- `--dry-run` — plan + extract first frame, skip both API calls.
- `--skip-generate` + `--use-image PATH` — skip stage 1 and animate the supplied image directly.

## Outputs

```
{out}/
  plan.json          # full request plan
  first_frame.png    # extracted from --ref-video
  generated.png      # stage-1 output (styled first frame)
  animation.mp4      # stage-2 output
  manifest.json      # full record of both stages
```

## Example

```bash
python3 -m astrid.packs.builtin.animate_image.run \
  --style-image ~/Desktop/cGh6S8rc_400x400.jpg \
  --ref-video ~/Desktop/Input.mov \
  --out runs/animate-image-001
```
