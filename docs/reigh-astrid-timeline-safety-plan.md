# Reigh Astrid Timeline Safety Plan

## Goals

Make the Reigh app <-> Astrid timeline boundary safe enough for active product work without turning it into a broad rewrite. The plan is about persisted JSON parity, lossy-round-trip prevention, and clear validation boundaries across:

- `../reigh-app`
- `/Users/peteromalley/Documents/reigh-workspace/Astrid`
- `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`

The practical goal is that a timeline saved by Reigh, inspected or transformed by Astrid, and loaded back by Reigh preserves the top-level contract fields that both sides know how to carry, even when one side cannot fully render every visual feature.

## Non-Goals

- Do not port the full Reigh renderer into Astrid.
- Do not force a default theme into every persisted Reigh timeline.
- Do not run a blanket migration over historical no-theme timelines.
- Do not invent a deep schema for `generation_defaults` before the product contract is settled.
- Do not add a new adapter layer unless direct shared-schema parity tests fail and prove one is needed.
- Do not make Astrid accept every timeline that Reigh can visually render; Astrid only needs to preserve the persisted shape and smoke-load renderable subsets.

## Owners

- **Shared persisted schema owner**: `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`
- **Reigh app owner**: `../reigh-app`, especially `src/tools/video-editor`
- **Astrid owner**: `/Users/peteromalley/Documents/reigh-workspace/Astrid`, especially `astrid/timeline.py`, generated Remotion types, and Remotion smoke checks

## Central Persisted-Timeline Contract

`/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema` is the persisted JSON contract. Its TypeScript Zod schema is the source shape for the shared package, and its emitted JSON Schema / Python generated types are the portable validation artifacts.

Applications may impose stricter runtime renderability rules at the edge where they actually render or resolve themes. That split is load-bearing:

- Persisted validation should answer: "Is this a timeline JSON payload that the ecosystem agrees may exist on disk or in storage?"
- Runtime renderability should answer: "Can this particular app resolve enough context to render this timeline now?"

This distinction lets Reigh keep no-theme default timelines while Astrid and theme resolvers continue to reject no-theme inputs at render time.

## Current Touch Points

- Shared schema currently defines `TimelineConfig` in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema/typescript/src/schemas.ts`. The present shape requires `theme` and allows `clips`, optional `tracks`, optional `pinnedShotGroups`, optional `theme_overrides`, and optional `output`.
- Reigh's editor type lives in `../reigh-app/src/tools/video-editor/types/index.ts`. It already models `theme`, `theme_overrides`, and `generation_defaults` as optional top-level fields.
- Reigh serialization lives in `../reigh-app/src/tools/video-editor/lib/serialize.ts`. Its top-level allowlist already includes `generation_defaults`, and `serializeForDisk` carries `theme`, `theme_overrides`, and `generation_defaults` when supplied.
- Reigh default timeline creation lives in `../reigh-app/src/tools/video-editor/lib/defaults.ts`. It intentionally omits `theme`, `theme_overrides`, and `generation_defaults` for newly created timelines.
- Astrid timeline validation and fallback shared types live in `astrid/timeline.py`. The file describes `banodoco_timeline_schema` as the canonical shape check, then adds Astrid-only validation such as effect registry checks.
- Astrid generated Remotion shape snapshots include `remotion/src/types.generated.ts` and `remotion/__smoke__/bundle.mjs`.

## Known Drift

- **`generation_defaults` drift**: Reigh treats `generation_defaults` as an optional top-level persisted field in `../reigh-app/src/tools/video-editor/types/index.ts` and preserves it in `../reigh-app/src/tools/video-editor/lib/serialize.ts`. The shared schema in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema/typescript/src/schemas.ts` does not currently include it, and Astrid top-level allowlists in `astrid/timeline.py` / generated Remotion allowlists do not include it.
- **`theme` optionality drift**: Reigh allows and creates persisted timelines without `theme` in `../reigh-app/src/tools/video-editor/types/index.ts` and `../reigh-app/src/tools/video-editor/lib/defaults.ts`. The shared schema currently requires `theme`, while Astrid `validate_timeline` requires `Timeline.theme` to be a non-empty slug for renderable timelines.
- **Renderer scope drift**: Reigh's renderer is broader than the Astrid local Remotion renderer. Astrid Remotion should be treated as a compatibility smoke renderer for loadability and contract preservation, not as a full visual parity target.

