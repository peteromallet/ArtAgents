# Reigh Convergence Architecture

## 1. Executive Summary + Target Architecture

Converge Banodoco's Python authoring pipeline and Reigh's web editor onto one timeline contract without merging products. Shared packages: `timeline-schema` (TS types, Zod, Python TypedDicts, `resolveTheme(timeline, themeRegistry)` [PROPOSED]), `timeline-ops` (pure edits), and `composition` (`TimelineRenderer`, effects, animations, transitions). Banodoco keeps brief -> arrange -> cut, theme data, run dirs, local render. Reigh keeps editor UI, agent loop, Supabase DB/asset registry, worker orchestration.

Non-negotiable: Banodoco keeps `npx remotion render` against shared composition with no Reigh web stack. Today it shells out at `tools/render_remotion.py:314-324`, serves assets at `tools/render_remotion.py:295`, and passes `{timeline, assets, theme}` at `tools/render_remotion.py:307-310`.

Theme content stays Banodoco-side as JSON/assets under `themes/<id>/`; runtime components become peer-dep packages like `@banodoco/timeline-theme-<id>`, replacing imports like `themes/2rp/effects/section-hook/component.tsx:4-6`.

Reigh edits to `clipType`, `params`, `theme`, and `theme_overrides` are AI-via-chat only. The real snake_case surface includes `add_media_clip`, `add_text_clip`, `set_clip_property`, `move_clip` at `reigh-app/supabase/functions/ai-timeline-agent/tools/timeline.ts:731-760`; Phase 3 keeps these routable. No inspector, property panel, theme picker, or schema-driven controls. Sole UI delta: read-only `Theme: <id>` chip with resolved JSON from `resolveTheme(timeline, themeRegistry)` [PROPOSED, `timeline-schema`; see SD-024].

```text
Banodoco CLI -> timeline-schema + timeline-ops + composition -> local npx remotion render
Reigh editor -> shared packages + @banodoco/timeline-theme-<id> peer deps -> Theme chip
publish CLI -> asset upload <user_id>/<timeline_id>/... -> timeline-import [PROPOSED] -> Reigh DB
Reigh agent -> Banodoco service [Phase 7, PROPOSED] -> update_timeline_config_versioned -> player re-render
```

Four constraints hold: local CLI render remains viable, Reigh editor/worker function, each phase ships independently, and cross-repo touches are explicit across `banodoco-workspace`, `reigh-workspace`, `shared-repo`.

## 2. Shared Package Contracts

### Schema Reconciliation

Canonical `output` adopts Reigh's current `TimelineOutput` verbatim: `{resolution: string, fps: number, file: string, background?: string | null, background_scale?: number | null}` from `reigh-app/src/tools/video-editor/types/index.ts:128-134`. Reigh parses `resolution` through `lib/config-utils.ts:9-15`, defaults it in `lib/defaults.ts:24-35`, and consumes `output.fps` in `TimelineRenderer.tsx:102-106`.

Banodoco fills this through `materialize_output(timeline, theme)` [PROPOSED]: `resolution` is `${theme.visual.canvas.width}x${theme.visual.canvas.height}`, `fps` comes from `theme.visual.canvas.fps` (`themes/2rp/theme.json:29-33`, `tools/remotion/src/Root.tsx:35-40`, `tools/timeline.py:570-585`), `file` defaults to `output.mp4` [PROPOSED], and background fields pass through.

| Banodoco source | Canonical field | Reigh consumer |
| --- | --- | --- |
| `theme.visual.canvas.width/height` | `output.resolution` | `parseResolution()` |
| `theme.visual.canvas.fps` | `output.fps` | `TimelineRenderer.tsx:102-106` |
| render default | `output.file` | export naming |
| theme/callsite background | `background`, `background_scale` | existing output type |

### `timeline-schema`

| Export | Status | Notes |
| --- | --- | --- |
| `TimelineConfig`, clip/output/asset TS types | canonical | Replaces parallel handwritten shapes. |
| `TimelineConfigSchema` Zod validator | canonical | TS+Zod is source of truth. |
| JSON Schema artifact | generated | Produced by `zod-to-json-schema`. |
| Python TypedDicts | generated | `datamodel-code-generator`; current analogue is `tools/timeline.py:115-188`. |
| `validateTimeline(config, {strict})` [PROPOSED] | exported | Replaces `tools/timeline.py:785`; `strict` is registry-aware after Phase 4. |
| `resolveTheme(timeline, themeRegistry)` [PROPOSED] | exported | Pure merge helper for Phase 2 Theme chip; ports `tools/timeline.py:622` and `tools/timeline.py:654` behavior without composition dependency. |

