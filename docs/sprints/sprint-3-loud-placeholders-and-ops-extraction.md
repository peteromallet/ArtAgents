# Sprint 3 — Loud placeholders + ops extraction starts

**Phases covered:** Phase 2 complete + Phase 3 partial
**Repos touched:** `reigh-workspace`, `shared-repo` (`@banodoco/timeline-ops` scaffold)
**Estimated:** ~4 pw, 2 engineers
**Risk:** UI scope creep around the Theme chip; agent tool routing regression during ops extraction.
**Demoable milestone:** Reigh editor opens a themed timeline, shows the Theme chip, and renders unknown clipTypes as a labeled placeholder instead of a black void.

## Scope

Close the Phase 2 user-visible deliverables (loud placeholder + Theme chip) and start extracting `timeline-ops` from `reigh-app/supabase/functions/ai-timeline-agent/tools/{timeline,clips}.ts` into a shared package — without changing tool names visible to the LLM (SD-018).

### Deliverables

1. **Loud-placeholder dispatch in `TimelineRenderer.tsx`:** for any `clipType` that isn't `media` / `hold` / `text` / `effect-layer`, render a labeled frame:
   > `clipType '<id>' not yet supported by editor — Phase 4 will enable`
   This replaces the previously-silent fallthrough to `VisualClipSequence` that returned `null` at `VisualClip.tsx:90-94`. The placeholder is a sibling of SD-019's "theme not installed" placeholder; both are loud, never silent (SD-025).
2. **Read-only Theme chip:** small chip showing `Theme: <id>` with an expandable JSON view of the resolved theme. Data source: shared `resolveTheme(timeline, themeRegistry)` from `@banodoco/timeline-schema` (Sprint 1 deliverable). Falls back to `Theme: <id> (not installed)` when the corresponding `@banodoco/timeline-theme-<id>` peer-dep package isn't loaded. **No picker, no edit form** (SD-019).
3. **`@banodoco/timeline-ops` package scaffold** (sibling published repo): empty exports, CI wired, depends on `@banodoco/timeline-schema`. No ops moved yet.
4. **First batch of pure ops extracted** from `ai-timeline-agent/tools/{timeline,clips}.ts` into `@banodoco/timeline-ops`:
   - Surgical CRUD: `addClip`, `removeClip`, `moveClip`, `setClipProperty`, `setClipTime`, `setTimelineProperty`.
   - Excludes any op that touches Supabase / agent state directly. Glue (file uploads, generation calls, lora ops, etc.) stays Reigh-side.
5. **`reigh-app/supabase/functions/ai-timeline-agent/tools/registry.ts` re-exports** the moved ops with identical names — the LLM tool schema is byte-equivalent before and after.

### Exit criteria

1. A timeline with `clipType="section-hook"` and no theme component installed renders the loud placeholder, NOT a black void.
2. Theme chip displays correctly for each existing theme fixture; clicking expands the resolved-theme JSON.
3. Existing agent chat flows for `addClip` / `removeClip` / `moveClip` / `setClipProperty` work unchanged from the user's perspective.
4. `ai-timeline-agent` test suite passes with no regressions; tool schemas in `tool-schemas.ts:10-24` unchanged.

### Out of scope (deliberate)

- New agent ops (`set_params`, `set_theme`, `set_theme_overrides`) — Sprint 4.
- All ai-timeline-agent integration sites for new ops (registry.ts, tool-schemas.ts, tool-calls.ts, loop.ts) — Sprint 4.
- Real EFFECT_REGISTRY dispatch — Sprint 5.
- `@banodoco/timeline-theme-<id>` package publishing — Sprint 5.

## Settled decisions to inherit

- SD-018 (AI-via-chat is the only editing surface) — Theme chip is read-only; no edit form added.
- SD-019 (Theme chip is the sole permitted UI addition).
- SD-024 (clipType: string) + SD-025 (loud placeholders).
- SD-006a (`resolveTheme()` lives in `timeline-schema`, available to Theme chip without composition extraction).

## Risks

- **Theme chip scope creep.** Easy to add "since I'm here, why not a theme picker?" Reject anything beyond read-only display + JSON expansion. Theme switching happens via chat (SD-018).
- **Tool-name compatibility during extraction.** `registry.ts` registers ops by name; the LLM tool schema in `tool-schemas.ts:10-24` declares them. Any rename breaks chat. Use re-exports + identical names to keep the tool schema byte-equivalent. Snapshot-test the schema before and after extraction.
- **Pure-vs-glue boundary.** Some ops in `tools/timeline.ts` and `tools/clips.ts` look pure but reach into Supabase via closures. Audit each before moving; leave borderline ones in Reigh until Sprint 4.

## Sources / citations to verify

- `reigh-app/src/tools/video-editor/compositions/TimelineRenderer.tsx:35-96` (clipType dispatch — codex ground-truth corrected range).
- `reigh-app/src/tools/video-editor/compositions/VisualClip.tsx:90-94` (silent-null bug — load-bearing).
- `reigh-app/supabase/functions/ai-timeline-agent/registry.ts` (existing tool registry).
- `reigh-app/supabase/functions/ai-timeline-agent/tool-schemas.ts:10-24` (LLM-visible tool schema declarations).
- `reigh-app/supabase/functions/ai-timeline-agent/tools/timeline.ts` (existing surgical ops).
- `reigh-app/supabase/functions/ai-timeline-agent/tools/clips.ts` (existing surgical ops).
