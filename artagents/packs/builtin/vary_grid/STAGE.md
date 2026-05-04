# Vary Grid

Iterative grid editor. Take an existing grid image (e.g. one produced by `builtin.logo_ideas`), pick one or more cells to use as references, and produce a new grid of variations.

Pipeline:
1. **Slice** — crop the source grid into its constituent cells (auto-detected from the sibling `logo-manifest.json`, or override with `--source-rows`/`--source-cols`).
2. **Pick** — keep only the cells listed in `--cells` (e.g. `4`, `1,2`, `4,5`, `1-3`, `all`). Selected cells become reference images.
3. **Concepts** — call Kimi K2 on Fireworks to expand the brief into N distinct variation prompts. Skip with `--no-kimi` to send the brief verbatim.
4. **Edit** — single call to fal `openai/gpt-image-2/edit`, attaching the reference image(s) as base64 data-URIs and a composite grid prompt asking for an NxN contact-sheet of variations.

The output is one grid PNG. Slice it again, pick a cell, vary again — that's the loop.

## Inputs

- `--from PATH` *(required)* — path to source grid image.
- `--cells SPEC` *(required)* — which cells of the source to use as references (`4`, `1,2`, `1-3,5`, `all`).
- `--ideas TEXT` *(required)* — variation brief.
- `--out PATH` *(required)* — output directory.
- `--count N` — number of variants. Default `9`. Max `9` (single image-edits call returns one grid).
- `--source-rows N`, `--source-cols N` — override grid layout if not auto-detectable.
- `--size WxH` — gpt-image-2 size. Default `1024x1024`.
- `--quality` — `low|medium|high|auto`. Default `high`.
- `--model` — Fireworks chat model id (default Kimi K2).
- `--no-kimi` — skip the Kimi expansion; the brief becomes a single composite "N variations of attached" prompt.
- `--env-file` — env file with `FIREWORKS_API_KEY` and `OPENAI_API_KEY`.
- `--dry-run` — write the plan + ref crops, skip both API calls.

## Env

- `FAL_KEY` — required for the image-edits call.
- `FIREWORKS_API_KEY` — required for the Kimi step (skip with `--no-kimi`).

## Outputs

```
{out}/
  vary-plan.json         # the request
  refs/ref-001.png ...   # the cell crops sent as references
  concepts.json          # Kimi's per-cell variation prompts (or null with --no-kimi)
  prompts.json           # final per-cell prompts handed to gpt-image-2
  grid.png               # the new grid (single gpt-image-2 render)
  vary-manifest.json     # full record incl. the composite edit prompt
```
