# Search LoRAs

Use `builtin.search_loras` when you need to discover Hugging Face Hub LoRA
adapter repositories for a specific base model.

The executor calls the Hugging Face Hub model search endpoint with:

- `filter=lora`
- `filter=base_model:<base-model>`
- `full=true` so returned repository file names and tags can be inspected

Inspect first:

```bash
python3 -m astrid executors inspect builtin.search_loras --json
```

Dry-run through the canonical executor CLI:

```bash
python3 -m astrid executors run builtin.search_loras \
  --input base_model=stabilityai/stable-diffusion-xl-base-1.0 \
  --out runs/search-loras \
  --dry-run
```

Run:

```bash
python3 -m astrid executors run builtin.search_loras \
  --input base_model=stabilityai/stable-diffusion-xl-base-1.0 \
  --out runs/search-loras
```

Direct run with additional options:

```bash
python3 -m astrid.packs.builtin.search_loras.run \
  --base-model stabilityai/stable-diffusion-xl-base-1.0 \
  --match "cinematic" \
  --limit 50 \
  --fetch-limit 200 \
  --sort downloads \
  --out runs/search-loras/search-loras.json
```

## Inputs

- `--base-model` *(required)* — Hugging Face repo id for the model the LoRA
  should be based on.
- `--query` — optional Hugging Face API text search. If the Hub returns no
  results, Astrid retries a broader base-model search and applies the query as
  a local match across repo id, tags, and filenames.
- `--match` — local substring filter across repo id, tags, and `.safetensors`
  filenames after fetching broader results. May be repeated; all terms must
  match. Prefer this for intent filters like `realism`, `photography`, or
  `35mm`.
- `--match-mode {all,any}` — whether all `--match` terms or any one term must
  match. Use `any` for synonym searches such as `photo`, `realism`, `35mm`.
- `--limit` — maximum results to request. Default `25`.
- `--fetch-limit` — how many Hub results to fetch before applying `--match`.
  Defaults to `max(limit, 100)` when `--match` is used.
- `--sort` — Hub sort field. Default `downloads`.
- `--direction` — `-1` descending or `1` ascending. Default `-1`.
- `--list-base-models` — scan LoRA repositories and list discovered
  `base_model:*` tags instead of searching one base model. Use `--match` to
  focus the scan and `--fetch-limit` to increase coverage.
- `--base-model-match` — with `--list-base-models`, filter the extracted base
  model ids themselves. Use this when you want model names matching `z-image`
  without unrelated repos that merely mention Z-Image.
- `--token` — optional Hugging Face token. Prefer environment variables.
- `--timeout` — request timeout in seconds. Default `30`.
- `--out` — write JSON results to this file. If omitted, prints JSON.
- `--compact` — print or write compact JSON.

## Finding Base Model Names

Hugging Face does not expose `base_model` as a complete tag group in
`models-tags-by-type`. To discover usable base model ids, scan LoRA repos and
extract their `base_model:*` tags:

```bash
python3 -m astrid.packs.builtin.search_loras.run \
  --list-base-models \
  --base-model-match z-image \
  --fetch-limit 1000 \
  --out runs/search-loras/base-models.json
```

## Env

- `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` — optional. Used only for the
  Authorization header; never written to output.

## Outputs

The JSON output contains the normalized search request, result count, a
`guidance` object, and a `results` array. `guidance.messages`,
`guidance.next_commands`, and `guidance.next_executor_commands` are intended for
agents: they explain sparse searches, fallback behavior, direct-module query
fragments, and full canonical `executors run` commands to try next. Each result
includes repo id, URL, downloads, likes, dates, pipeline/library metadata,
base-model tags, license tags, `.safetensors` file names when present, and
match diagnostics when local matching was used.
