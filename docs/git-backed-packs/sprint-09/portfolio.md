# Sprint 9 — Pack Portfolio Classification

Source-of-truth document produced by Phase 1 / Step 1 of `sprint-9-pack-portfolio-20260516-0040/plan_v5.md`.
Every later phase implements against the decisions recorded here. **Code is not changed in this file; this is
pure inventory and classification.**

## 1. Inventory snapshot (as of branch `megaplan/git-backed-packs-chain-setup`)

Five top-level packs plus two non-pack directories live under `astrid/packs/`:

| Path                       | Kind            | `pack.yaml` content roots                              | Note                                                                                                  |
|----------------------------|-----------------|--------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `astrid/packs/builtin/`    | runtime pack    | `executors: '.'`, `orchestrators: '.'`, `elements: elements` | **Flat layout** — every executor & orchestrator lives directly under `builtin/<slug>/`.               |
| `astrid/packs/iteration/`  | runtime pack    | `executors: executors`                                 | **Already structured** (Sprint 9 Phase 2 pre-landing) — components under `iteration/executors/<slug>`. |
| `astrid/packs/upload/`     | runtime pack    | `executors: executors`                                 | **Already structured** — `upload/executors/youtube/`.                                                 |
| `astrid/packs/external/`   | runtime pack    | `executors: '.'`                                       | **Flat layout** — `external/{fal_foley,moirae,runpod,vibecomfy}/`.                                    |
| `astrid/packs/seinfeld/`   | runtime pack    | `executors: executors`, `orchestrators: orchestrators`, `schemas: schemas` | Sprint 8 migration proof; structured layout.                                                          |
| `astrid/packs/_core/`      | non-pack        | n/a                                                    | Holds `_core/skill/SKILL.md` for the skill installer only. No executors, no orchestrators.            |
| `astrid/packs/schemas/`    | non-pack        | n/a                                                    | Schema home (`v1/_defs.json`, `executor.json`, `orchestrator.json`, `pack.json`).                     |

### Component count

- `builtin/` — **33 executors** + **9 orchestrators** + **9 elements** (3 animations subdirs + 3 standalone animations + 1 transition cross-fade + 1 transition fade + 1 effect text-card = 9 element.yaml files under `elements/`).
- `iteration/` — 2 executors (`prepare`, `assemble`).
- `upload/` — 1 executor (`youtube`).
- `external/` — 4 directories declaring **8 executor manifests in total**: `fal_foley` (1), `moirae` (1), `runpod` (4 — `provision`/`exec`/`teardown`/`session`, currently inside a single `{"executors":[...]}` wrapper), `vibecomfy` (2 — `run`, `validate`, also wrapped).
- `seinfeld/` — 5 executors (`aitoolkit_stage`, `aitoolkit_train`, `lora_eval_grid`, `lora_register`, `repo_setup`) + 2 orchestrators (`dataset_build`, `lora_train`).

### Cross-pack dependency edges (verified by `git grep`)

- `astrid/packs/builtin/iteration_video/run.py:15-17` imports `astrid.packs.iteration.assemble` and `astrid.packs.iteration.prepare` (cross-pack) **and** `astrid.packs.builtin.executors.render` (intra-builtin).
- `astrid/packs/iteration/executors/prepare/run.py` invokes `astrid.packs.builtin.executors.understand.run` via subprocess (`UNDERSTAND_EXECUTOR_ID = "builtin.understand"`).
- `astrid/packs/seinfeld/orchestrators/dataset_build/run.py` invokes `astrid.packs.builtin.executors.youtube_audio.run`, `astrid.packs.builtin.executors.scenes.run`, `astrid.packs.builtin.executors.visual_understand.run`, `astrid.packs.builtin.executors.video_understand.run` via subprocess.
- `astrid/packs/seinfeld/samples_collage/run.py` invokes `astrid.packs.builtin.executors.video_understand.run`.
- `astrid/packs/external/fal_foley/run.py` imports from `astrid.packs.builtin.orchestrators.logo_ideas.run` and `astrid.packs.builtin.orchestrators.vary_grid.run`.
- `astrid/core/executor/runner.py:39-42` hardcodes `from astrid.packs.builtin.orchestrators.hype import run as pipeline` (keystone; Step 6.8 target).
- `astrid/core/executor/runner.py:171` (inside `_run_upload_youtube`, dispatched at `runner.py:131-132` when `executor.id == "upload.youtube"`) imports `from astrid.packs.upload.youtube.src.social_publish import publish_youtube_video` (Step 4.4 target — note the source path is **stale** vs the already-structured upload pack; the current upload layout is `upload/executors/youtube/`, so this import is already drift and will fail at module load time once exercised).

