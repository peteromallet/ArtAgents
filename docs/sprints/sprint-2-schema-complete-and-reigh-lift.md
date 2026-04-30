# Sprint 2 — Schema complete + Reigh schema lift starts

**Phases covered:** Phase 1 complete + Phase 2 partial
**Repos touched:** `shared-repo`, `banodoco-workspace`, `reigh-workspace`
**Estimated:** ~4 pw, 2 engineers
**Risk:** Reigh's serializer rejecting new fields in unexpected paths; backward compatibility with timelines saved before this sprint.

## Scope

Finish the schema package by getting Banodoco's full code path on the shared types behind a narrow adapter. Begin Reigh's schema lift: widen `ClipType` to `string`, add `theme` / `theme_overrides` / `generation_defaults` fields, ensure existing timelines still load and save without data loss. **No editor UI changes yet** — placeholder dispatch + Theme chip are Sprint 3.

### Deliverables

1. **Banodoco fully on shared schema:** `cut.py:476/554`, `pool_merge.py`, `arrange.py`, `pipeline.py` import canonical TypedDicts from `banodoco_timeline_schema`. The narrow adapter shim deleted; direct imports throughout.
2. **Reigh dependency on `@banodoco/timeline-schema`:**
   - `reigh-app/src/tools/video-editor/types/index.ts` re-exports the shared `TimelineConfig` / `TimelineClip` types instead of declaring them locally.
   - **Widen `ClipType`** at `types/index.ts:49` from the closed union `'media' | 'hold' | 'text' | 'effect-layer'` to `string` (registry-validated elsewhere). This is the load-bearing change that unblocks themed clipTypes (SD-024).
3. **Schema lift:** add the new fields to Reigh's persisted `TimelineConfig` shape:
   - `theme: string` (theme id)
   - `theme_overrides?: ThemeOverrides`
   - `generation_defaults?: GenerationDefaults`
   - On clips: `params?: Record<string, unknown>`, `hold?: number`, `pool_id?: string`, `clip_order?: number`, `asset?: string` (optional; pure-generative clips have no `asset`).
4. **Reigh serialize-validator update** (located via Step 1.14 of architecture doc): tolerate the new fields. Validator does NOT reject unknown `clipType` strings yet; that's enforced at render time once Sprint 5 ships strict validation. **DO NOT** add registry validation here — see SD-015.
5. **Backward compatibility test:** load each existing Reigh timeline fixture, save without modifications, assert byte-equivalent (or normalized-equivalent) output. No data loss on round-trip.
6. **`createDefaultTimelineConfig()` at `lib/defaults.ts:24-35`** updated to populate the new optional fields with safe defaults.

### Exit criteria

1. Existing Reigh timelines load, save, and re-load without errors or data loss.
2. Banodoco's pipeline emits a timeline that validates against the shared schema and is loadable by Reigh's `SupabaseDataProvider` (manual smoke test — full publish path is Sprint 6, but the shape compatibility lands here).
3. CI diff-gate (Sprint 1) green on both repos.
4. `materialize_output()` is invoked from `tools/cut.py` / `tools/pipeline.py` so all Banodoco-emitted timelines now carry the canonical `output` block.

### Out of scope (deliberate)

- Editor placeholder dispatch for unknown clipTypes — Sprint 3.
- Theme chip — Sprint 3.
- New agent ops (`set_params`, `set_theme`, `set_theme_overrides`) — Sprint 4.
- timeline-ops extraction — Sprint 4.

## Settled decisions to inherit

- SD-001..009 from Sprint 1 plus all Sprint 1 deliverables.
- SD-016 (Reigh serialize-validator update is part of Phase 2).
- SD-024 (`clipType` is a string at the schema level).
- SD-031 / SD-032 (brief authoring is agent-inline; Reigh-originated media references reuse `asset_registry`) — these don't change code yet but anchor the Sprint 7 design; honor them by NOT introducing a separate brief-storage table here.

## Risks

- **Closed allowlist in Reigh's validator may reject unknown fields silently.** The existing serialize validator (Step 1.14) needs an audit before extending. If it's a strip-unknowns serializer, the new fields will round-trip-drop silently — catch this in the backward-compat test by asserting field presence after round-trip.
- **`clipType: string` vs `clipType: ClipType` switch in dispatching code.** Widening the type ripples through every `switch (clipType)` in Reigh. Sprint 2's job is to widen the type; Sprint 3 ships the placeholder dispatch that handles unknown values gracefully. Between these sprints, Reigh's `TimelineRenderer.tsx:35-96` may render unknown clipTypes as silent `null` (the existing bug at `VisualClip.tsx:90-94`). Document this as a known gap closed in Sprint 3, NOT a regression.
- **Existing Reigh timelines without `theme` field.** `theme` becomes optional in the schema but the editor's defaults helper sets a sensible value (probably the current Reigh-default `media` rendering, treated as "no theme" / `theme: null` if no theme registry packages are installed).

## Sources / citations to verify

- `reigh-app/src/tools/video-editor/types/index.ts:49` (ClipType union — load-bearing widening target).
- `reigh-app/src/tools/video-editor/types/index.ts:128-134` (TimelineOutput).
- `reigh-app/src/tools/video-editor/lib/defaults.ts:24-35` (createDefaultTimelineConfig).
- `reigh-app/src/tools/video-editor/data/SupabaseDataProvider.ts:74-99` (versioned RPC — must accept new fields).
- `reigh-app/src/tools/video-editor/lib/config-utils.ts:9-15` (`output.resolution` parser).
- Reigh serialize validator (Step 1.14 of architecture doc).