## Settled Decisions

- **SD-001** — Make the shared package the persisted JSON contract. _load_bearing: true_
  Rationale: The contract needs one neutral home that both Reigh and Astrid can validate against without inheriting either app's renderer assumptions.

- **SD-002** — Permit absent `theme` in persisted timelines. _load_bearing: true_
  Rationale: Reigh already creates no-theme defaults, and forcing a theme would change active storage semantics without solving render-time readiness.

- **SD-003** — Keep theme resolution strict. _load_bearing: true_
  Rationale: `resolveTheme` in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema/typescript/src/resolveTheme.ts`, `resolve_theme` in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema/python/banodoco_timeline_schema/theme.py`, and Astrid `resolve_timeline_theme` / `validate_timeline` should continue to reject absent or empty theme values when a renderable timeline is required.

- **SD-004** — Treat `generation_defaults` as optional open pass-through data for now. _load_bearing: true_
  Rationale: Reigh already persists it as `Record<string, unknown>`, but there is not yet a stable product-level schema for its inner keys.

- **SD-005** — Limit Astrid renderer scope to smoke/loadability parity. _load_bearing: true_
  Rationale: The safety goal is no lossy boundary behavior. Full visual parity with the Reigh renderer is a separate renderer project.

## Theme Policy

The settled policy is:

- Persisted schema permits `theme` to be absent.
- Persisted schema permits `theme_overrides` to be absent or present.
- Runtime theme resolution requires `theme` to be a non-empty slug.
- Astrid render validation may require a non-empty `theme` even though shared persisted validation allows no-theme timelines.

This means a no-theme timeline can be valid persisted JSON while still being non-renderable in a themed Astrid path. That is intentional.

## Renderer Scope

Astrid local Remotion checks should prove that timelines using the supported subset can be loaded, typed, smoke-rendered, and round-tripped without dropping contract fields. They should not be used as a claim that Astrid visually matches Reigh's renderer.

Success for the renderer boundary is smoke/loadability:

- Generated Astrid/Remotion allowlists know about the same persisted top-level fields.
- A themed fixture with `theme_overrides` and `generation_defaults` can pass through Astrid without losing those fields.
- No-theme persisted fixtures can validate at the shared-schema layer while still failing explicit Astrid renderability checks.

## Shared Schema Implementation

This is the first required implementation phase because every downstream check should inherit one persisted JSON contract instead of copying Reigh-specific or Astrid-specific assumptions.

Required changes in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`:

- Change `TimelineConfig.theme` in `typescript/src/schemas.ts` from required `z.string()` to optional `z.string().optional()`.
- Add optional top-level `generation_defaults` to `TimelineConfig`.
- Model `generation_defaults` as an open object, equivalent to Reigh's current `Record<string, unknown>` intent. A practical Zod shape is `z.record(z.unknown()).optional()`.
- Leave `theme_overrides` semantics unchanged.
- Leave clip-level `generation` semantics unchanged.

Do not deep-validate `generation_defaults` in this phase. The field is a top-level pass-through contract for pipeline-wide generation knobs. Until Reigh has a stable product schema for its inner keys, validation should only prove that the field is either absent or an object. Do not reject unknown inner keys such as model IDs, prompt settings, defaults by media type, or future provider-specific options.

Generated artifacts to refresh after the TypeScript schema change:

- `typescript/dist/timeline.schema.json` via the package build.
- `python/banodoco_timeline_schema/timeline.schema.json` via the schema emission / Python generation flow.
- `python/banodoco_timeline_schema/generated.py` via `npm run gen:python`.
- Any TypeScript declaration output produced by `npm run build`.

Use the package's documented commands from `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`:

```bash
npm run build
npm run gen:python
npm run check:codegen
```

Shared validation tests should cover three fixture classes:

- `timeline-no-theme-minimal`: `{ "clips": [] }` plus any required output/tracks shape if the current schema requires those elsewhere. This must pass persisted schema validation.
- `timeline-themed-with-extras`: a themed timeline containing `theme`, `theme_overrides`, and `generation_defaults` with at least two arbitrary inner keys. This must validate and preserve those keys through JSON Schema / Python validation.
- `timeline-legacy-no-extras`: an existing themed timeline with no `theme_overrides` and no `generation_defaults`. This must continue to validate unchanged.

The tests should exist at both schema-consumer layers where practical:

- TypeScript tests near `typescript/tests`, adding direct `TimelineConfig.parse` assertions or a small schema validation test if no such file exists yet.
- Python tests near `tests`, proving `validate_timeline(..., strict=False)` accepts the no-theme persisted fixture and the themed fixture with open `generation_defaults`.

Success criteria for this phase:

- The shared package accepts no-theme persisted timelines.
- The shared package accepts optional open `generation_defaults`.
- Existing themed timelines without the new field still pass.
- Generated JSON Schema and Python TypedDict artifacts match the TypeScript source.
- No resolver, renderer, or Astrid-specific renderability rule is weakened by the persisted-schema change.

## Strict Theme Resolution

After `TimelineConfig.theme` becomes optional in the persisted schema, theme resolution must remain a stricter render boundary. The executor should make the difference obvious in code and tests: schema validation accepts stored no-theme timelines; theme resolution rejects them.

Required TypeScript work in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`:

- Keep `resolveTheme` in `typescript/src/resolveTheme.ts` strict about `timeline.theme`.
- Because `TimelineConfigT["theme"]` will become optional, tighten the resolver-facing type so callers can see that `resolveTheme` requires render-resolvable input. Acceptable approaches include a small local type such as `Pick<TimelineConfigT, "theme" | "theme_overrides"> & { theme: string }`, or a named `ThemeResolvableTimeline` export if downstream TypeScript callers benefit from the explicit name.
- Preserve the runtime guard: absent, non-string, or empty `theme` values throw `Timeline.theme must be a non-empty slug`.
- Do not make `resolveTheme` choose a default theme, infer a theme from `theme_overrides`, or silently return an unmerged fallback theme.

Required Python work in `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`:

- Keep `resolve_theme` in `python/banodoco_timeline_schema/theme.py` strict about `timeline["theme"]`.
- Preserve the runtime guard: absent, non-string, or empty `theme` values raise `ValueError("Timeline.theme must be a non-empty slug")`.
- Do not add a Python-side default theme fallback.

Required tests:

- Add TypeScript resolver tests in `typescript/tests/resolveTheme.test.ts` proving `resolveTheme({} as any, registry)` rejects.
- Add TypeScript resolver tests proving `resolveTheme({ theme: "" }, registry)` rejects.
- Keep or refine the existing unknown-theme test so it proves a non-empty but missing registry slug still rejects separately from absent/empty theme.
- Add Python resolver tests near `tests/test_materialize_output.py` proving `resolve_theme({}, THEMES_ROOT)` rejects with `ValueError`.
- Add Python resolver tests proving `resolve_theme({"theme": ""}, THEMES_ROOT)` rejects with `ValueError`.
- Pair those resolver rejection tests with the shared validation tests from the previous section: the same no-theme persisted fixture should pass `validate_timeline(..., strict=False)` but fail `resolveTheme` / `resolve_theme`.

Success criteria for this phase:

- Readers cannot confuse persisted validation with render-resolvable input.
- TypeScript compile-time types nudge render callers toward providing `theme`.
- TypeScript and Python runtime tests prove no-theme and empty-theme inputs reject at resolver boundaries.
- No default-theme injection or migration behavior is introduced.

## Astrid Parity

Astrid should align with the shared persisted contract for field preservation while keeping its own renderability gate stricter. This phase is not about making every Reigh timeline render locally. It is about ensuring Astrid does not reject or drop top-level persisted fields that Reigh already writes.

Required changes in `/Users/peteromalley/Documents/reigh-workspace/Astrid`:

- Add `generation_defaults` to `_TIMELINE_TOP_ALLOWED` in `astrid/timeline.py`.
- Add `generation_defaults: dict[str, Any]` to the fallback `SharedTimelineConfig` `TypedDict` in `astrid/timeline.py`, so Astrid still carries the field when `banodoco_timeline_schema` is not importable or is temporarily stale in a local environment.
- Do not add inner-key validation for `generation_defaults`. Treat it as optional open pass-through data, matching the shared schema phase.
- Keep `_THEME_OVERRIDES_ALLOWED` unchanged.
- Keep clip-level `generation` validation separate from top-level `generation_defaults`; do not conflate the two.

