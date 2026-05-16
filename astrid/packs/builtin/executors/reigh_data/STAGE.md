---
name: "reigh-data"
description: "Fetch canonical Reigh project, shot, task, timeline, image, and video data through the reigh-app PAT-authenticated Edge Function."
---

# Reigh Data Executor

Use `builtin.reigh_data` when an Astrid workflow needs live Reigh project,
shot, task, timeline, image, or video data. Do not query Supabase tables
directly from Astrid: the canonical read path is the `reigh-data-fetch` Edge
Function in `reigh-app`, which reuses the app's query shapes and ownership
checks.

## Environment

Set a Personal Access Token and one URL:

```bash
export REIGH_PAT=<personal-access-token>
export SUPABASE_URL=https://<project-ref>.supabase.co
```

You can also set `REIGH_DATA_FETCH_URL` to the full function URL, or
`REIGH_API_URL` to the Supabase base URL. The executor checks nearby `this.env`
and `.env` files, including the sibling `reigh-app` checkout.

## Commands

Fetch a whole project payload:

```bash
python3 -m astrid reigh-data --project-id <PROJECT_UUID> --out runs/reigh/project.json
```

Fetch one shot's app-shaped media and positions:

```bash
python3 -m astrid reigh-data \
  --project-id <PROJECT_UUID> \
  --shot-id <SHOT_UUID> \
  --out runs/reigh/shot.json
```

Fetch task params/settings/output and timeline config/assets in the same
payload:

```bash
python3 -m astrid reigh-data \
  --project-id <PROJECT_UUID> \
  --task-id <TASK_UUID> \
  --timeline-id <TIMELINE_UUID>
```

The canonical executor entry point can also run it directly:

```bash
python3 -m astrid executors run builtin.reigh_data --out runs/reigh --input project_id=<PROJECT_UUID>
```

## Payload Contract

The response is intentionally a thin copy of the app's read surfaces:

- `project` and `project_settings`
- `shots` plus `shot_settings`
- `shot_media.by_shot[shot_id].timeline_images`
- `shot_media.by_shot[shot_id].unpositioned_images`
- `shot_media.by_shot[shot_id].video_outputs`
- `project_media.items`, `project_media.images`, and `project_media.videos`
- `tasks` and `task_settings[task_id]`
- `timelines` with raw `config` and `asset_registry`

Shot media preserves `timeline_frame` and derives `position` as
`floor(timeline_frame / 50)`, matching the current app bucket semantics.
Primary variant URLs are preferred over original generation URLs, matching
gallery display behavior.

## Guardrails

- Always pass `project_id`. Optional `shot_id`, `task_id`, and `timeline_id` are
  filters inside that project, not standalone lookup keys.
- Treat `tasks[].params`, `task_settings`, timeline `config`, and
  `asset_registry` as Reigh-owned JSON. Do not rewrite their schema in
  Astrid.
- For new fetch needs, extend the Reigh edge function first, then update this
  client. Do not add direct table queries in Astrid.