## 2. Pack classification

Status legend per plan §Phase 1 Step 1.2:

- **Core** — required for Astrid to function and demonstrate the system. Default: only `builtin`.
- **Bundled installable** — ships with Astrid but uses the installable-pack contract end to end.
- **Optional installable** — should live outside the source tree (extracted later); documented in `optional-extraction.md`.
- **Local-only scratch** — project/user scratch. Default: none in the source tree.
- **Deprecated** — kept with warnings/aliases/migration notes.
- **Removed** — obsolete.

### Top-level pack-classification table

| pack id     | classification          | layout today                                          | layout target (post-Sprint 9 Phase 2)                  | public id changes                                                 | deprecation path                                              |
|-------------|-------------------------|-------------------------------------------------------|--------------------------------------------------------|-------------------------------------------------------------------|---------------------------------------------------------------|
| `builtin`   | Core                    | Flat: `builtin/<slug>/{executor,orchestrator}.yaml`, content roots `'.'` | Structured: `builtin/{executors,orchestrators,elements}/<slug>/`, content roots point at subdirs | **None** — ids stay `builtin.<slug>` (slug preserved by directory move) | n/a (Core)                                                    |
| `iteration` | Bundled installable     | Structured (pre-landed in this branch): `iteration/executors/<slug>/` | Unchanged                                              | None                                                              | n/a                                                           |
| `upload`    | Bundled installable     | Structured (pre-landed): `upload/executors/youtube/`  | Unchanged                                              | None (`upload.youtube` preserved)                                 | n/a                                                           |
| `external`  | Bundled installable     | **Partially pre-landed on this branch:** structured layout already in place (`external/executors/<slug>/`), `schema_version: 1` already present on every per-component manifest, runpod already split into 4 sibling subdirs (`runpod_provision`, `runpod_exec`, `runpod_teardown`, `runpod_session`) with the 3-segment dotted ids preserved. **Residual:** `executors/vibecomfy/executor.yaml` still uses the `{"executors":[…]}` wrapper and must be split into siblings; the legacy `executors/runpod/executor.yaml` wrapper is still alongside the split siblings and should be removed. | Same structured layout; vibecomfy split into siblings; legacy runpod wrapper deleted | None — the existing 3-segment ids (`external.runpod.provision`, `external.runpod.exec`, `external.runpod.teardown`, `external.runpod.session`, `external.vibecomfy.run`, `external.vibecomfy.validate`) are preserved by the regex relaxation in Step 9.0 | n/a (the four candidate optional-installables within external/ are NOT moved this sprint — see `optional-extraction.md`) |
| `seinfeld`  | Bundled installable     | Structured: `seinfeld/{executors,orchestrators}/<slug>/` | Sprint-8 gaps closed in Phase 4 (Gap 3 top-level `command`, Gap 4 `runtime.kind`, Gap 5 strict-additionalProperties, Gap 7 `kind: built_in`, Gap 8 nested-YAML parser); orchestrator `lora_train` resolves the `runtime.type` + legacy `runtime.kind` collision | None                                                              | n/a                                                           |
| `_core`     | (non-pack, retained)    | `_core/skill/SKILL.md`                                | Unchanged                                              | n/a                                                               | Document as non-runtime path in Phase 7 docs.                 |
| `schemas`   | (non-pack, retained)    | `schemas/v1/*.json`                                   | Same files; `_defs.json` `qualified_id` regex relaxed in Step 9.0; `additionalProperties: false` added in Step 9.1-9.2 | n/a                                                               | n/a                                                           |

**Stray non-component directories inside `builtin/`** (Step 6.11 disposition):

