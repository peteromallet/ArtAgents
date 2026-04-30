# Sprint 5 — Composition extraction + EFFECT_REGISTRY dispatch

**Phases covered:** Phase 4 complete (4a/b/c/d)
**Repos touched:** `shared-repo` (`@banodoco/timeline-composition`, `@banodoco/timeline-theme-<id>` peer-dep packages), `banodoco-workspace`, `reigh-workspace`
**Estimated:** ~5 pw allocated, **codex's own per-phase estimate is 7 pw** — schedule risk flagged.
**Risk:** Highest blast radius of the program. Remotion / browser bundling differences across the CLI and Reigh; theme peer-dep versioning. If 4d slips, Sprint 6's Phase 5+6 work cascades.
**Demoable milestone:** A saved `clipType="section-hook"` renders the actual themed frame in Reigh's `@remotion/player` preview, NOT the Sprint-3 placeholder.

## Scope

Lift `tools/remotion/src/HypeComposition.tsx` and friends into `@banodoco/timeline-composition`. Publish the first `@banodoco/timeline-theme-2rp` peer-dep package. Replace Reigh's hardcoded `TimelineRenderer.tsx` dispatch with EFFECT_REGISTRY-style clipType dispatch. Keep Banodoco's local CLI render path working at every step.

### Deliverables

1. **`@banodoco/timeline-composition` extracted from `tools/remotion/src/`:**
   - Composition id renamed `HypeComposition` → `TimelineComposition` (PROPOSED).
   - Props `{timeline, assets, theme}` (matches `tools/render_remotion.py:307-310`).
   - Plugin discovery via directory-as-plugin pattern (cite `tools/effects_catalog.py:139-155` — file is 228 lines; do NOT cite `:780-800` or `:785`).
   - Codegenned `registry.generated.ts` listing all known clipTypes from theme packages found in `node_modules/@banodoco/timeline-theme-*`.
   - Re-exports `theme-api` sub-path (already stable from Sprint 4 deliverable 6).
2. **First peer-dep theme package published:** `@banodoco/timeline-theme-2rp`. Contents: `themes/2rp/effects/*/` plus `theme.json`. Peer-depends on `@banodoco/timeline-composition/theme-api`. Tilde-pin policy.
3. **Banodoco CLI render path updated:** `tools/render_remotion.py:307-310` props unchanged. Bundle target updated to import `TimelineComposition` from `@banodoco/timeline-composition` instead of the in-tree path. Range HTTP server at `tools/render_remotion.py:295` preserved. **Local CLI render must work at every commit during this sprint** — gate every PR on `npx remotion render TimelineComposition` against the 2rp templated brief.
4. **Reigh `TimelineRenderer.tsx` dispatch replacement (Phase 4d):** replace the existing hardcoded switch at `:35-96` (`effect-layer` → null, `text` → TextClipSequence, fallthrough → VisualClipSequence) with EFFECT_REGISTRY-style dispatch mirroring `tools/remotion/src/HypeComposition.tsx:58-64`. The dispatch reads from the codegen `registry.generated.ts`. Sprint-3's loud placeholder remains as the fallback for clipTypes not present in the registry (theme package missing or unknown clipType).
5. **Strict validation enabled** (`strict: true`) in `tools/timeline.py:785` and the Reigh validator. From this sprint forward, unknown clipTypes that are NOT registered with a theme package fail validation cleanly. Sprint-3's placeholder still renders the loud message at runtime for graceful degradation when the package is installed but the renderer fails.

### Exit criteria

1. Reigh editor opens a 2rp templated brief and renders the section-hook clip correctly in `@remotion/player` — not as a placeholder.
2. Banodoco CLI render against the 2rp templated brief still produces the same MP4 it did before this sprint.
3. The 2rp peer-dep package can be installed in a fresh Reigh checkout (`npm install @banodoco/timeline-theme-2rp@~0.1.0`); editor preview works without local theme files in tree.
4. `arca-gidan` peer-dep package follows; identical install + preview test (gate before declaring sprint done).

### Out of scope (deliberate)

- Banodoco pipeline retargeting (cut.py imports etc.) — Sprint 6.
- Publish-to-Reigh CLI / `timeline-import` edge function — Sprint 6.
- Server-side render of themed timelines — Sprint 8.
- Bidirectional agent handoff — Sprint 7.

## Settled decisions to inherit

- SD-017 (Stable Theme Public API at `@banodoco/timeline-composition/theme-api`).
- SD-009 (theme content/data stays Banodoco-side; only runtime components externalize).
- SD-026 (Phase 4 explicitly replaces `TimelineRenderer.tsx` switch with EFFECT_REGISTRY dispatch).
- SD-015 (strict validation phasing — strict: true lands here).

## Risks (load-bearing for the schedule)

- **Phase 4 underestimate.** Codex sprint table allocates 5 pw to Phase 4 but per-phase estimate is 7 pw. The real cost is bundling: Remotion ships an opinionated webpack config; making it work inside Reigh's Vite app and the Banodoco standalone bundler simultaneously usually surfaces edge cases. Mitigate by getting the bundling smoke test working in Sprint 4 against the Sprint 4 scaffold, not first thing in Sprint 5.
- **Spillover.** If Phase 4d (renderer dispatch) doesn't land in Sprint 5, push to Sprint 6 first half. Then Phase 5 + Phase 6 split across Sprints 6 and 7. Phase 7 → Sprint 8, Phase 8 → Sprint 9. The 8-sprint window becomes a 9-sprint window. Surface this to the project owner the moment Sprint 5 day-7 standup shows 4d isn't on track.
- **Theme peer-dep versioning.** First major version of `@banodoco/timeline-composition/theme-api` is the contract every future theme package depends on. Any breaking change after this sprint requires major-version bumps across every theme package. Lock the API surface aggressively.

## Sources / citations to verify

- `tools/remotion/src/HypeComposition.tsx:1-80` and `:58-64` (existing dispatch — migration target).
- `tools/remotion/src/Root.tsx:35-40` (canvas.fps reaches Remotion metadata).
- `tools/render_remotion.py:277-324`, `:295` (Range HTTP server), `:307-310` (props).
- `tools/effects_catalog.py:139-155` (plugin discovery; file is 228 lines).
- `tools/timeline.py:785` (validate_timeline — strict toggle).
- `reigh-app/src/tools/video-editor/compositions/TimelineRenderer.tsx:35-96` (dispatch replacement target — codex ground-truth corrected range).
- `reigh-app/src/tools/video-editor/compositions/VisualClip.tsx:90-94` (silent-null fallback the placeholder still guards against).
- `themes/2rp/effects/section-hook/component.tsx` (first peer-dep package contents).