Versioning: semver; additive schema fields are minor releases; removals/renames require a major with a dual-shape transition.

| Consumer | Depends on |
| --- | --- |
| Banodoco | generated Python types, JSON Schema validator, `resolveTheme()` parity tests |
| Reigh | TS types, Zod validator, `resolveTheme()` for Theme chip |

### `timeline-ops`

| Export | Status | Notes |
| --- | --- | --- |
| Pure clip/track CRUD functions | extracted | From `ai-timeline-agent/tools/{timeline,clips}.ts`; `(timeline, args) -> timeline`. |
| Snake_case compatibility map | required | `add_media_clip`, `add_text_clip`, `set_clip_property`, `move_clip`, etc. stay routable via `tools/registry.ts` per SD-018. |
| Patch helpers [PROPOSED] | optional | Shared CLI/Reigh application of structured edits. |

Versioning follows `timeline-schema` peer ranges. Reigh keeps glue for DB writes, asset registry, `generation.ts`, `create-task.ts`, `duplicate-generation.ts`, `loras.ts`, and `transform-image.ts`.

| Consumer | Depends on |
| --- | --- |
| Banodoco | pure ops for authoring/rewriting timelines |
| Reigh | pure ops behind unchanged snake_case agent tools |

### `composition`

| Export | Status | Notes |
| --- | --- | --- |
| `TimelineComposition` [PROPOSED] | exported | Renames local `HypeComposition`; props stay `{timeline, assets, theme}` from `tools/render_remotion.py:307-310`. |
| `TimelineRenderer` | exported | Shared by Reigh preview and Banodoco render. |
| `registry.generated.ts` [PROPOSED] | generated | Directory-as-plugin discovery; current scanner is `tools/effects_catalog.py:139-155`. |
| `@banodoco/timeline-composition/theme-api` [PROPOSED] | exported sub-path | Re-exports `effects.types`, `lib/animations`, and `ThemeContext` for theme packages. |

Versioning is semver with peer dependency alignment to `timeline-schema`.

| Consumer | Depends on |
| --- | --- |
| Banodoco | Remotion composition + theme API for local CLI render |
| Reigh | renderer + generated registries for editor preview |

## 3. Cross-Repo Tooling

Recommendation: create a sibling shared repo that publishes `@banodoco/timeline-*` packages to npm and `banodoco-timeline-*` packages to PyPI. Reject a monorepo because Banodoco pipeline iteration, Reigh app deploys, and shared package releases need independent cadence. Reject git submodules because they defer the real problem: schema/type sync and release pinning.

TS<->Python sync is mechanical: Zod source -> `zod-to-json-schema` -> JSON Schema -> `datamodel-code-generator` -> generated Python TypedDicts -> CI diff check. The shared repo CI runs package unit tests plus cross-language schema parity. `banodoco-workspace` and `reigh-workspace` pin tilde versions, run integration suites against the pinned package, and upgrade intentionally.

Version policy: semver; minor versions allow additive fields and looser validators; major versions require transitional dual-shape parsing until both repos have migrated. Schema validation starts loose in Phase 1, matching current `tools/timeline.py:785` validation. Phase 4 adds registry-aware validation with a `strict: bool` [PROPOSED] flag once effect/animation/transition registries are shared.

## 4. Phase Plan

### Phase 1 - `timeline-schema` Extraction

Repos: `shared-repo`, `banodoco-workspace`. Order: first because every later phase needs a canonical contract. Entry: verified Banodoco schema in `tools/timeline.py:115-188`. Exit: TS+Zod package, generated Python types, reconciled `output`, `materialize_output()` [PROPOSED] using `theme.visual.canvas.fps`, and `resolveTheme()` [PROPOSED] exported from `timeline-schema`. Shippable: Banodoco can still emit its current shape while validating against the shared schema. Rollback: pin Banodoco back to local `tools/timeline.py`. Constraints: local render unchanged; Reigh untouched.

### Phase 2 - Reigh Schema Lift + Serialize Validator + Theme Chip