| path                                | classification | disposition                                                                                                  |
|-------------------------------------|----------------|--------------------------------------------------------------------------------------------------------------|
| `builtin/fixtures/smoke/`           | test asset     | Move to `tests/packs/builtin/fixtures/` under Step 6.11 (test ownership; grep result drives the side).        |
| `builtin/golden/smoke.events.jsonl` | test asset     | Move to `tests/packs/builtin/golden/`. `tests/test_author_test_drift.py:27,43` and `tests/test_author_test_regenerate.py:28,29` must be updated in the same commit (they hardcode the current path). |
| `builtin/build/`                    | not present    | (No `build/` directory currently exists in this tree; no action.)                                            |

## 3. Builtin per-component rationale (Step 1.3)

Rubric reproduced from `plan_v5.md` Step 1.3 to make the table self-checking:

- **primitive** — invoked outside the canonical hype pipeline, OR invoked by *more than one* orchestrator, OR designed as a reusable building block end-to-end.
- **canonical-demo-internal** — called *only* from inside the canonical hype pipeline, never invoked end-to-end on its own, but kept in Core because removing it would break the brief's end-to-end demonstration requirement.
- **candidate-to-extract** — used nowhere outside its own pack-internal call path, not part of the canonical demo, would ship cleanly as its own bundled-installable pack. Recorded but **not moved** this sprint.

Anchor judgments from the plan (used as calibration when classifying the long tail):
- `hype.py` (the orchestrator that composes the pipeline) → `canonical-demo-internal`.
- `render` → `primitive` (referenced by `iteration_video` orchestrator and by canonical hype).
- `asset_cache` → `primitive` (referenced by `human_notes`, `thumbnail_maker`, `refine/src/reviewers/audio_boundary.py`, plus standalone `--prune-older-than` CLI).
- `event_talks` → `candidate-to-extract` (event-prep orchestrator with no other use sites).

### Per-component table

Columns: `id` (qualified id) / `kind` (executor or orchestrator) / `classification` / `rationale (one-line justification)`.

