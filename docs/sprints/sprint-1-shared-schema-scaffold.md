# Sprint 1 — Shared schema scaffold

**Phases covered:** Phase 1 (partial — schema scaffolding only)
**Repos touched:** new `shared-repo` (`@banodoco/timeline-schema`), `banodoco-workspace`
**Estimated:** ~4 pw, 2 engineers
**Risk:** highest unknown of the program — TS→JSON Schema→Python codegen fidelity. Schema drift here blocks every later sprint. Front-loaded for that reason.

## Scope

Stand up the shared `@banodoco/timeline-schema` package as the canonical contract for `TimelineConfig`, plus the cross-language sync pipeline. No Reigh changes yet; no composition extraction; no agent-side ops.

### Deliverables

1. **New sibling repo** published as `@banodoco/timeline-schema` (npm) and `banodoco-timeline-schema` (PyPI).
2. **Zod source of truth** for `TimelineConfig`, `TimelineClip`, `Theme`, `ThemeOverrides`, `TimelineOutput`, `AssetEntry`. Hand-ported from `tools/timeline.py:115-188` (canonical TypedDicts) and `reigh-app/src/tools/video-editor/types/index.ts:128-134` (canonical `TimelineOutput`).
3. **`TimelineOutput` shape adopted verbatim from Reigh:** `{resolution: string, fps: number, file: string, background?: string, background_scale?: number}` (see SD-009).
4. **`materialize_output()` helper** (Python, exported from `banodoco-timeline-schema`) that takes a Banodoco-side timeline and produces a canonical `output` block:
   - `output.resolution` ← `"{theme.visual.canvas.width}x{theme.visual.canvas.height}"`
   - `output.fps` ← `theme.visual.canvas.fps` (NOT `theme.pacing.fps` — see SD-009; verified at `themes/2rp/theme.json:29-33`)
   - `output.file` ← deterministic default (Q3 — recommend `"output.mp4"` constant for v1)
   - Carries `background` / `background_scale` through.
5. **`resolveTheme(timeline, themeRegistry)` and theme-merge helpers** in TS, exported from `@banodoco/timeline-schema` (NOT composition — SD-006a / FLAG-017 fix). TS port of `tools/timeline.py:622-670`.
6. **Codegen pipeline:** `zod-to-json-schema` → JSON Schema → `datamodel-code-generator` → Python `TypedDict`s. Output checked into both repos as a generated artifact + CI diff-gate that fails on stale generated files.
7. **Banodoco-side adapter:** `tools/timeline.py` imports `TimelineConfig` / `TimelineClip` from generated Python module; old hand-written `TypedDict`s deleted. `validate_timeline()` at `tools/timeline.py:785` shells through to the shared validator.

### Exit criteria

1. `from banodoco_timeline_schema import TimelineConfig` works in `tools/`.
2. CI gate: TS Zod source + emitted JSON Schema + generated Python types diff-clean on every PR.
3. One existing Banodoco timeline (e.g. `tools/runs/2rp-templated/briefs/2rp-templated/hype.timeline.json`) validates against the shared schema with `strict: false`.
4. `materialize_output(timeline, theme)` produces a Reigh-compatible `output` block from the 2rp theme; unit-tested.
5. Banodoco's local CLI render (`npx remotion render TimelineComposition`) still works end-to-end.

### Out of scope (deliberate)

- Reigh-side imports — Sprint 2.
- Composition extraction — Sprint 5.
- Strict validation flag — Sprint 5 (Phase 4 coupling, see SD-015).
- Asset upload, agent ops, render task — Sprints 6+.

## Settled decisions to inherit (architecture doc)

- SD-001..009 (schema source-of-truth, package location, plugin registry shape, theme-merge ownership, pure-generative clip contract, edit-ops split, worker scope, local CLI render contract, schema reconciliation with Reigh's `output` shape).
- SD-006a (`resolveTheme()` and theme-merge live in `timeline-schema`, not composition).
- SD-009 (`materialize_output()` sources `output.fps` from `theme.visual.canvas.fps`).
- SD-024 (`clipType` is a string at the schema level — `clipType` field is typed `string`, NOT a closed union; widening of Reigh's union happens Sprint 2).

## Risks

- **TS→Python codegen fidelity.** `datamodel-code-generator` may emit Python types that deviate from hand-written TypedDicts in subtle ways (Optional vs required, discriminated-union shape, `Literal` enums). Mitigation: write a smoke test that round-trips the existing 2rp hype timeline through TS → JSON → Python → re-serialize and asserts equality on the canonical fields.
- **`@banodoco/timeline-schema` versioning** before any consumer is on it. Pin to `0.0.x` and use tilde ranges; first stable cut at `0.1.0` after Sprint 5 lands.
- **CI complexity.** The diff-gate must run from both repos. Add it to `tools/` first, then add `reigh-app/` consumer in Sprint 2.

## Sources / citations to verify

- `tools/timeline.py:115-188` (TimelineClip / TimelineConfig / ThemeOverrides), `:570-585` (canonical fps source), `:622-670` (theme-merge), `:785` (validate_timeline).
- `tools/render_remotion.py:307-310` (props passed to Remotion).
- `tools/remotion/src/Root.tsx:35-40` (canvas.fps reaches Remotion metadata).
- `themes/2rp/theme.json:29-33` (visual.canvas.fps verified = 30; pacing has no fps).
- `reigh-app/src/tools/video-editor/types/index.ts:128-134` (TimelineOutput).
- `reigh-app/src/tools/video-editor/lib/config-utils.ts:9-15` (`output.resolution` parser).
- `reigh-app/src/tools/video-editor/lib/defaults.ts:24-35` (createDefaultTimelineConfig — corrected path; not `data/defaults.ts`).
- `reigh-app/src/tools/video-editor/compositions/TimelineRenderer.tsx:102-106` (`config.output.fps` consumer — corrected line range; codex ground-truth).
