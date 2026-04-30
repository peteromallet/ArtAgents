# Sprint 8 — Themed render via orchestrator

**Phases covered:** Phase 8 (REQUIRED final phase)
**Repos touched:** `reigh-worker-orchestrator`, `banodoco-workspace` (worker image), `reigh-workspace`
**Estimated:** ~5 pw, 2 engineers
**Risk:** headless Chrome/Remotion reliability in container; mixed media+themed timeline strategy; render time/cost; same SD-035 worker-runtime contract dependency as Sprint 7.
**Demoable milestone:** Reigh user authors a themed timeline (existing or via Sprint 7 chat-driven generation), clicks Render, gets an MP4 in the storage bucket. End-to-end value.

## Scope

Add the `banodoco_render_timeline` task type to `reigh-worker-orchestrator`. The same `banodoco-worker` image from Sprint 7 picks up render tasks, runs `npx remotion render TimelineComposition --props=<timeline-json>`, uploads the MP4 to Reigh's render-output storage path, and writes the render-task record. **`reigh-worker` (the existing ffmpeg/Python worker) is NOT modified** — it stays focused on media-bearing-timeline stitching; themed timelines route to the new task type.

### Pre-conditions

- Sprint 7 deliverables in place. SD-035 worker-runtime decision applies here too — same image serves both task types.
- Reigh's render UI knows to route themed timelines to `banodoco_render_timeline` and pure-media timelines to the existing reigh-worker path. This routing is part of this sprint's deliverable 3.

### Why this sprint exists (load-bearing)

Without it, Reigh users who author a themed timeline literally cannot click render and get an MP4:
- `reigh-worker/source/task_handlers/join/clip_preprocessor.py:48-50` raises `ValueError: "clip {idx} missing 'url'"` on any pure-generative clip.
- `reigh-worker/source/task_handlers/tasks/task_registry.py` has no `render_timeline` / `render_remotion_clip` handler.
- `reigh-worker/source/task_handlers/join/final_stitch.py:14-27` has zero Remotion / Node imports (codex ground-truth — the load-bearing claim is no JS/Node presence).

This is what flipped Phase 8 from optional to required (SD-027) once we audited the actual render path.

### Deliverables

1. **New orchestrator task type:** `banodoco_render_timeline` registered at `reigh-worker-orchestrator/api_orchestrator/task_handlers.py:15-33` with dispatch through `main.py:64-74`. Same image as `banodoco_timeline_generate` (Sprint 7); different Python entry point routes the task to `npx remotion render` instead of the pipeline.
2. **Task payload (SD-034 honored):**
   ```
   {
     timeline_id: string,
     timeline: TimelineConfig,           // resolved at enqueue time so render is reproducible
     assets: AssetRegistry,
     theme_id: string,
     output_filename: string,            // suggested name; worker may suffix with task_id
     user_jwt: string,                   // SD-022 authorization gate
     project_id: string,
     correlation_id: string              // SD-034 correlation
   }
   ```