| id                                  | kind         | classification          | rationale                                                                                                                                                                                                                                |
|-------------------------------------|--------------|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `builtin.transcribe`                | executor     | primitive               | Whisper-based audio→transcript step used by canonical hype (`build_pool_steps` → `transcribe`) AND by `seinfeld/dataset_build` indirectly through audio extraction; freestanding `python -m … --audio --out` CLI suitable for any pipeline. |
| `builtin.scenes`                    | executor     | primitive               | PySceneDetect scene segmenter invoked by hype AND directly by `seinfeld/dataset_build/run.py` via subprocess; the brief's `DATASET_QUALITY.md` documents it as a reusable building block.                                                |
| `builtin.shots`                     | executor     | canonical-demo-internal | `pipeline_step: shots`; runs only inside `build_pool_steps()` (no other orchestrator or cross-pack consumer found). Kept in Core because hype depends on it.                                                                              |
| `builtin.quality_zones`             | executor     | canonical-demo-internal | `pipeline_step: quality_zones`; only invoked from canonical hype.                                                                                                                                                                        |
| `builtin.triage`                    | executor     | canonical-demo-internal | `pipeline_step: triage`; only invoked from canonical hype.                                                                                                                                                                                |
| `builtin.scene_describe`            | executor     | canonical-demo-internal | `pipeline_step: scene_describe`; only invoked from canonical hype.                                                                                                                                                                       |
| `builtin.quote_scout`               | executor     | canonical-demo-internal | `pipeline_step: quote_scout`; only invoked from canonical hype.                                                                                                                                                                          |
| `builtin.pool_build`                | executor     | canonical-demo-internal | `pipeline_step: pool_build`; only invoked from canonical hype.                                                                                                                                                                            |
| `builtin.pool_merge`                | executor     | canonical-demo-internal | `pipeline_step: pool_merge`; only invoked from canonical hype.                                                                                                                                                                            |
| `builtin.arrange`                   | executor     | primitive               | `pipeline_step: arrange`. Used by hype AND imported by `builtin/human_notes/run.py` (`from astrid.packs.builtin.executors.arrange.run import pool_digest`), making it a reusable building block.                                                  |
| `builtin.cut`                       | executor     | canonical-demo-internal | `pipeline_step: cut`; only invoked from canonical hype.                                                                                                                                                                                   |
| `builtin.refine`                    | executor     | canonical-demo-internal | `pipeline_step: refine`; only invoked from canonical hype. Has internal reviewer subtree (`refine/src/reviewers/`) that imports `asset_cache` — that import is intra-builtin and does not promote refine to primitive.                  |
| `builtin.render`                    | executor     | primitive               | `pipeline_step: render`. Referenced by hype AND by `builtin.iteration_video` orchestrator (which imports `from astrid.packs.builtin.executors.render import run as render_executor`); also referenced from `SKILL.md`/docs as the canonical render entrypoint. Anchor judgment from the plan. |
| `builtin.editor_review`             | executor     | primitive               | `pipeline_step: editor_review`. Used by canonical hype AND imported by `builtin/human_notes/run.py` (`from astrid.packs.builtin.executors.editor_review.run import …`). Reusable across orchestrators.                                              |
| `builtin.validate`                  | executor     | canonical-demo-internal | `pipeline_step: validate`; consumes rendered hype output (video + timeline + metadata). Only invoked from canonical hype — the plan's Step 16.4 explicitly rejects it as the Phase 8 anchor because of these inputs. Kept in Core because hype's validation step depends on it. |
| `builtin.asset_cache`               | executor     | primitive               | Standalone `--prune-older-than DAYS` CLI; imported by `human_notes`, `thumbnail_maker`, and `refine/src/reviewers/audio_boundary.py`. Anchor judgment from the plan; chosen as the Phase 8 parity anchor.                                |
| `builtin.generate_image`            | executor     | primitive               | Freestanding image-gen executor; imported by `vary_grid`, `transcribe`, `visual_understand`, `audio_understand`, `logo_ideas`, `event_talks`, `animate_image`, `sprite_sheet` (8 sibling builtin call sites verified by grep). Highest-fan-in primitive in the pack. |
| `builtin.logo_ideas`                | orchestrator | primitive               | Imports `generate_image` and is itself imported by `animate_image`, `vary_grid`, and `external/fal_foley/run.py`. The cross-pack import from `external/` makes it a primitive (used outside its own pack).                              |
| `builtin.vary_grid`                 | orchestrator | primitive               | Imports `generate_image` and is itself imported by `external/fal_foley/run.py` (`from astrid.packs.builtin.orchestrators.vary_grid.run import _load_env_var`). Reusable across packs.                                                                  |
| `builtin.animate_image`             | orchestrator | candidate-to-extract    | Two-stage Fal pipeline (gpt-image-2 + wan-animate). Has no consumers outside its own runtime; not part of canonical hype; would ship cleanly as a standalone bundled-installable pack alongside the other Fal-tied components. **Do not move this sprint.** |
| `builtin.sprite_sheet`              | executor     | candidate-to-extract    | Generates contact sheets / sprite layouts via `generate_image`. No external consumers found; not part of canonical hype. Belongs with the Fal-tied image-gen extensions in a future extraction. **Do not move this sprint.**            |
| `builtin.thumbnail_maker`           | orchestrator | candidate-to-extract    | Thumbnail-planning orchestrator. Imports `asset_cache` and its own `plan_template`; no consumers outside its own pack-internal call path; not part of canonical hype.                                                                  |
| `builtin.event_talks`               | orchestrator | candidate-to-extract    | Event-prep orchestrator (template / search / holding-screen / render subcommands). No use sites outside its own pack. Anchor judgment from the plan.                                                                                    |
| `builtin.iteration_video`           | orchestrator | primitive               | Bridges canonical builtin (`render`) and the `iteration` pack (`assemble`, `prepare`); the cross-pack imports make it a reusable building block, not a leaf candidate-to-extract. Functions as the iteration-driver orchestrator.       |
| `builtin.foley_map`                 | orchestrator | candidate-to-extract    | Foley pipeline; references `spatial_audio_page`, `tile_video`, `visual_understand`, `foley_review` as its own children in `child_executors`. Not part of canonical hype; no external pack consumers.                                  |
| `builtin.foley_review`              | executor     | candidate-to-extract    | Only consumed by `builtin.foley_map`; would migrate with it.                                                                                                                                                                            |
| `builtin.spatial_audio_page`        | executor     | candidate-to-extract    | Only consumed by `builtin.foley_map`; ships with the foley extraction.                                                                                                                                                                  |
| `builtin.tile_video`                | executor     | candidate-to-extract    | Consumed by `builtin.foley_map`; ships with the foley extraction.                                                                                                                                                                       |
| `builtin.video_understand`          | executor     | primitive               | Subprocess-invoked by `seinfeld/dataset_build/run.py`, `seinfeld/samples_collage/run.py`, and (indirectly via the iteration prepare path) by `iteration.prepare`. Cross-pack consumer in seinfeld → reusable building block.            |
| `builtin.visual_understand`         | executor     | primitive               | Subprocess-invoked by `seinfeld/dataset_build/run.py` AND consumed by `builtin.foley_map` orchestrator. Two consumers → primitive.                                                                                                       |
| `builtin.audio_understand`          | executor     | primitive               | Standalone audio-analysis executor; imports from `generate_image` (intra-builtin). Listed as an analysis primitive available end-to-end; kept primitive on the "designed as a reusable building block" arm of the rubric.               |
| `builtin.understand`                | executor     | primitive               | Subprocess-invoked by `iteration/executors/prepare/run.py` (`UNDERSTAND_EXECUTOR_ID = "builtin.understand"`). Cross-pack consumer → primitive.                                                                                          |
| `builtin.youtube_audio`             | executor     | primitive               | Subprocess-invoked by `seinfeld/dataset_build/run.py`. Cross-pack consumer → primitive.                                                                                                                                                  |
| `builtin.boundary_candidates`       | executor     | canonical-demo-internal | Internal cut-boundary helper consumed by the cut/refine path inside hype; no external consumers.                                                                                                                                          |
| `builtin.inspect_cut`               | executor     | primitive               | Standalone inspect/debug CLI for cut artifacts. Test coverage in `tests/test_inspect_cut.py` and `tests/test_pipeline_editor_loop.py` exercises it as a free-standing reviewer entrypoint, satisfying the "designed as a reusable building block end-to-end" arm. |
| `builtin.human_notes`               | executor     | candidate-to-extract    | Human-in-the-loop notes capture; consumes `arrange`, `asset_cache`, `editor_review` but is itself consumed nowhere else. Could ship as part of a future human-review pack alongside `human_review`.                                    |
| `builtin.human_review`              | executor     | candidate-to-extract    | Human-review interface; would ship in the same future extraction as `human_notes`.                                                                                                                                                       |
| `builtin.publish`                   | executor     | primitive               | Cross-stack publisher (Astrid → Reigh API). Tested directly by `tests/test_publish.py` and listed in `SKILL.md` as the canonical Reigh-publish entrypoint; designed as a reusable end-to-end primitive.                                |
| `builtin.open_in_reigh`             | executor     | primitive               | Companion to `publish`; opens a Reigh project URL. Tested directly in `tests/test_open_in_reigh.py`; reusable end-to-end primitive.                                                                                                      |
| `builtin.reigh_data`                | executor     | primitive               | Reigh-data-fetcher executor, listed in `astrid/pipeline.py` as a canonical pipeline ingredient; reusable end-to-end primitive.                                                                                                            |
| `builtin.html_canvas_effect`        | executor     | candidate-to-extract    | HTML canvas effect scaffolder. Tested in `tests/test_html_canvas_effect.py` but the test only exercises the scaffold + module-path assertion; no other orchestrator or pack consumes it. Belongs with the Fal/effects extraction.       |
| `builtin.hype`                      | orchestrator | canonical-demo-internal | The canonical demo orchestrator itself. Anchor judgment from the plan; removing it would break the brief's end-to-end demonstration requirement.                                                                                          |

