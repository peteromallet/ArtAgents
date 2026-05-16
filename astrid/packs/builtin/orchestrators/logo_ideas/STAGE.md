# Logo Ideas

Generate a grid of distinct logo concepts from a single brief.

Pipeline:
1. **Concepts** — call Kimi K2 on Fireworks (`accounts/fireworks/models/kimi-k2p5` by default) to expand the brief into N varied logo prompts.
2. **Renders** — call fal.ai with one prompt per image. Default provider is `z-image` (`fal-ai/z-image/turbo`, 1 image per call). Pass `--provider gpt-image` to use `openai/gpt-image-2` instead.
3. **Grid** — assemble a contact sheet of all renders for review.

## Inputs

- `--ideas` *(required)* — free-form brief: brand, vibe, motifs, constraints.
- `--count` — number of logos to generate. Default `9`.
- `--out` *(required)* — output directory. Concepts, prompts, images, and the grid land here.
- `--provider` — `z-image` (default) or `gpt-image`.
- `--model` — override the Fireworks chat model id.
- `--image-size` — fal image size preset or `WIDTHxHEIGHT`. Default `square_hd`.
- `--env-file` — env file containing `FIREWORKS_API_KEY` and `FAL_KEY`.
- `--dry-run` — write the plan, skip both API calls.

## Env

- `FIREWORKS_API_KEY` — required for the concept step.
- `FAL_KEY` — required for the render step.

Both are looked up from the `--env-file`, `this.env`, `.env`, or the standard workspace fallbacks.

## Outputs

```
{out}/
  logo-plan.json
  concepts.json          # raw concepts from Kimi (prompt, name, rationale)
  prompts.json           # final prompts sent to fal
  images/logo-001.png ...
  grid.jpg               # contact sheet of all renders
  logo-manifest.json     # per-candidate result with image paths
```
