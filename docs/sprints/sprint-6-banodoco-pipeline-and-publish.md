# Sprint 6 — Banodoco pipeline retargeting + publish-to-Reigh

**Phases covered:** Phase 5 + Phase 6
**Repos touched:** `banodoco-workspace`, `reigh-workspace`
**Estimated:** ~5 pw, 2 engineers
**Risk:** Supabase auth/storage/RLS edge cases; content-addressed asset idempotency.
**Demoable milestone:** `tools/pipeline.py publish` ships a Banodoco-authored timeline into Reigh; user opens Reigh and previews it correctly.

## Scope

Two phases share this sprint because Phase 5 is small (codex estimate: 2 pw) and naturally pairs with Phase 6's CLI-side work. Phase 5 retargets Banodoco's pipeline at the shared composition / schema. Phase 6 ships the publish path: CLI uploads assets, edge function imports the timeline.

### Deliverables

#### Phase 5 — Banodoco pipeline retargeting (2 pw)

1. `tools/cut.py:476/554`, `tools/pool_merge.py`, `tools/arrange.py`, `tools/pipeline.py` import `TimelineConfig` / `TimelineClip` directly from `banodoco-timeline-schema` (Sprint 1+2 work consolidated). All Banodoco-side hand-written TypedDicts gone.
2. `materialize_output()` invoked from `tools/cut.py` and `tools/pipeline.py` so every emitted timeline carries the canonical `output` block.
3. `tools/render_remotion.py:314-324` updated to bundle `@banodoco/timeline-composition`; Range HTTP server preserved per `:295`. Verified: `npx remotion render TimelineComposition --props=...` against the 2rp brief produces the same MP4 byte-equivalent (or normalized-equivalent) to pre-Sprint-1 output.
4. Strict validation now in effect (`strict: true`) per Sprint 5 deliverable.

#### Phase 6 — Publish CLI + edge function (3 pw)

5. **CLI surface (PROPOSED):** `tools/pipeline.py publish --project-id <PID> --timeline-id <TID> [--expected-version <N>] [--create-if-missing] [--force] [--timeline-file <path>]`. Reads `REIGH_USER_TOKEN` (Supabase user JWT only — **NOT a PAT**) from env. Decodes JWT to obtain `user_id`.
6. **Asset Handoff with idempotency policy:** for each non-HTTP entry in Banodoco's `assets` object (`render_remotion.py:307-310`):
   - Construct storage key `<user_id>/<timeline_id>/<sha256(content)>.<ext>` (RLS-compliant per migration `20260325090001_create_timeline_assets_bucket.sql:15-35`; matches existing convention at `SupabaseDataProvider.ts:244-268`).
   - **Idempotency:** Supabase Storage HEAD on the key first. On 200, treat as success and skip upload. Otherwise `.upload(key, file, { upsert: false })` matching `SupabaseDataProvider.ts:253-260`. Reject `upsert: true`. On 409/duplicate-object error from a race, treat as success (sha256 == sha256).
   - Rewrite in-memory `asset_registry` to bucket keys.
   - Submit `{timeline, asset_registry}` to import endpoint.
   - Pure-generative timelines skip upload.
7. **`reigh-app/supabase/functions/timeline-import/` edge function:**
   - Reuses `_shared/auth.ts` `authenticateRequest()` from `:68-160` and project-ownership helpers at `:163-228`. NO bespoke JWT/PAT parser.
   - Validates payload against shared Zod validator from `@banodoco/timeline-schema`.
   - Writes via `update_timeline_config_versioned(p_timeline_id, p_config, p_expected_version)` per `SupabaseDataProvider.ts:74-99`. Returns 409 on version mismatch.
8. **Concurrency handshake:** CLI obtains `expected_version` via (a) sibling `timeline-export` GET / `get_timeline_version` RPC (PROPOSED — default), (b) explicit `--expected-version`, or (c) `--force` for fetch-then-write inside the edge function. 409 → CLI prints actionable error.
9. **Auth + ownership:** SD-GATE-005 + SD-022 split: user JWT authorizes; service-role used by the edge function only after `authenticateRequest()` and ownership check pass. Missing row + `--create-if-missing` requires project ownership and inserts caller as owner.

### Exit criteria

1. From a fresh checkout, run `tools/pipeline.py` end-to-end against the 2rp brief, then `tools/pipeline.py publish --project-id <test_pid> --timeline-id <test_tid>` succeeds. Open Reigh in the browser; the new timeline loads and previews correctly via the shared composition.
2. Run publish twice in a row against the same content: second run no-ops on uploads (HEAD-check) and 409s on the version write. CLI prints actionable error.
3. Run with stale `--expected-version`: 409 returned with a clear "version is now N, retry with `--expected-version N` or `--force`" message.
4. PAT token in `REIGH_USER_TOKEN` is rejected at CLI startup with a clear error pointing to SD-024 / future enhancement.
5. Banodoco's local CLI render still works (Phase 5 regression).

### Out of scope (deliberate)

- Bidirectional agent handoff (`delegateToBanodocoAgent` tool, `banodoco_timeline_generate` task type) — Sprint 7.
- Themed-timeline render via orchestrator — Sprint 8.
- Edge-mediated upload path for PAT users — future enhancement, not this sprint.

## Settled decisions to inherit

- SD-011 (publish-to-reigh transport: user-first storage key, HEAD-check + upsert: false + treat-409-as-success).
- SD-012 (edge function reuses `_shared/auth.ts`).
- SD-013 (concurrency via real RPCs with `p_expected_version`).
- SD-014 (publish-to-reigh vs render-task separation).
- SD-018 / SD-022 (PAT rejection on this path; future edge-mediated upload path is the alternative).
- SD-031 / SD-032 (asset registry semantics — Phase 6 path is the inverse direction of Phase 7's; the asymmetry is intentional).

## Risks

- **RLS edge case: existing assets uploaded by another user.** If a previously-uploaded asset's path doesn't match the calling user's `user_id` segment, the HEAD will 403, not 200. Treat 403 as "asset is owned by someone else; cannot proceed without `--force-reupload-as-mine`" — design but don't ship the flag in v1.
- **`get_timeline_version` RPC may not exist** in Reigh's current SQL. Confirm in implementation phase; add it if missing (cheap migration).
- **Edge-function import of shared Zod validator.** Same Deno/edge bundling concerns as Sprint 4; should be solved by then.
- **Phase 4 spillover from Sprint 5.** If Sprint 5's renderer dispatch slipped, Sprint 6 may need to absorb it before Phase 6 work. Surface to project owner if so.

## Sources / citations to verify

- `tools/pipeline.py`, `tools/cut.py`, `tools/pool_merge.py`, `tools/arrange.py` (Phase 5 retargets).
- `tools/render_remotion.py:277-324`, `:295`, `:307-310`, `:314-324`.
- `tools/timeline.py:785` (validate_timeline strict).
- `reigh-app/src/tools/video-editor/data/SupabaseDataProvider.ts:74-99` (versioned RPC), `:244-268` (uploadAsset path), `:253-260` (`.upload(..., {upsert: false})`).
- `reigh-app/supabase/migrations/20260325090001_create_timeline_assets_bucket.sql:15-35` (RLS — first folder segment must equal `auth.uid()::text`).
- `reigh-app/supabase/functions/_shared/auth.ts:68-160` (`authenticateRequest()`), `:163-228` (project ownership helpers).
- `reigh-app/supabase/migrations/` glob for `update_timeline_config_versioned` / `update_timeline_versioned`.
