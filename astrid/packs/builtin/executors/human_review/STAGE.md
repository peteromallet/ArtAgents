---
name: human_review
description: Generic human-gate primitive. Serves a project HTML page, collects schema-validated JSON decisions, blocks until submit.
---

# Human Review

Reusable HTTP server for human-in-loop steps. Any orchestrator that needs a
human to look at something and produce a structured decision passes its own
HTML page + JSON data, and gets back validated JSON.

## CLI

```
python3 -m astrid.packs.builtin.executors.human_review.run \
  --html <path>            # file or dir; served at /
  --data <path>            # JSON file, served at /data.json (read-only)
  --serve /prefix=<dir>    # repeatable; static mount
  --state <path>           # POST /save writes here (partial, per-keystroke)
  --out <path>             # POST /submit writes here, server exits 0
  --response-schema <path> # optional; strict JSON-schema validation of /submit
  --port 0                 # auto-pick free port (default)
  --no-open                # skip browser auto-launch
  --timeout 0              # exit nonzero after N seconds if no submit (0=unlimited)
```

On startup the executor prints **one line** containing the URL with the
session token query param. Open it in any browser if `--no-open` is set.

## Routes

| Method | Path                   | Behavior |
|--------|------------------------|----------|
| GET    | `/?token=<t>`          | Serves `--html` (file content or dir's `index.html`). |
| GET    | `/data.json`           | Read-only mount of `--data`. |
| GET    | `/state.json?token=<t>`| Returns `--state` contents (200), or 404 if absent. |
| GET    | `/<prefix>/...`        | Static mount per `--serve PREFIX=DIR`. Supports HTTP Range for mp4 seeking. |
| POST   | `/save`                | Atomic write of body to `--state`. Returns 204. Token required. |
| POST   | `/submit`              | Schema-validate body, atomic write to `--out`, signal shutdown. Returns 204 on success / 400 on schema fail (state/out unchanged). Token required. |

## Static mounts are unauthenticated by design

`<video>` and `<img>` tags can't easily send custom auth headers, so static
GETs under `--serve` mounts are **not** token-checked. Don't mount sensitive
content; mount only the media the page needs. POSTs and `/state.json` ARE
token-checked.

## Reuse pattern

The HTML decides the response shape; the executor only validates against
the supplied schema. Same primitive serves dataset-review, eval-grid pick,
arrangement approval — write the HTML next to the orchestrator that uses it.