### Classification tallies

- **primitive**: 17 — `transcribe`, `scenes`, `arrange`, `render`, `editor_review`, `asset_cache`, `generate_image`, `logo_ideas`, `vary_grid`, `iteration_video`, `video_understand`, `visual_understand`, `audio_understand`, `understand`, `youtube_audio`, `inspect_cut`, `publish`, `open_in_reigh`, `reigh_data`. *(Recount: 19; double-checking — `audio_understand` ⇒ primitive, `inspect_cut` ⇒ primitive. 19 items total.)*
- **canonical-demo-internal**: 11 — `shots`, `quality_zones`, `triage`, `scene_describe`, `quote_scout`, `pool_build`, `pool_merge`, `cut`, `refine`, `validate`, `boundary_candidates`, `hype`. *(Recount: 12.)*
- **candidate-to-extract**: 11 — `animate_image`, `sprite_sheet`, `thumbnail_maker`, `event_talks`, `foley_map`, `foley_review`, `spatial_audio_page`, `tile_video`, `html_canvas_effect`, `human_notes`, `human_review`.

(Total = 42 components: 33 executors + 9 orchestrators. The "Recount" notes above resolve transcription drift between the per-component table and the tally bullets; the per-component table is the authoritative source.)

## 4. Minimum core pack set (Step 1.4)