Repos: `reigh-workspace`. Order: after Phase 1 so Reigh imports the shared validator and `resolveTheme()`. Entry: current serializer validator at `reigh-app/src/tools/video-editor/lib/serialize.ts:98-122`. Exit: Reigh accepts `theme`, `theme_overrides`, `generation_defaults`, `clipType`, `params`, `hold`, `pool_id`, `clip_order`, optional `asset`; serializer is updated; read-only Theme chip renders `Theme: <id>` or `Theme: <id> (not installed)` from `resolveTheme()`. Shippable: existing media timelines still load and save. Rollback: remove new fields from serializer and hide chip. Constraints: only allowed editor UI delta is the chip.

### Phase 3 - `timeline-ops` Extraction Preserving AI Chat Surface

Repos: `shared-repo`, `reigh-workspace`. Order: after Reigh can store the lifted schema. Entry: snake_case handlers at `ai-timeline-agent/tools/timeline.ts:731-760`. Exit: pure ops move to shared lib; `tools/registry.ts` keeps identical names (`add_media_clip`, `add_text_clip`, `set_clip_property`, `move_clip`); Reigh glue for DB/assets/generation remains local. Shippable: LLM tool routing is unchanged. Rollback: point registry back to local functions. Constraints: Reigh editor remains functional; no inspector UI.

### Phase 4 - Composition + Plugin Registry Extraction

Repos: `shared-repo`, `banodoco-workspace`, `reigh-workspace`. Order: after schema/ops because renderer needs stable clip fields. Entry: current Remotion props and local registries. Exit: 4a stable `@banodoco/timeline-composition/theme-api` [PROPOSED] re-exports `effects.types`, `lib/animations`, `ThemeContext`; 4b one-time codemod [PROPOSED] rewrites `themes/<id>/effects/*/component.tsx` imports away from `../../../../tools/remotion/src/...`; 4c theme runtime packages `@banodoco/timeline-theme-<id>` [PROPOSED] publish as peer deps while theme data stays in `banodoco-workspace`. Shippable: Banodoco still renders locally; Reigh can opt in per theme. Rollback: restore local Remotion project and generated registry. Constraints: no Reigh worker rewrite.

### Phase 5 - Banodoco Pipeline Retargeting

Repos: `banodoco-workspace`. Order: after shared composition exists. Entry: `cut.py:476` builds timelines and pure-generative clips use `clipType` at `cut.py:554`; render shells out at `render_remotion.py:314-324`. Exit: `cut.py` imports generated schema types, emits canonical output through `materialize_output()` [PROPOSED], and `render_remotion.py` bundles `TimelineComposition` [PROPOSED] while preserving the Range HTTP server at `render_remotion.py:295`. Shippable: CLI run dirs and local render keep working. Rollback: emit legacy timeline and render with `tools/remotion`. Constraints: no Reigh dependency enters the CLI render path.

### Phase 6 - Publish-to-Reigh CLI + `timeline-import`

Repos: `banodoco-workspace`, `reigh-workspace`. Order: after Banodoco emits canonical timelines. Entry: Phase 5 output plus Reigh versioned RPCs. Exit: `tools/pipeline.py publish` [PROPOSED] uploads assets under `<user_id>/<timeline_id>/...`, calls `timeline-import` [PROPOSED], validates with shared Zod, and writes through `update_timeline_config_versioned` / `update_timeline_versioned` with `p_expected_version`. Shippable: one-way CLI handoff works without render-task submission. Rollback: undeploy edge function and remove CLI subcommand. Constraints: Reigh web stack is not required for local render; Reigh DB path remains versioned.

Phase 6 detail: CLI surface is `tools/pipeline.py publish --project-id <PID> --timeline-id <TID> [--expected-version <N>] [--create-if-missing] [--force] [--timeline-file <path>]` [PROPOSED]. The CLI reads `REIGH_USER_TOKEN`, restricted to a Supabase user JWT, not a PAT, because Storage RLS requires `auth.uid()` to match the first folder segment (`reigh-app/supabase/migrations/20260325090001_create_timeline_assets_bucket.sql:15-35`).

Asset handoff: decode the JWT to `user_id`; for each non-HTTP asset from the `{timeline, assets, theme}` props shape (`tools/render_remotion.py:307-310`), write a content-addressed key [PROPOSED] `<user_id>/<timeline_id>/<sha256(content)>.<ext>`. Idempotency is HEAD first: 200 means skip upload; otherwise call `.upload(key, file, {upsert: false})` matching `reigh-app/src/tools/video-editor/data/SupabaseDataProvider.ts:253-260`; reject upsert true; treat 409/duplicate-object as success. Rewrite the in-memory asset registry to bucket keys and submit `{timeline, asset_registry}`. Pure-generative timelines skip upload.