Required validation behavior:

- `timeline.validate_timeline(config)` must continue to require `Timeline.theme` to be a non-empty slug for Astrid-renderable timelines.
- A no-theme persisted fixture may pass shared-schema validation, but it should still fail Astrid `validate_timeline` with `Timeline.theme must be a non-empty slug`.
- A themed fixture containing `theme`, `theme_overrides`, and `generation_defaults` should pass Astrid validation.
- Astrid should preserve `generation_defaults` losslessly when reading, validating, normalizing, or writing a themed timeline. Preservation means the exact JSON object survives; Astrid does not need to understand its inner keys.

Recommended Astrid tests:

- Extend `tests/test_schema_contract.py` so the parsed generated top-level allowlist and `timeline._TIMELINE_TOP_ALLOWED` include `generation_defaults`.
- Add a validation test for a themed timeline with `generation_defaults` containing arbitrary nested data, for example `{ "model": "sequence-v1", "image": { "quality": "high" } }`.
- Add a rejection test showing the same valid persisted no-theme fixture from the shared schema section still fails `timeline.validate_timeline(...)` in Astrid.
- Add or extend a round-trip-style test that serializes a themed timeline through the Astrid JSON path and asserts `generation_defaults` is byte-equivalent after reload.

Do not do these in this phase:

- Do not relax Astrid `validate_timeline` to allow no-theme render inputs.
- Do not resolve, merge, or interpret `generation_defaults` against theme generation blocks.
- Do not introduce a compatibility adapter that rewrites Reigh timelines before validation.
- Do not port Reigh renderer behavior to make more fixtures visually render in Astrid.

Success criteria for this phase:

- Astrid accepts and preserves `generation_defaults` on themed timelines.
- Astrid still rejects no-theme timelines at the renderability boundary.
- Astrid does not inspect or reject unknown inner `generation_defaults` keys.
- The section keeps the same persisted-vs-renderable contract split established by the shared schema and strict theme-resolution phases.

## Generated Remotion And Smoke Snapshot

After Astrid accepts `generation_defaults` in `astrid/timeline.py`, update the generated Remotion artifacts that mirror Astrid timeline types and allowlists. This phase is mechanical but important because stale generated files make the boundary look unsafe even after the Python source is correct.

Required generated updates:

- Regenerate `remotion/src/types.generated.ts` with `scripts/gen_remotion_types.py`.
- Confirm the generated `_TIMELINE_TOP_ALLOWED` export includes `generation_defaults`.
- Update the expected `_TIMELINE_TOP_ALLOWED` array in `remotion/__smoke__/bundle.mjs` to include `generation_defaults`.
- Keep the expected allowlist sorted the same way the generator emits it, so snapshot churn is limited to the new key.

Preferred command path from `/Users/peteromalley/Documents/reigh-workspace/Astrid`:

```bash
python3 scripts/gen_remotion_types.py
cd remotion
npm run typecheck
npm run smoke
```

The `remotion` package also exposes `npm run gen-types`, but that command runs both `../scripts/gen_remotion_types.py` and `../scripts/gen_effect_registry.py`. Use it only if the executor intentionally wants to refresh both generated surfaces. For this timeline-safety work, `python3 scripts/gen_remotion_types.py` is the narrow required command.

Generator stability check:

- Run `python3 scripts/gen_remotion_types.py` once after the Astrid source change.
- Inspect the diff and confirm it is limited to the expected `TimelineConfig` / `SharedTimelineConfig` field additions and `_TIMELINE_TOP_ALLOWED` updates.
- Run the generator a second time and confirm no additional diff appears.

Available smoke coverage:

- `npm run typecheck` in `remotion` should prove the generated TypeScript remains consumable by the local Remotion project.
- `npm run smoke` in `remotion` should prove the bundle imports the generated allowlists and that `remotion/__smoke__/bundle.mjs` expectations are current.
- If `npm run smoke` loads example timelines, keep those fixtures themed and within the local Astrid renderer subset. This is a loadability smoke check, not a visual parity assertion against Reigh.

Success criteria for this phase:

- `remotion/src/types.generated.ts` includes `generation_defaults` in the generated timeline config type surface and `_TIMELINE_TOP_ALLOWED`.
- `remotion/__smoke__/bundle.mjs` expects `generation_defaults` in `_TIMELINE_TOP_ALLOWED`.
- The generator is stable after one intentional update.
- Remotion typecheck and smoke coverage still pass or fail only for clearly unrelated pre-existing reasons that the executor records.

## Reigh Round Trip

Reigh already has most of the local plumbing for `theme`, `theme_overrides`, and `generation_defaults`. This phase is about proving those fields survive real Reigh caller flows, not adding broad transformation logic.

Required checks in `../reigh-app`:

- Keep `TimelineConfig` / `ResolvedTimelineConfig` in `src/tools/video-editor/types/index.ts` aligned with the shared contract: `theme`, `theme_overrides`, and `generation_defaults` stay optional top-level fields.
- Keep `serializeForDisk` in `src/tools/video-editor/lib/serialize.ts` preserving all three fields when they are present, including when `generation_defaults` contains arbitrary nested data.
- Keep no-theme defaults from `src/tools/video-editor/lib/defaults.ts` unchanged. A newly created default timeline should still omit `theme`, `theme_overrides`, and `generation_defaults`.
- Keep `validateSerializedConfig` focused on the Reigh persisted shape; do not add a rule that injects or requires `theme`.
- Keep timeline-data helpers in `src/tools/video-editor/lib/timeline-data.ts` carrying `theme`, `theme_overrides`, and `generation_defaults` through resolved-data construction and registry-derived data construction.

Focused serializer and data assertions:

- Extend `src/tools/video-editor/lib/serialize.test.ts` with a fixture equivalent to `timeline-themed-with-extras`, asserting `serializeForDisk(...)` emits exact `theme`, `theme_overrides`, and `generation_defaults` values.
- Include nested `generation_defaults`, not only a scalar key, for example `{ "model": "sequence-v1", "image": { "quality": "high", "provider": "reigh" } }`.
- Keep the existing no-theme serializer assertion: when the input has no `theme`, `theme_overrides`, or `generation_defaults`, the serialized result should not gain them.
- Extend `src/tools/video-editor/lib/timeline-data.test.ts` so `buildTimelineData`, `buildDataFromCurrentRegistry`, or the closest existing data helper proves those three fields survive config-to-data-to-serialized round trips.
- Assert absence separately from presence. The no-theme default case should prove Reigh still omits the fields; the themed-with-extras case should prove Reigh preserves them exactly.

At least one active caller-path assertion is required in addition to the low-level serializer and data tests. Pick the narrowest path that already has harness coverage:

- Preferred active save path: extend `src/tools/video-editor/hooks/useTimelinePersistence.test.tsx` so a save triggered through `useTimelinePersistence` calls `provider.saveTimeline(...)` with a config containing exact `theme`, `theme_overrides`, and `generation_defaults`.
- Acceptable active commit path: extend `src/tools/video-editor/hooks/useTimelineCommit.test.tsx` or `src/tools/video-editor/hooks/useTimelineSave.ts` coverage so `commitData(..., { save: true })` retains the three top-level fields until persistence receives the config.
- Acceptable history path: extend `src/tools/video-editor/hooks/useTimelineHistory.test.ts` so undo/redo or `jumpToCheckpoint` commits a checkpoint payload containing exact `theme`, `theme_overrides`, and `generation_defaults`.

The active-path test should fail if a future refactor preserves the fields in `serializeForDisk` but drops them before a real save, commit, or history caller reaches persistence. One active path is enough for this phase; do not create a large integration suite unless the narrow harness cannot observe the payload.

Recommended Reigh fixture names:

- `reighNoThemeDefaultTimeline`: a default timeline produced through the existing defaults helper, expected to omit `theme`, `theme_overrides`, and `generation_defaults`.
- `reighThemedTimelineWithGenerationDefaults`: a small timeline with `theme: "test-theme"`, a visible `theme_overrides` value such as `{ visual: { canvas: { fps: 24 } } }`, and nested `generation_defaults`.
- `reighLegacyThemedTimelineNoExtras`: a themed timeline without `theme_overrides` or `generation_defaults`, expected to preserve legacy behavior.

Do not do these in this phase:

- Do not force a default theme into Reigh default timelines.
- Do not add a blanket migration that backfills `theme` across historical timelines.
- Do not make Reigh save logic synthesize `theme_overrides` or `generation_defaults` when absent.
- Do not add a Reigh-specific adapter layer around the shared schema unless the focused assertions prove direct parity cannot work.

Success criteria for this phase:

- Reigh serializer tests prove present `theme`, `theme_overrides`, and `generation_defaults` survive exactly.
- Reigh data helper tests prove the same fields survive config/data reconstruction paths.
- At least one active save, commit, or history test proves a real caller flow carries the fields to the persistence-facing boundary.
- Reigh no-theme defaults remain unchanged, with no forced theme injection and no blanket migration.

## Recommended Fixtures

Use a small shared vocabulary for fixtures, even if each repo stores its own local copy. Centralizing fixtures can come later; do not block this safety work on a cross-repo fixture package.

- `timeline-no-theme-minimal`
  Assertion: validates as persisted JSON in `timeline-schema`; fails explicit theme resolution; fails Astrid render validation; remains omitted by Reigh defaults.

- `timeline-themed-with-extras`
  Shape: includes `theme`, `theme_overrides`, and nested `generation_defaults`, for example:

  ```json
  {
    "theme": "test-theme",
    "theme_overrides": {
      "visual": {
        "canvas": {
          "fps": 24
        }
      }
    },
    "generation_defaults": {
      "model": "sequence-v1",
      "image": {
        "quality": "high",
        "provider": "reigh"
      }
    },
    "clips": []
  }
  ```

  Assertion: validates in the shared schema, passes Astrid validation when otherwise renderable, survives Reigh serializer/data/active save or history flow, and preserves the exact `generation_defaults` JSON object.

- `timeline-legacy-no-extras`
  Assertion: existing themed timelines with no `theme_overrides` and no `generation_defaults` still validate and serialize unchanged.

- `astrid-themed-pass-through`
  Assertion: Astrid accepts a themed timeline with arbitrary nested `generation_defaults`, writes or reloads it without loss, and does not inspect inner keys.

- `reigh-active-save-with-extras`
  Assertion: the Reigh active save, commit, or history harness receives exact `theme`, `theme_overrides`, and `generation_defaults` at the persistence-facing boundary.

Keep fixture JSON intentionally small. Add clips only when a specific parser or renderer requires them. When a renderer smoke fixture needs assets or effects, keep that fixture separate from the pure persisted-contract fixtures so renderer limitations do not distort schema assertions.

## Risks And Mitigations

- **Risk: Persisted validation and renderability get conflated.**
  Mitigation: Pair every no-theme acceptance test with resolver/render rejection tests. The same fixture should pass shared persisted validation and fail `resolveTheme`, `resolve_theme`, and Astrid `validate_timeline`.

- **Risk: `generation_defaults` becomes over-specified too early.**
  Mitigation: Validate only that it is an optional object. Preserve unknown nested keys exactly. Do not add semantic checks until Reigh has a stable product contract for those keys.

- **Risk: Reigh low-level serializers pass while real save flows drop fields.**
  Mitigation: Require one active save, commit, or history assertion in Reigh in addition to serializer and data helper tests.

- **Risk: Generated Astrid Remotion artifacts drift from Python source.**
  Mitigation: Regenerate `remotion/src/types.generated.ts`, update `remotion/__smoke__/bundle.mjs`, and run the generator twice to prove stability.

- **Risk: Astrid renderer failures are mistaken for contract failures.**
  Mitigation: Keep renderer smoke fixtures themed and within the Astrid-supported subset. Treat broader Reigh renderer coverage as out of scope.

- **Risk: A forced theme migration changes live Reigh semantics.**
  Mitigation: Keep no-theme Reigh defaults unchanged and test absence explicitly. Any future migration should require a separate product decision and rollout plan.

Overzealous work to avoid:

- Do not build a full adapter layer before direct shared-schema parity tests prove one is needed.
- Do not port Reigh renderer behavior into Astrid for this plan.
- Do not create a deep `generation_defaults` schema.
- Do not normalize absent `theme` into a default value during serialization, save, or migration.
- Do not make a central fixture package a prerequisite for these focused tests.

## Execution Order

1. Update `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`.

   Checkpoint: `TimelineConfig.theme` is optional, `generation_defaults` is optional open pass-through data, generated artifacts are refreshed, and resolver tests still reject absent or empty theme values.