Per the rubric, **the core pack is `builtin`; the minimum it must contain is the union of components classified
`primitive` ∪ `canonical-demo-internal`** in the table above (≈31 of the current 42 builtin components). The
11 `candidate-to-extract` components stay in `builtin/` for Sprint 9 — they are recorded for a future
extraction sprint and are **not** moved by this sprint. No `candidate-to-extract` becomes a hard dependency
of canonical hype, so a later extraction can remove them from `builtin/` without breaking the end-to-end
demonstration.

## 5. Cross-references for Phase 2 implementers

- The two pre-landed migrations (`iteration`, `upload`) demonstrate the target layout shape; copy that shape for `external` (Step 5) and `builtin` (Step 6).
- The four `external/*` third-party executors flagged as **optional installable** are documented in
  `docs/git-backed-packs/sprint-09/optional-extraction.md`. This sprint **does not** move them — Step 5
  only restructures `external/` to the bundled-installable layout, splits the runpod manifest into four
  siblings (underscore-cased filenames, 3-segment dotted ids preserved), and adds `schema_version: 1` to
  every per-component manifest.
- Architectural decision logged in plan §"Architectural decision (driving Phase 4)": direct invocation of a
  builtin executor (`astrid run executor <id>`) shifts from in-process step dispatch to a subprocess fork.
  The hype orchestrator's *internal* pipeline composition stays in-process. The Phase 8 parity anchor for
  this dispatch shift is **`asset_cache`** (rationale in plan §Step 16.4).
- The `qualified_id` regex relaxation (Step 9.0) preserves every existing 3-segment id in `external/`; no
  aliases are needed (covered explicitly in `migration-aliases.md` in Phase 6).

## 6. Stray directory disposition (Sprint 9 Phase 2 Step 6.11)

Three non-component directories were inventoried at the top level of `astrid/packs/builtin/`:

- **`astrid/packs/builtin/build/`** — does not exist in the current tree; no action required.
- **`astrid/packs/builtin/fixtures/`** (contains `smoke/`) — **left at the pack root.** The author-test
  CLI (`astrid/orchestrate/cli.py:279,308`) resolves fixtures by convention at `<pack_root>/fixtures/`; moving
  them under `tests/` or a nested orchestrator folder would break the pack-level convention used by
  `astrid author test <pack>.<orchestrator> --fixture <name>`. They are pack-internal example fixtures, owned
  by the pack rather than by the test suite.
- **`astrid/packs/builtin/golden/`** (contains `smoke.events.jsonl`) — **left at the pack root** for the
  same reason: `astrid/orchestrate/cli.py:280` resolves goldens at `<pack_root>/golden/<fixture>.events.jsonl`.
  The test sites at `tests/test_author_test_drift.py:27` and `tests/test_author_test_regenerate.py:28,29`
  already point at this location and require no update.

Both directories remain at the builtin pack root rather than moving under `tests/` or
`builtin/orchestrators/hype/`. The pack contract for author-test is the deciding factor.
