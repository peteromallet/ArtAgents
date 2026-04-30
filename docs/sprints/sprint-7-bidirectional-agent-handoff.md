# Sprint 7 — Bidirectional agent handoff

**Phases covered:** Phase 7
**Repos touched:** `reigh-workspace`, `reigh-worker-orchestrator`, new `banodoco-worker` image (built from `banodoco-workspace`)
**Estimated:** ~5 pw, 2 engineers
**Risk:** orchestrator task-registration details; JWT/JWKS verification; conflict UX during in-flight generation; SD-035 worker-runtime contract MUST be settled before this sprint starts.
**Demoable milestone:** Reigh chat enqueues "extend this hype reel by 15 seconds in the 2rp style"; the worker writes the new TimelineConfig directly; Reigh editor's realtime subscription picks it up and shows the extended timeline.

## Scope

Reigh's `ai-timeline-agent` gains a single new tool that delegates generative authoring to a `banodoco-worker` running as a typed task on `reigh-worker-orchestrator`. The worker writes the result directly via `update_timeline_config_versioned`; the agent does not apply the returned config. SD-034's task-lifecycle contract is implemented for the first time here and becomes the template for Sprint 8.

### Pre-conditions (load-bearing)

- **SD-035 settled.** The worker-runtime choice (Pinned Railway service / per-task RunPod / in-process Python wrapper) is decided and documented before any code lands. This sprint assumes the recommended default — Pinned Railway service polling the orchestrator for typed tasks. If a different option is picked, deliverable 4 below changes shape but the contract stays the same.

### Deliverables

1. **New orchestrator task type:** `banodoco_timeline_generate` registered in `reigh-worker-orchestrator/api_orchestrator/task_handlers.py:15-33` (codex ground-truth — this is a Python-handler registry; dispatch at `api_orchestrator/main.py:64-74`). The Python handler enqueues the task to the `banodoco-worker` pool and tracks status; it does NOT itself run the generation.
2. **Task payload schema (SD-034 + SD-022 honored):**
   ```
   {
     intent: string,
     brief_inputs: { transcript?, sources?, ... },
     theme_id: string,
     current_timeline?: TimelineConfig,
     expected_version: number,           // required (SD-013, SD-034 idempotency)
     scope: "full" | "insert" | "replace_range",
     user_jwt: string,                   // SD-022 authorization gate
     project_id: string,
     timeline_id: string,
     correlation_id: string              // SD-034 correlation
   }
   ```
3. **`banodoco-worker` container image** — Node + Remotion + Chrome + shared `@banodoco/timeline-composition` + theme packages baked in, plus the Python pipeline (`tools/pipeline.py`, `tools/arrange.py`, `tools/cut.py`, `tools/pool_merge.py`). Image build job lives under `banodoco-workspace/`. **Boot health check** — worker reports `ready` before claiming work. **`worker_unavailable` task-status** when no worker can claim within N seconds (N defaults to 30s; configurable).
4. **Worker execution flow:**
   1. Pull task; verify the user JWT against Reigh's Supabase JWKS (`<reigh-project>.supabase.co/auth/v1/.well-known/jwks.json`); confirm project ownership. Reject without service-role-only fallback (SD-022).
   2. Run the Banodoco pipeline against `brief_inputs` + `theme_id`; produce a canonical `TimelineConfig` validated against `@banodoco/timeline-schema` strict mode.
   3. Write directly via `update_timeline_config_versioned(p_timeline_id, p_config, p_expected_version)` using service-role for the DB call but with `user_id` audited from the JWT (SD-022 mutation surface). Embed `correlation_id` in the timeline-version metadata.
   4. **On 409:** check whether the existing config carries the same `correlation_id` (SD-034 retry semantics). If yes, treat as success (predecessor wrote). If no, post task-failure with code `version_conflict` and a "your edits superseded the AI's, retry?" message.
   5. Post task-completion to the orchestrator with the new version number.
5. **New Reigh agent tool: `delegateToBanodocoAgent`** — registered at all four ai-timeline-agent integration sites (SD-026):
   - Tool implementation at `reigh-app/supabase/functions/ai-timeline-agent/tools/delegateToBanodocoAgent.ts`.
   - Registered in `reigh-app/supabase/functions/ai-timeline-agent/registry.ts`.
   - Schema declaration in `reigh-app/supabase/functions/ai-timeline-agent/tool-schemas.ts:10-24`.
   - Allowlist entry in `reigh-app/supabase/functions/ai-timeline-agent/tool-calls.ts:14-23`.
   - Execution branch in `reigh-app/supabase/functions/ai-timeline-agent/loop.ts:442-481`.
   - Tool body: capture `expected_version` from the current Reigh state, generate a fresh `correlation_id`, enqueue `banodoco_timeline_generate` on the orchestrator, return to the LLM with "queued, will appear in ~30s." NO synchronous HTTP call to Banodoco.