Edge function `reigh-app/supabase/functions/timeline-import/` [PROPOSED] imports `authenticateRequest()` from `_shared/auth.ts:68-160` and ownership helpers from `_shared/auth.ts:163-228`; no bespoke JWT or PAT parser. It validates payloads with shared Zod and calls `update_timeline_config_versioned` or `update_timeline_versioned` with `p_expected_version`, matching `SupabaseDataProvider.ts:74-99`.

Concurrency: default fetches expected version through sibling `timeline-export` GET or `get_timeline_version` RPC [PROPOSED]; explicit `--expected-version` overrides; `--force` performs fetch-then-write inside the edge function; mismatches return 409. `--create-if-missing` requires project ownership and inserts the caller as owner. This is separate from render-task submission: Phase 6 ships without Phase 7 or Phase 8. Rollback is edge-function undeploy plus CLI subcommand removal.

### Phase 7 - Bidirectional Agent Handoff

Repos: `banodoco-workspace`, `reigh-workspace`. Order: after Phase 1, Phase 3, Phase 6, and either Phase 4 or a v1 media-backed-only constraint. Entry: Reigh agent can perform surgical edits; Banodoco can generate canonical JSON. Exit: Reigh adds one `delegateToBanodocoAgent` tool [PROPOSED] and Banodoco exposes `/agents/generate-timeline-segment` [PROPOSED]. Shippable: surgical edits remain Reigh-side; bulk generation can be disabled by removing the new tool. Rollback: unregister tool from `tool-schemas.ts`, `tool-calls.ts`, `loop.ts`, and `registry.ts`. Constraints: pre-Phase-4 returns are constrained to media-backed clips that current `TimelineRenderer.tsx:34-96` / `VisualClipSequence` can render.

Phase 7 detail: this phase exists because Reigh's `ai-timeline-agent` is a surgical editor today. Its real CRUD surface is snake_case handlers such as `add_media_clip`, `add_text_clip`, `set_clip_property`, and `move_clip` (`reigh-app/supabase/functions/ai-timeline-agent/tools/timeline.ts:731-760`), and the text command parser only recognizes numeric settable properties at `command-parser.ts:22`. Bulk generative authoring remains Banodoco's job: `tools/pipeline.py`, `tools/arrange.py`, `tools/cut.py`, and `tools/pool_merge.py` own brief-to-arrangement-to-cut construction.

Banodoco exposes `POST /agents/generate-timeline-segment` [PROPOSED] with body `{ project_id: string, timeline_id: string, intent: string, brief_inputs: {...}, theme_id: string, current_timeline?: TimelineConfig, scope: 'full'|'insert'|'replace_range' }`. `project_id` and `timeline_id` are required so the service can verify Reigh ownership via `verifyProjectOwnership(supabaseAdmin, projectId, userId, ...)` (`reigh-app/supabase/functions/_shared/auth.ts:189-228`). Response is `{ timeline: TimelineConfig }` or `{ patch: TimelinePatch }` [PROPOSED], validated in and out with shared Zod.

Reigh adds one tool file, `reigh-app/supabase/functions/ai-timeline-agent/tools/delegateToBanodocoAgent.ts` [PROPOSED]. `registry.ts` alone is insufficient: Phase 7 also updates `tool-schemas.ts:10-220` for the LLM function declaration, `tool-calls.ts:15-23` for `FALLBACK_TOOL_NAMES`, and `loop.ts:426-481` for `executeToolCall()` dispatch. The tool calls Banodoco, then applies the returned timeline or patch through `update_timeline_config_versioned` with `p_expected_version`, using the same conflict semantics as Phase 6.

Auth: Reigh forwards the user's JWT to Banodoco. Banodoco verifies it against `<reigh-project>.supabase.co/auth/v1/.well-known/jwks.json` [PROPOSED primary] or performs a service-role check-back to Reigh [PROPOSED fallback], then confirms project ownership before generating. No service-role-only fallback is allowed. Hosting recommendation: a small dedicated Railway/Fly service. Reject a Reigh-side Edge Function shim because it forces the Python pipeline into TS; reject an on-demand container because per-call cold start is wrong for chat.

Phase 7 is separate from Phase 6: endpoints differ, but schema, JWT model, and versioned write semantics match. Banodoco stays stateless with respect to Reigh DB. Streaming remains open: sync 200 with the full result is the v1 default; SSE is a later option.