2. Update Astrid persisted-contract parity.

   Checkpoint: `astrid/timeline.py` accepts `generation_defaults` in top-level allowlists and fallback typed shape, preserves it on themed timelines, and still rejects no-theme render inputs.

3. Regenerate Astrid Remotion type and smoke snapshots.

   Checkpoint: `remotion/src/types.generated.ts` and `remotion/__smoke__/bundle.mjs` both include `generation_defaults`, and the generator is stable on a second run.

4. Update Reigh round-trip coverage in `../reigh-app`.

   Checkpoint: serializer, timeline-data, and at least one active save/commit/history test prove `theme`, `theme_overrides`, and `generation_defaults` survive real caller flows; no-theme defaults remain unchanged.

5. Run broader validation only after focused contract checks pass.

   Checkpoint: any remaining failures are either unrelated baseline failures or true contract regressions with a clear owner repo.

## Validation Order

Run the cheapest, most specific checks first. The exact package scripts may need small adjustment to match local repo tooling, but the order should stay fixed.

In `/Users/peteromalley/Documents/banodoco-workspace/packages/timeline-schema`:

```bash
npm run build
npm run gen:python
npm run check:codegen
```

Focused test targets:

- `typescript/tests/resolveTheme.test.ts`
- the new or existing TypeScript schema test that covers `timeline-no-theme-minimal`, `timeline-themed-with-extras`, and `timeline-legacy-no-extras`
- Python tests near `tests/test_materialize_output.py` for `resolve_theme` rejection and persisted validation acceptance

Then run the package's broader TypeScript/Python test commands if available.

In `/Users/peteromalley/Documents/reigh-workspace/Astrid`:

```bash
python3 scripts/gen_remotion_types.py
python3 scripts/gen_remotion_types.py
python3 -m pytest tests/test_schema_contract.py
cd remotion
npm run typecheck
npm run smoke
```

Focused checkpoints:

- `tests/test_schema_contract.py` proves top-level allowlists include `generation_defaults`.
- Astrid validation tests prove themed pass-through works and no-theme render validation still fails.
- The second generator run produces no additional diff.
- Remotion checks are smoke/loadability checks only.

In `../reigh-app`:

```bash
npm run test -- src/tools/video-editor/lib/serialize.test.ts
npm run test -- src/tools/video-editor/lib/timeline-data.test.ts
npm run test -- src/tools/video-editor/hooks/useTimelinePersistence.test.tsx
```

If the active assertion is implemented in a different narrow harness, substitute one of:

```bash
npm run test -- src/tools/video-editor/hooks/useTimelineCommit.test.tsx
npm run test -- src/tools/video-editor/hooks/useTimelineHistory.test.ts
```

Then run the relevant broader Reigh checks used by the repo, such as the video-editor test subset or full typecheck, after the targeted round-trip tests pass.

## Overall Success Criteria

- The shared schema is the persisted JSON contract, and it permits absent `theme` plus optional open `generation_defaults`.
- Theme resolution remains strict in TypeScript, Python, and Astrid renderability checks.
- Reigh preserves `theme`, `theme_overrides`, and `generation_defaults` through serializer, data helper, and at least one active caller path.
- Astrid accepts and preserves `generation_defaults` for themed timelines without interpreting its inner keys.
- Astrid generated Remotion types and smoke snapshots match the Python allowlists.
- No-theme Reigh defaults remain unchanged.
- The plan does not require visual parity between Reigh's renderer and Astrid Remotion.
- The only acceptable contract failures after implementation are documented baseline failures or newly discovered mismatches assigned to one of the three owner repos.

## Final Review Checklist

- The document lives at `docs/reigh-astrid-timeline-safety-plan.md`.
- The settled theme policy is unchanged: persisted timelines may omit `theme`; theme resolution and Astrid renderability still require a non-empty theme.
- Required work is scoped to schema parity, Astrid allowlist/generated parity, Reigh round-trip assertions, and focused validation.
- Overzealous work remains out of scope: no broad theme migration, no forced default theme injection, no deep `generation_defaults` schema, no adapter layer without failed direct parity tests, and no full Reigh renderer port.
- Astrid Remotion is described only as a compatibility smoke/loadability renderer.
- Validation order starts with focused contract tests before broader suites.
