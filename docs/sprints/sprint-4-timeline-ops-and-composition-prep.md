# Sprint 4 — Timeline-ops complete + composition prep

**Phases covered:** Phase 3 complete + Phase 4a/b start
**Repos touched:** `shared-repo` (`@banodoco/timeline-ops`, `@banodoco/timeline-composition` scaffold), `reigh-workspace`
**Estimated:** ~4 pw, 2 engineers
**Risk:** edge-function packaging of shared `timeline-ops`; keeping pure ops separate from Reigh glue.
**Demoable milestone:** Agent chat can mutate `clipType` / `params` / `theme` / `theme_overrides` via three new ops; `@banodoco/timeline-composition/theme-api` exists as a stable public sub-path.

## Scope

Finish `@banodoco/timeline-ops` extraction. Add the three new ops the schema lift requires (`set_params`, `set_theme`, `set_theme_overrides`), wired into all four ai-timeline-agent integration sites. Begin Phase 4 by stabilizing the `theme-api` public surface and writing the codemod that rewrites theme-component imports — no composition extraction yet.

### Deliverables

1. **`@banodoco/timeline-ops` complete:** all pure timeline ops moved out of `reigh-app/supabase/functions/ai-timeline-agent/tools/{timeline,clips}.ts`. `tools/registry.ts` re-exports the shared ops with unchanged names. Glue ops (`generation.ts`, `create-task.ts`, `duplicate-generation.ts`, `loras.ts`, `transform-image.ts`) stay Reigh-side.
2. **Three new agent ops** added to `@banodoco/timeline-ops` and registered Reigh-side:
   - `set_params(clipId, params)` — for editing themed-clip params (`kicker`, `title`, `subtitle`, etc.). Today `reigh-app/supabase/functions/ai-timeline-agent/tools/timeline.ts:731-760` exposes only `set_clip_property` for numeric media properties.
   - `set_theme(themeId)` — for switching the active theme on a timeline.
   - `set_theme_overrides(overridesPatch)` — for layering canvas/type/palette overrides without re-authoring the theme.
3. **Each new op lands at all four integration sites** (FLAG-016 / SD-026 four-site rule):
   - Tool implementation file in `reigh-app/supabase/functions/ai-timeline-agent/tools/`.
   - Registration in `reigh-app/supabase/functions/ai-timeline-agent/registry.ts`.
   - Schema declaration in `reigh-app/supabase/functions/ai-timeline-agent/tool-schemas.ts:10-24`.
   - Allowlist entry in `reigh-app/supabase/functions/ai-timeline-agent/tool-calls.ts:14-23`.
   - Execution branch in `reigh-app/supabase/functions/ai-timeline-agent/loop.ts:442-481`.
4. **`command-parser.ts` decision** at `reigh-app/supabase/functions/ai-timeline-agent/command-parser.ts:3-23` (corrected path; the parser is in the agent's edge function, not in `lib/`). The `SETTABLE_PROPERTIES` allowlist at `:22` is currently `volume|speed|opacity|x|y|width|height`. Decide:
   - Option A — widen to include `clipType`, `params`, `theme`, `theme_overrides`. Means the slash-command surface stays usable for themed editing.
   - Option B — leave it media-only, document that themed-field editing happens via the agent's natural-language tools (`set_params` etc.) NOT via `/property=value` syntax.
   Recommendation: **Option B** for v1 (matches SD-018 — chat is the editing surface; slash-commands stay for power-user media tweaks). Document the decision in the resulting code.
5. **`@banodoco/timeline-composition` package scaffold** (sibling published repo): empty exports, CI wired, depends on `@banodoco/timeline-schema`.
6. **Stable theme public API** at `@banodoco/timeline-composition/theme-api` — re-exports `effects.types`, `lib/animations`, `ThemeContext` from the existing Banodoco code (still in-tree at `tools/remotion/src/`). Theme components depend on this sub-path going forward; no relative `../../../../tools/remotion/src/...` imports.
7. **One-time codemod** that rewrites every `themes/<id>/effects/*/component.tsx` import off the old relative path onto `@banodoco/timeline-composition/theme-api`. Run the codemod against `themes/2rp/` and `themes/arca-gidan/`; commit the result. Codemod script lives in `tools/scripts/` for reuse.

### Exit criteria

1. Agent chat: "make the kicker say '2RP Spring' on the section-hook clip" successfully calls `set_params` and updates the timeline. Verify against an existing 2rp templated brief.
2. Agent chat: "switch this timeline to the arca-gidan theme" calls `set_theme`; resolved-theme JSON in the Theme chip updates.
3. All four integration sites for each new op are exercised by at least one test in the ai-timeline-agent test suite.
4. `@banodoco/timeline-composition/theme-api` is importable from a temporary test file; running the codemod against `themes/` produces zero relative-path imports remaining.
5. Reigh and Banodoco tests pass.

### Out of scope (deliberate)

- Composition extraction itself — Sprint 5.
- `@banodoco/timeline-theme-<id>` peer-dep package publishing — Sprint 5.
- `TimelineRenderer.tsx` dispatch replacement — Sprint 5 (Phase 4d).

## Settled decisions to inherit

- SD-018 (AI-via-chat is the only editing surface — drives the new-ops choice).
- SD-026 (four-site rule for new ai-timeline-agent tools).
- SD-031 / SD-032 / SD-033 (brief authoring inline; assets via existing registry; theme discoverability agent-driven).

## Risks

- **Edge-function packaging.** Reigh's `ai-timeline-agent` runs in Supabase Edge (Deno). `@banodoco/timeline-ops` must bundle cleanly under Deno's import-map / npm-shim system. Validate early — write the smallest possible new op, push through the full deploy, and only then do the bulk move.
- **Codemod scope.** `themes/2rp/` and `themes/arca-gidan/` are the only known themes. Verify no other paths import from `tools/remotion/src/` before publishing the codemod.
- **`set_theme` UX semantics.** Switching theme on a timeline with existing themed clips can leave clips referencing a `clipType` from the old theme that doesn't exist in the new theme. v1 behavior: warn in the agent's response; future enhancement could prompt the user to remap. Document but don't solve here.

## Sources / citations to verify

- `reigh-app/supabase/functions/ai-timeline-agent/tools/timeline.ts:731-760` (corrected path — current `set_clip_property`).
- `reigh-app/supabase/functions/ai-timeline-agent/registry.ts`, `tool-schemas.ts:10-24`, `tool-calls.ts:14-23`, `loop.ts:442-481` (four-site rule).
- `reigh-app/supabase/functions/ai-timeline-agent/command-parser.ts:3-23` (corrected path; SETTABLE_PROPERTIES at `:22`).
- `tools/remotion/src/` (existing theme-api source — to be re-exported via `@banodoco/timeline-composition/theme-api`).
- `themes/2rp/effects/section-hook/component.tsx` and similar — codemod targets.