3. **Reigh editor render-action routing:** the existing render button's handler inspects the `TimelineConfig` for any clip whose `clipType` is registry-registered to a theme package. If yes, enqueue `banodoco_render_timeline`. Otherwise enqueue the existing reigh-worker render task. Mixed timelines route to `banodoco_render_timeline` per architecture-doc decision (preferred-for-simplicity option (a)).
4. **Worker render flow:**
   1. Pull task; verify user JWT against JWKS; confirm project ownership (SD-022 same as Sprint 7).
   2. Resolve `assets` to local files (download from Reigh's `timeline-assets` bucket if needed; cache by sha256 to make retries cheap).
   3. Run `npx remotion render TimelineComposition --props=<timeline-json>` against `@banodoco/timeline-composition` and the appropriate `@banodoco/timeline-theme-<id>` peer-dep package.
   4. **Artifact upload (SD-034):** `<user_id>/<timeline_id>/<task_id>.mp4` in Reigh's render-output storage bucket. Storage RLS path scheme matches Phase 6's user-first key convention. **Retry policy:** N=3 retries on upload failure; on final failure, post task-failure with code `render_artifact_upload_failed` and a worker-logs URL.
   5. Write the render-task record via Reigh's existing render-task RPC, again as the sole writer for this artifact.
   6. Post task-completion with the storage URL.
5. **Mixed-timeline strategy (architecture-doc decision):** themed + media timelines render end-to-end inside `banodoco_render_timeline` (the worker pulls the media assets and Remotion handles the composition uniformly). The alternative — produce themed-clip MP4 segments that ffmpeg-worker joins — is rejected for v1 as adding cross-task coordination cost.
6. **Reigh worker untouched.** No edits to `reigh-worker/source/`. Pure-media timelines continue to route to the existing path. Document the routing logic so future contributors know which worker handles which timeline shape.

### Exit criteria

1. End-to-end test: user opens an existing 2rp hype-reel timeline in Reigh, clicks Render, receives an MP4 in their storage bucket. MP4 is byte-equivalent (or normalized-equivalent) to what `tools/pipeline.py` + `npx remotion render` produces locally for the same timeline.
2. Mixed timeline (themed + media): renders correctly via `banodoco_render_timeline`. Pure-media timeline still routes to and renders via the existing `reigh-worker` path.
3. SD-034 contract spot-checks: correlation_id surfaces in worker logs and in the render-task record; retry of an MP4-upload-failure preserves the same `task_id` filename so the second worker's success doesn't create a duplicate file.
4. Cost / time recorded: median wall-clock and orchestrator-cost for one 2rp hype reel rendered via this path. Documented for capacity planning.
5. `worker_unavailable` and `render_artifact_upload_failed` error codes both reachable in test scenarios; surfaces correctly in Reigh's UI.

### Out of scope (deliberate)

- Editing render-output storage paths after the task completes (CDN, cleanup, lifecycle policies) — separate operations work.
- Tearing down `reigh-worker` (it stays for pure-media timelines).
- Multi-theme-per-timeline rendering — Q6 in architecture doc; deferred (v1 enforces one theme per timeline).

## Settled decisions to inherit

- SD-027 (server-side render of themed timelines is REQUIRED).
- SD-028 (Phase 7+8 hosting on reigh-worker-orchestrator with single `banodoco-worker` image).
- SD-022 (auth split — same as Sprint 7).
- SD-034 (Task Lifecycle Contract — second instance after Sprint 7).
- SD-035 (worker-runtime contract — same decision as Sprint 7).
- SD-GATE-004 (reigh-worker not rewritten).

## Risks

- **Headless Chrome reliability.** Remotion-in-container has well-documented memory and font-loading footguns. Allocate Sprint-day-1 to a smoke test rendering the 2rp brief in the actual container, not on a developer laptop.
- **Render times for long timelines.** A 60s themed timeline at 1920×1080@30fps renders in O(minutes) on Chrome, not seconds. Default orchestrator task timeout may need to be lifted for `banodoco_render_timeline`. Capture in deliverable 4's task-config.
- **Mixed-timeline strategy** chose option (a) end-to-end-in-banodoco-worker. If render performance is unacceptable for media-heavy mixed timelines, fall back to option (b) (themed segments + ffmpeg join). Document the trigger for that pivot.
- **Asset cache cost.** The worker downloads from Reigh's storage to render. If the cache disk fills under load, evict by LRU. Capture in operations runbook (out of scope deliverable for the sprint, in scope for documentation).

## Sources / citations to verify

- `reigh-worker-orchestrator/api_orchestrator/task_handlers.py:15-33` and `main.py:64-74` (task registration + dispatch — codex ground-truth).
- `reigh-worker/source/task_handlers/join/clip_preprocessor.py:48-50` (the load-bearing ValueError that proved Phase 8 is required).
- `reigh-worker/source/task_handlers/tasks/task_registry.py` (no render_timeline handler today).
- `reigh-worker/source/task_handlers/join/final_stitch.py:14-27` (no Node/Remotion presence — load-bearing for not-touching-reigh-worker).
- `tools/render_remotion.py:277-324`, `:307-310` (props passed to Remotion — must match worker invocation).
- Reigh's existing render-task RPC (locate during pre-sprint investigation; equivalent to `update_timeline_config_versioned` but for render-task records).
- `reigh-app/supabase/migrations/` glob for render-output storage bucket + RLS migration (may need to ship one if it doesn't exist).