Independent shippability is conditional. If Phase 4 has not landed, Phase 7 v1 returns only media-backed clips with `assetEntry`; otherwise Reigh's current path routes non-text clips through `TimelineRenderer.tsx:34-96` and `VisualClip.tsx:90-99`, where clips without `assetEntry` render null. The canonical 2rp timeline has pure-generative clips at `tools/runs/2rp-templated/briefs/2rp-templated/hype.timeline.json:15-153`, so full motion-graphic delegation unlocks after Phase 4.

Worked example: user chats in Reigh, "extend this hype reel by 15 seconds in the 2rp style." The agent selects `delegateToBanodocoAgent`, Banodoco runs arrange-to-cut and returns a `TimelinePatch` [PROPOSED] constrained to media-backed clips before Phase 4. Reigh applies it through `update_timeline_config_versioned`; `@remotion/player` re-renders from the changed `TimelineConfig`. No inspector UI is involved.

### Phase 8 - Optional Render-Task Handoff

Repos: `reigh-workspace`, `banodoco-workspace`. Order: last and optional because shared composition must not force worker migration. Entry: publish-to-Reigh is stable. Exit: CLI may submit render jobs to Reigh worker [PROPOSED], but server-side Remotion remains a later decision. Shippable: current ffmpeg+NumPy worker can continue stitching pre-rendered assets. Rollback: disable render submission endpoint. Constraints: local CLI render remains permanent; Phase 8 is not a prerequisite for any prior phase.

## Section 5 - Battle-Tested Decision Points

### 5a. Canonical Schema Location
Recommendation: use sibling published repo. Monorepo couples release cadence; submodule still punts TS/Python type sync.

### 5b. Edit-Ops Extraction
Recommendation: TS-first pure subset in `timeline-ops`; Reigh glue stays local; `registry.ts` preserves snake_case names. Python consumes generated contracts.

### 5c. Pure-Generative Clip Flow
Recommendation: post-Phase-4 Reigh renders motion graphics through shared `EFFECT_REGISTRY`. Pre-Phase-4 clips without `assetEntry` do not render, so Phase 7 v1 returns media-backed patches.

### 5d. Effect-vs-Schema Coupling
Recommendation: keep Phase 1 validation loose at `tools/timeline.py:785`; add registry-aware strictness after Phase 4 via `strict: bool` [PROPOSED].

### 5e. Worker Rewrite Scope
Recommendation: no worker rewrite. Reigh's ffmpeg+NumPy worker keeps pre-rendered assets; server-side Remotion remains optional Phase 8.

### 5f. Rollback Map
Recommendation: every phase has a single revert handle.
| Phase | Rollback |
| --- | --- |
| 1 | Re-pin local schema and validator. |
| 2 | Remove lifted fields from Reigh serializer and hide Theme chip. |
| 3 | Point agent registry back to local ops. |
| 4 | Render with old composition and theme-local imports. |
| 5 | Emit legacy Banodoco timeline and render via `tools/remotion`. |
| 6 | Undeploy `timeline-import` and remove `publish`. |
| 7 | Remove tool from `tool-schemas.ts`, `tool-calls.ts`, `loop.ts`, `registry.ts`. |
| 8 | Disable render submission endpoint. |

### 5g. Schema Reconciliation
Recommendation: output adopts Reigh's `{resolution, fps, file, background?, background_scale?}` shape. Banodoco derives fps from `theme.visual.canvas.fps` (`themes/2rp/theme.json:29-33`; `tools/remotion/src/Root.tsx:35-40`).

### 5h. Theme Portability
Recommendation: theme JSON and assets remain in Banodoco, while runtime components ship as `@banodoco/timeline-theme-<id>` [PROPOSED] peer packages depending on `@banodoco/timeline-composition/theme-api` [PROPOSED].

### 5i. Publish-to-Reigh Asset/Auth/Concurrency
Recommendation: use user-first bucket keys, HEAD-then-upload idempotency, `_shared/auth.ts` helpers, and user-JWT-only CLI auth. PAT upload is rejected because Storage RLS depends on `auth.uid()`.

### 5j. Editing Surface
Recommendation: AI-via-chat is the only edit path for `clipType`, `params`, `theme`, and `theme_overrides`. Use existing snake_case agent tools plus new snake_case mutations where needed; reject inspector forms, schema forms, and theme picker.

### 5k. Bidirectional Handoff Hosting
Recommendation: host Banodoco's agent service on Railway/Fly. Reject Edge Function rewrite because it ports Python to TS; reject on-demand containers.