6. **Status surfacing:**
   - **Editor:** consumes the version bump via Reigh's existing realtime subscription on the `timelines` table — no new infrastructure (SD-034 status path).
   - **Agent chat:** polls the orchestrator's task-status endpoint to drive progress messages (queued → running → completed/failed). NO SSE. NO streaming partial timelines.
7. **Conflict UX (Q5 v1 default):** worker on 409 (different correlation_id) drops the result and surfaces "your edits superseded the AI's, retry?" in the chat. Three-way merge and pick-version UI are out of scope for v1.

### Exit criteria

1. End-to-end happy path: user types "extend this 2rp hype reel by 15 seconds" in Reigh chat → agent picks `delegateToBanodocoAgent` → orchestrator dispatches → worker generates and writes directly → editor's realtime subscription updates → `@remotion/player` renders the extended timeline.
2. Conflict path: user makes a surgical edit during the wait → worker's write 409s with a different `correlation_id` → agent surfaces the retry prompt.
3. Retry path: orchestrator retries a worker that crashed mid-execution → second worker's write 409s with the same `correlation_id` → treated as success (predecessor wrote).
4. Auth path: corrupted/expired user JWT in payload → worker rejects before generating; task-status surfaces an `auth_failed` reason.
5. `worker_unavailable` path: orchestrator with no warm workers → task-status reports `worker_unavailable` within 30s; agent chat reports back to the user.
6. SD-034 / SD-035 acceptance: every one of the six contract elements in SD-034 (idempotency, retry, correlation, identity, status, artifact) verifiable against this sprint's code.

### Out of scope (deliberate)

- Themed-timeline render — Sprint 8 (the `banodoco_render_timeline` task type uses the same worker image but a different Python entry).
- Three-way merge for conflicts — post-v1.
- Polling-based status UI for the editor — editor uses realtime, only the agent polls.

## Settled decisions to inherit

- SD-020 (single new tool that enqueues; surgical edits stay sync).
- SD-022 (round-trip auth — identity-vs-mutation split).
- SD-023 (Phase 7 endpoint separation from Phase 6).
- SD-026 (four-site rule).
- SD-027 (Phase 8 is REQUIRED — informs Sprint 8).
- SD-028 (Phase 7+8 hosting on reigh-worker-orchestrator).
- SD-029 (sync/async editing split).
- SD-031 / SD-032 (brief inline; assets via existing registry).
- SD-034 (Task Lifecycle Contract — implement here; this sprint is its first instance).
- SD-035 (worker-runtime contract — must be settled before this sprint starts).

## Risks

- **JWKS endpoint availability.** If Reigh's Supabase project doesn't expose JWKS at the canonical path, fall back to a service-role check-back call (SD-022 fallback). Confirm in pre-sprint.
- **Worker bundle size.** Node + Chrome + Remotion + Python pipeline in one image is large. Build with multi-stage Dockerfile; document image size and cold-boot time.
- **Long-running generation.** If the pipeline takes > orchestrator's default task timeout, raise the timeout for `banodoco_timeline_generate` specifically. Surface as a task-payload field if needed.

## Sources / citations to verify

- `reigh-worker-orchestrator/api_orchestrator/task_handlers.py:15-33` (registration entry — codex ground-truth).
- `reigh-worker-orchestrator/api_orchestrator/main.py:64-74` (dispatch).
- `reigh-app/supabase/functions/ai-timeline-agent/registry.ts`, `tool-schemas.ts:10-24`, `tool-calls.ts:14-23`, `loop.ts:442-481` (four-site rule).
- `reigh-app/supabase/functions/_shared/auth.ts:68-160`, `:163-228` (auth helpers).
- `reigh-app/src/tools/video-editor/data/SupabaseDataProvider.ts:74-99` (versioned RPC the worker calls).
- `tools/pipeline.py`, `tools/arrange.py`, `tools/cut.py`, `tools/pool_merge.py` (Banodoco generative entry points).
