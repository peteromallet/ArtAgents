# Sprint 9 — Per-Component Inventory

Phase 1 / Step 2 of `sprint-9-pack-portfolio-20260516-0040/plan_v5.md`. One row per executor / orchestrator /
element across all packs. Classification column is inherited from `portfolio.md` (the source of truth for
classification rationale).

Columns:
- **id** — qualified id (`<pack>.<slug>` or, for elements, the element manifest id).
- **kind** — `executor` | `orchestrator` | `element`.
- **manifest path** — relative to repo root.
- **runtime module** — taken from `command.argv` (if present) or `metadata.runtime_module`. `n/a` for elements.
- **owning pack** — top-level pack directory.
- **classification** — inherited from `portfolio.md` (`Core/primitive`, `Core/canonical-demo-internal`,
  `Core/candidate-to-extract`, or `Bundled installable` for non-builtin packs).
- **blocker flags** — non-empty when the migration sweep must touch this component (hardcoded paths in tests,
  module-string assertions, runner-level dispatch hardcoding, etc.). Flags are enumerated here only;
  remediation lives in plan Steps 6.12, 4.4, 6.8, 6.11.

## 1. `builtin` pack — executors

| id                              | kind     | manifest path                                              | runtime module                                                       | owning pack | classification                       | blocker flags |
|---------------------------------|----------|------------------------------------------------------------|----------------------------------------------------------------------|-------------|--------------------------------------|---------------|
| `builtin.transcribe`            | executor | `astrid/packs/builtin/transcribe/executor.yaml`            | `astrid.packs.builtin.executors.transcribe.run`                                | `builtin`   | Core / primitive                     | F-LONGTAIL    |
| `builtin.scenes`                | executor | `astrid/packs/builtin/scenes/executor.yaml`                | `astrid.packs.builtin.executors.scenes.run`                                    | `builtin`   | Core / primitive                     | F-LONGTAIL, F-SEINFELD-SUBPROC |
| `builtin.shots`                 | executor | `astrid/packs/builtin/shots/executor.yaml`                 | `astrid.packs.builtin.executors.shots.run`                                     | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.quality_zones`         | executor | `astrid/packs/builtin/quality_zones/executor.yaml`         | `astrid.packs.builtin.executors.quality_zones.run`                             | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.triage`                | executor | `astrid/packs/builtin/triage/executor.yaml`                | `astrid.packs.builtin.executors.triage.run`                                    | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.scene_describe`        | executor | `astrid/packs/builtin/scene_describe/executor.yaml`        | `astrid.packs.builtin.executors.scene_describe.run`                            | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.quote_scout`           | executor | `astrid/packs/builtin/quote_scout/executor.yaml`           | `astrid.packs.builtin.executors.quote_scout.run`                               | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.pool_build`            | executor | `astrid/packs/builtin/pool_build/executor.yaml`            | `astrid.packs.builtin.executors.pool_build.run`                                | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.pool_merge`            | executor | `astrid/packs/builtin/pool_merge/executor.yaml`            | `astrid.packs.builtin.executors.pool_merge.run`                                | `builtin`   | Core / canonical-demo-internal       |               |
| `builtin.arrange`               | executor | `astrid/packs/builtin/arrange/executor.yaml`               | `astrid.packs.builtin.executors.arrange.run`                                   | `builtin`   | Core / primitive                     | F-LONGTAIL, F-INTRA-BUILTIN (consumed by `human_notes`) |
| `builtin.cut`                   | executor | `astrid/packs/builtin/cut/executor.yaml`                   | `astrid.packs.builtin.executors.cut.run`                                       | `builtin`   | Core / canonical-demo-internal       |               |
| `builtin.refine`                | executor | `astrid/packs/builtin/refine/executor.yaml`                | `astrid.packs.builtin.executors.refine.run`                                    | `builtin`   | Core / canonical-demo-internal       | F-INTRA-BUILTIN (`refine/src/reviewers/audio_boundary.py:7` imports `from astrid.packs.builtin.executors.asset_cache import run as asset_cache`) |
| `builtin.render`                | executor | `astrid/packs/builtin/render/executor.yaml`                | `astrid.packs.builtin.executors.render.run`                                    | `builtin`   | Core / primitive                     | F-CANONICAL-CLI (`tests/test_canonical_cli.py:79`), F-REGISTRY-SCOPES (`tests/test_default_registry_scopes.py:62`), F-SKILLMD-356 (`SKILL.md:356`), F-INTRA-BUILTIN (consumed by `iteration_video`) |
| `builtin.editor_review`         | executor | `astrid/packs/builtin/editor_review/executor.yaml`         | `astrid.packs.builtin.executors.editor_review.run`                             | `builtin`   | Core / primitive                     | F-INTRA-BUILTIN (consumed by `human_notes`) |
| `builtin.validate`              | executor | `astrid/packs/builtin/validate/executor.yaml`              | `astrid.packs.builtin.executors.validate.run`                                  | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.asset_cache`           | executor | `astrid/packs/builtin/asset_cache/executor.yaml`           | `astrid.packs.builtin.executors.asset_cache.run` (declared in `command.argv`)  | `builtin`   | Core / primitive                     | F-PHASE8-ANCHOR (Step 16.4 parity anchor; subprocess invocation must remain green), F-INTRA-BUILTIN (consumed by `human_notes`, `thumbnail_maker`, `refine/src/reviewers/audio_boundary.py`) |
| `builtin.generate_image`        | executor | `astrid/packs/builtin/generate_image/executor.yaml`        | `astrid.packs.builtin.executors.generate_image.run`                            | `builtin`   | Core / primitive                     | F-INTRA-BUILTIN (8 sibling imports: `vary_grid`, `transcribe`, `visual_understand`, `audio_understand`, `logo_ideas`, `event_talks`, `animate_image`, `sprite_sheet`) |
| `builtin.audio_understand`      | executor | `astrid/packs/builtin/audio_understand/executor.yaml`      | `astrid.packs.builtin.executors.audio_understand.run`                          | `builtin`   | Core / primitive                     | F-INTRA-BUILTIN (imports `generate_image.run`) |
| `builtin.video_understand`      | executor | `astrid/packs/builtin/video_understand/executor.yaml`      | `astrid.packs.builtin.executors.video_understand.run`                          | `builtin`   | Core / primitive                     | F-SEINFELD-SUBPROC (`seinfeld/dataset_build/run.py`, `seinfeld/samples_collage/run.py`), F-LONGTAIL |
| `builtin.visual_understand`     | executor | `astrid/packs/builtin/visual_understand/executor.yaml`     | `astrid.packs.builtin.executors.visual_understand.run`                         | `builtin`   | Core / primitive                     | F-SEINFELD-SUBPROC, F-INTRA-BUILTIN (consumed by `foley_map`) |
| `builtin.understand`            | executor | `astrid/packs/builtin/understand/executor.yaml`            | `astrid.packs.builtin.executors.understand.run`                                | `builtin`   | Core / primitive                     | F-ITERATION-SUBPROC (`iteration/executors/prepare/run.py` invokes via subprocess) |
| `builtin.youtube_audio`         | executor | `astrid/packs/builtin/youtube_audio/executor.yaml`         | `astrid.packs.builtin.executors.youtube_audio.run`                             | `builtin`   | Core / primitive                     | F-SEINFELD-SUBPROC |
| `builtin.boundary_candidates`   | executor | `astrid/packs/builtin/boundary_candidates/executor.yaml`   | `astrid.packs.builtin.executors.boundary_candidates.run`                       | `builtin`   | Core / canonical-demo-internal       | F-LONGTAIL    |
| `builtin.inspect_cut`           | executor | `astrid/packs/builtin/inspect_cut/executor.yaml`           | `astrid.packs.builtin.executors.inspect_cut.run`                               | `builtin`   | Core / primitive                     | F-LONGTAIL    |
| `builtin.foley_review`          | executor | `astrid/packs/builtin/foley_review/executor.yaml`          | `astrid.packs.builtin.executors.foley_review.run`                              | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.spatial_audio_page`    | executor | `astrid/packs/builtin/spatial_audio_page/executor.yaml`    | `astrid.packs.builtin.executors.spatial_audio_page.run`                        | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.tile_video`            | executor | `astrid/packs/builtin/tile_video/executor.yaml`            | `astrid.packs.builtin.executors.tile_video.run`                                | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.sprite_sheet`          | executor | `astrid/packs/builtin/sprite_sheet/executor.yaml`          | `astrid.packs.builtin.executors.sprite_sheet.run`                              | `builtin`   | Core / candidate-to-extract          | F-INTRA-BUILTIN (imports `generate_image.run`); F-LONGTAIL |
| `builtin.html_canvas_effect`    | executor | `astrid/packs/builtin/html_canvas_effect/executor.yaml`    | `astrid.packs.builtin.executors.html_canvas_effect.run`                        | `builtin`   | Core / candidate-to-extract          | F-HTML-CANVAS (`tests/test_html_canvas_effect.py:11,19,92` import `from astrid.packs.builtin.executors.html_canvas_effect.run import main, scaffold`) |
| `builtin.human_notes`           | executor | `astrid/packs/builtin/human_notes/executor.yaml`           | `astrid.packs.builtin.executors.human_notes.run`                               | `builtin`   | Core / candidate-to-extract          | F-INTRA-BUILTIN (imports `arrange.run`, `asset_cache`, `editor_review.run`) |
| `builtin.human_review`          | executor | `astrid/packs/builtin/human_review/executor.yaml`          | `astrid.packs.builtin.executors.human_review.run`                              | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.publish`               | executor | `astrid/packs/builtin/publish/executor.yaml`               | `astrid.packs.builtin.executors.publish.run`                                   | `builtin`   | Core / primitive                     | F-LONGTAIL (`tests/test_publish.py`, `tests/test_pipeline_dispatch_aliases.py`); referenced from `astrid/pipeline.py` |
| `builtin.open_in_reigh`         | executor | `astrid/packs/builtin/open_in_reigh/executor.yaml`         | `astrid.packs.builtin.executors.open_in_reigh.run`                             | `builtin`   | Core / primitive                     | F-LONGTAIL (`tests/test_open_in_reigh.py`) |
| `builtin.reigh_data`            | executor | `astrid/packs/builtin/reigh_data/executor.yaml`            | `astrid.packs.builtin.executors.reigh_data.run`                                | `builtin`   | Core / primitive                     | Referenced from `astrid/pipeline.py` |

## 2. `builtin` pack — orchestrators

| id                              | kind         | manifest path                                                  | runtime module                                                     | owning pack | classification                       | blocker flags |
|---------------------------------|--------------|----------------------------------------------------------------|--------------------------------------------------------------------|-------------|--------------------------------------|---------------|
| `builtin.hype`                  | orchestrator | `astrid/packs/builtin/hype/orchestrator.yaml`                  | `astrid.packs.builtin.orchestrators.hype.run` (declared in `runtime.command.argv`) | `builtin`   | Core / canonical-demo-internal       | **F-KEYSTONE** (`astrid/core/executor/runner.py:39-42` hardcodes `from astrid.packs.builtin.orchestrators.hype import run as pipeline`); F-CANONICAL-CLI (`tests/test_canonical_cli.py:303,312`); F-SPRINT1-REGRESSION (`tests/test_sprint1_regression.py:501,519`); F-BRIEF-FRONTMATTER (`tests/test_brief_frontmatter.py:17-18,120-199` imports `from astrid.packs.builtin.orchestrators.hype import run as hype_run`); F-CORE-INIT-REEXPORT (`astrid/core/executor/__init__.py:32,75` re-exports `build_pipeline_context` from runner — to be deleted per Step 6.7) |
| `builtin.animate_image`         | orchestrator | `astrid/packs/builtin/animate_image/orchestrator.yaml`         | `astrid.packs.builtin.orchestrators.animate_image.run`                           | `builtin`   | Core / candidate-to-extract          | F-INTRA-BUILTIN (imports `generate_image.run`, `logo_ideas.run`) |
| `builtin.event_talks`           | orchestrator | `astrid/packs/builtin/event_talks/orchestrator.yaml`           | `astrid.packs.builtin.orchestrators.event_talks.run`                             | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.foley_map`             | orchestrator | `astrid/packs/builtin/foley_map/orchestrator.yaml`             | `astrid.packs.builtin.orchestrators.foley_map.run`                               | `builtin`   | Core / candidate-to-extract          |               |
| `builtin.iteration_video`       | orchestrator | `astrid/packs/builtin/iteration_video/orchestrator.yaml`       | `astrid.packs.builtin.orchestrators.iteration_video.run`                         | `builtin`   | Core / primitive                     | F-CROSS-PACK (`iteration_video/run.py:15-16` imports `from astrid.packs.iteration.assemble` and `.prepare` — must be rewritten in lockstep with the iteration migration per plan Step 3.4 / 6.9), F-INTRA-BUILTIN (`run.py:17` imports `from astrid.packs.builtin.executors.render import run as render_executor`) |
| `builtin.logo_ideas`            | orchestrator | `astrid/packs/builtin/logo_ideas/orchestrator.yaml`            | `astrid.packs.builtin.orchestrators.logo_ideas.run`                              | `builtin`   | Core / primitive                     | F-EXTERNAL-IMPORT (`external/fal_foley/run.py` imports `from astrid.packs.builtin.orchestrators.logo_ideas.run`), F-INTRA-BUILTIN (imports `generate_image.run`) |
| `builtin.thumbnail_maker`       | orchestrator | `astrid/packs/builtin/thumbnail_maker/orchestrator.yaml`       | `astrid.packs.builtin.orchestrators.thumbnail_maker.run`                         | `builtin`   | Core / candidate-to-extract          | F-INTRA-BUILTIN (imports `asset_cache`, `thumbnail_maker.plan_template`) |
| `builtin.vary_grid`             | orchestrator | `astrid/packs/builtin/vary_grid/orchestrator.yaml`             | `astrid.packs.builtin.orchestrators.vary_grid.run`                               | `builtin`   | Core / primitive                     | F-EXTERNAL-IMPORT (`external/fal_foley/run.py` imports `from astrid.packs.builtin.orchestrators.vary_grid.run`), F-INTRA-BUILTIN (imports `generate_image.run`, `logo_ideas.run`) |

## 3. `builtin` pack — elements

Elements live under `astrid/packs/builtin/elements/`; content root already declared correctly (`elements: elements`)
so they are untouched by Phase 2 Step 6. They are inventoried for completeness.

| id (manifest)                          | kind    | manifest path                                                                              | runtime module | owning pack | classification | blocker flags |
|----------------------------------------|---------|--------------------------------------------------------------------------------------------|----------------|-------------|----------------|---------------|
| `builtin.transitions.cross-fade`       | element | `astrid/packs/builtin/elements/transitions/cross-fade/element.yaml`                        | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.transitions.fade`             | element | `astrid/packs/builtin/elements/transitions/fade/element.yaml`                              | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.effects.text-card`            | element | `astrid/packs/builtin/elements/effects/text-card/element.yaml`                             | n/a            | `builtin`   | Core / primitive (asset) | `tests/test_text_card_render.py` references; F-LONGTAIL |
| `builtin.animations.fade-up`           | element | `astrid/packs/builtin/elements/animations/fade-up/element.yaml`                            | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.animations.fade`              | element | `astrid/packs/builtin/elements/animations/fade/element.yaml`                               | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.animations.slide-up`          | element | `astrid/packs/builtin/elements/animations/slide-up/element.yaml`                           | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.animations.scale-in`          | element | `astrid/packs/builtin/elements/animations/scale-in/element.yaml`                           | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.animations.type-on`           | element | `astrid/packs/builtin/elements/animations/type-on/element.yaml`                            | n/a            | `builtin`   | Core / primitive (asset) |               |
| `builtin.animations.slide-left`        | element | `astrid/packs/builtin/elements/animations/slide-left/element.yaml`                         | n/a            | `builtin`   | Core / primitive (asset) |               |

## 4. `iteration` pack

| id                       | kind     | manifest path                                                  | runtime module                                              | owning pack | classification         | blocker flags |
|--------------------------|----------|----------------------------------------------------------------|-------------------------------------------------------------|-------------|------------------------|---------------|
| `iteration.prepare`      | executor | `astrid/packs/iteration/executors/prepare/executor.yaml`       | `astrid.packs.iteration.executors.prepare.run`              | `iteration` | Bundled installable    | F-LONGTAIL (`tests/test_iteration_video*.py`); invokes `builtin.understand` via subprocess |
| `iteration.assemble`     | executor | `astrid/packs/iteration/executors/assemble/executor.yaml`      | `astrid.packs.iteration.executors.assemble.run`             | `iteration` | Bundled installable    | F-LONGTAIL |

## 5. `upload` pack

| id                | kind     | manifest path                                                  | runtime module                                              | owning pack | classification         | blocker flags |
|-------------------|----------|----------------------------------------------------------------|-------------------------------------------------------------|-------------|------------------------|---------------|
| `upload.youtube`  | executor | `astrid/packs/upload/executors/youtube/executor.yaml`          | `astrid.packs.upload.executors.youtube.run`                 | `upload`    | Bundled installable    | **F-RUNNER-UPLOAD-DRIFT**: `astrid/core/executor/runner.py:131-132` (id-based dispatch `if executor.id == "upload.youtube"`) and `runner.py:171` (helper imports `from astrid.packs.upload.youtube.src.social_publish import publish_youtube_video` — stale path, must be rewritten to `astrid.packs.upload.executors.youtube.src.social_publish` per Step 4.4). |

## 6. `external` pack

**State note (verified on this branch):** Phase 2 Step 5 has been **partially pre-landed**: `external/pack.yaml`
already declares `content.executors: executors`, the four leaf executors have been moved to
`external/executors/{fal_foley,moirae,runpod,vibecomfy}/`, the **runpod wrapper has been split** into four
sibling subdirectories under `external/executors/` with underscore-cased filenames preserving the 3-segment
dotted ids (`runpod_provision/`, `runpod_exec/`, `runpod_teardown/`, `runpod_session/`), and every
per-component manifest already declares `schema_version: 1`. The `vibecomfy` manifest **still uses the
multi-executor wrapper** `{"executors":[…]}` and must be split in the same shape as runpod (Step 5.2 residual
work). The legacy `runpod/executor.yaml` wrapper also still exists alongside the split siblings and should be
removed once the split is complete.

The eight logical executor manifests that result from the split are:

| id                                | kind     | manifest path (current on branch)                                                  | runtime module                                                      | owning pack | classification                          | blocker flags |
|-----------------------------------|----------|------------------------------------------------------------------------------------|---------------------------------------------------------------------|-------------|-----------------------------------------|---------------|
| `external.fal_foley`              | executor | `astrid/packs/external/executors/fal_foley/executor.yaml`                          | `astrid.packs.external.executors.fal_foley.run`                     | `external`  | Bundled installable (optional-candidate) | F-BUILTIN-IMPORT (run.py imports `astrid.packs.builtin.orchestrators.logo_ideas.run` and `astrid.packs.builtin.orchestrators.vary_grid.run`) |
| `external.moirae`                 | executor | `astrid/packs/external/executors/moirae/executor.yaml`                             | `astrid.packs.external.executors.moirae.run`                        | `external`  | Bundled installable (optional-candidate) | — |
| `external.runpod.provision`       | executor | `astrid/packs/external/executors/runpod_provision/executor.yaml`                   | `astrid.packs.external.executors.runpod.run` (subcommand `provision`) | `external` | Bundled installable (optional-candidate) | F-QID-REGEX (3-segment id; relies on Step 9.0 regex relaxation) |
| `external.runpod.exec`            | executor | `astrid/packs/external/executors/runpod_exec/executor.yaml`                        | `astrid.packs.external.executors.runpod.run` (subcommand `exec`)    | `external`  | Bundled installable (optional-candidate) | F-QID-REGEX |
| `external.runpod.teardown`        | executor | `astrid/packs/external/executors/runpod_teardown/executor.yaml`                    | `astrid.packs.external.executors.runpod.run` (subcommand `teardown`) | `external` | Bundled installable (optional-candidate) | F-QID-REGEX |
| `external.runpod.session`         | executor | `astrid/packs/external/executors/runpod_session/executor.yaml`                     | `astrid.packs.external.executors.runpod.run` (subcommand `session`) | `external`  | Bundled installable (optional-candidate) | F-QID-REGEX |
| `external.vibecomfy.run`          | executor | nested in `astrid/packs/external/executors/vibecomfy/executor.yaml` (still a `{"executors":[…]}` wrapper) | `astrid.packs.external.executors.vibecomfy.run` (subcommand `run`)  | `external`  | Bundled installable (optional-candidate) | F-WRAPPER-SPLIT (residual Step 5.2 work — wrapper still present); F-QID-REGEX |
| `external.vibecomfy.validate`     | executor | (same wrapper)                                                                     | `astrid.packs.external.executors.vibecomfy.run` (subcommand `validate`) | `external`  | Bundled installable (optional-candidate) | F-WRAPPER-SPLIT; F-QID-REGEX |

> The pre-existing `astrid/packs/external/executors/runpod/executor.yaml` (legacy wrapper) is still present
> alongside the four split-out sibling manifests. The cleanup (delete the wrapper once the split siblings
> resolve cleanly through `PackResolver`) is residual Step 5 work and is flagged here for the implementer.

## 7. `seinfeld` pack

Already structured (Sprint 8 proof). Sprint 9 Phase 4 closes the deferred gaps (Gaps 3, 4, 5, 7, 8). The single
collision file is `astrid/packs/seinfeld/orchestrators/lora_train/orchestrator.yaml`, which carries **both**
`runtime.type: command` and legacy `runtime.kind: command`.

| id                                  | kind         | manifest path                                                                  | runtime module                                                          | owning pack | classification         | blocker flags |
|-------------------------------------|--------------|--------------------------------------------------------------------------------|-------------------------------------------------------------------------|-------------|------------------------|---------------|
| `seinfeld.aitoolkit_stage`          | executor     | `astrid/packs/seinfeld/executors/aitoolkit_stage/executor.yaml`                | `astrid.packs.seinfeld.executors.aitoolkit_stage.run`                   | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN (manifest still has `kind: built_in` — Gap 7 rename in Step 8b.3) |
| `seinfeld.aitoolkit_train`          | executor     | `astrid/packs/seinfeld/executors/aitoolkit_train/executor.yaml`                | `astrid.packs.seinfeld.executors.aitoolkit_train.run`                   | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN |
| `seinfeld.lora_eval_grid`           | executor     | `astrid/packs/seinfeld/executors/lora_eval_grid/executor.yaml`                 | `astrid.packs.seinfeld.executors.lora_eval_grid.run`                    | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN |
| `seinfeld.lora_register`            | executor     | `astrid/packs/seinfeld/executors/lora_register/executor.yaml`                  | `astrid.packs.seinfeld.executors.lora_register.run`                     | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN |
| `seinfeld.repo_setup`               | executor     | `astrid/packs/seinfeld/executors/repo_setup/executor.yaml`                     | `astrid.packs.seinfeld.executors.repo_setup.run`                        | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN |
| `seinfeld.dataset_build`            | orchestrator | `astrid/packs/seinfeld/orchestrators/dataset_build/orchestrator.yaml`          | `astrid.packs.seinfeld.orchestrators.dataset_build.run`                 | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN; F-RUNTIME-KIND (carries legacy `runtime.kind: command`) |
| `seinfeld.lora_train`               | orchestrator | `astrid/packs/seinfeld/orchestrators/lora_train/orchestrator.yaml`             | `astrid.packs.seinfeld.orchestrators.lora_train.run`                    | `seinfeld`  | Bundled installable    | F-KIND-BUILTIN; **F-RUNTIME-KIND-COLLISION** (carries BOTH `runtime.type` and `runtime.kind` — must be resolved before Step 9.1 strict-additionalProperties flip) |

## 8. Blocker-flag legend (for migration sweep)

| flag                          | meaning                                                                                                                                          | plan step that resolves it |
|-------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| F-KEYSTONE                    | `astrid/core/executor/runner.py:39-42` hardcoded `from astrid.packs.builtin.orchestrators.hype import run as pipeline`.                                       | 6.8                       |
| F-CANONICAL-CLI               | `tests/test_canonical_cli.py:79,303,312` asserts module strings `astrid.packs.builtin.executors.render.run` / `astrid.packs.builtin.orchestrators.hype.run` in stdout.  | 6.12 named-sites          |
| F-REGISTRY-SCOPES             | `tests/test_default_registry_scopes.py:24,37-38,45,62,67-69` asserts path suffixes like `astrid/packs/builtin/<folder>`.                        | 6.12 named-sites          |
| F-SHIPPED-IDS                 | `tests/test_packs_shipped_ids.py:57-65` path-suffix assertions for external/iteration/upload.                                                    | 6.12                      |
| F-SPRINT1-REGRESSION          | `tests/test_sprint1_regression.py:501,519` string assertions on `astrid.packs.builtin.orchestrators.hype.run`.                                                | 6.12                      |
| F-BRIEF-FRONTMATTER           | `tests/test_brief_frontmatter.py:17-18,120-199` imports `from astrid.packs.builtin.orchestrators.hype import run as hype_run`.                                | 6.12                      |
| F-HTML-CANVAS                 | `tests/test_html_canvas_effect.py:11,19,92` imports `from astrid.packs.builtin.executors.html_canvas_effect.run import main, scaffold`.                   | 6.12                      |
| F-LONGTAIL                    | Test files that hardcode `astrid.packs.builtin.<slug>.run` strings (enumerated long-tail list in plan Step 6.12).                               | 6.12 named-sites + grep-gate |
| F-INTRA-BUILTIN               | Component imports from a sibling builtin component (absolute path). Must be rewritten to the new `executors/<slug>` form during Step 6.9.       | 6.9                       |
| F-CROSS-PACK                  | Component imports from another pack across pack boundaries (e.g. `iteration_video` imports `astrid.packs.iteration.*`).                          | 3.4 / 6.9 lockstep        |
| F-SEINFELD-SUBPROC            | `astrid/packs/seinfeld/orchestrators/dataset_build/run.py` (and `samples_collage/run.py`) invokes `astrid.packs.builtin.<slug>.run` via subprocess. | 6.12 grep-gate (subprocess strings are in `python3 -m …` argv lists; grep the widened pattern) |
| F-ITERATION-SUBPROC           | `astrid/packs/iteration/executors/prepare/run.py` invokes `astrid.packs.builtin.executors.understand.run` via subprocess.                                  | 6.12 grep-gate            |
| F-EXTERNAL-IMPORT             | `astrid/packs/external/fal_foley/run.py` imports from `astrid.packs.builtin.orchestrators.logo_ideas.run` and `astrid.packs.builtin.orchestrators.vary_grid.run`.            | 6.9                       |
| F-RUNNER-UPLOAD-DRIFT         | `astrid/core/executor/runner.py:171` imports `from astrid.packs.upload.youtube.src.social_publish import publish_youtube_video` — stale path.    | 4.4                       |
| F-SKILLMD-356                 | `SKILL.md:356` references `astrid/packs/builtin/render/run.py`.                                                                                  | 13.2                      |
| F-CORE-INIT-REEXPORT          | `astrid/core/executor/__init__.py:32,75` re-exports `build_pipeline_context` from runner. Must be removed when machinery moves to hype package. | 6.7                       |
| F-NO-SCHEMA-VERSION           | Per-component manifest under `external/` lacks `schema_version: 1`; v1 schema does not validate it today.                                        | 5.5                       |
| F-WRAPPER-SPLIT               | Manifest is inside a `{"executors":[…]}` multi-executor wrapper that does not fit the v1 single-executor schema.                                 | 5.2                       |
| F-QID-REGEX                   | Id is 3-segment dotted (e.g. `external.runpod.provision`) and would be rejected by the current `qualified_id` regex.                              | 9.0                       |
| F-KIND-BUILTIN                | Manifest still declares `kind: built_in`; Gap 7 rename to `kind: external`.                                                                      | 8b.3                      |
| F-RUNTIME-KIND                | Orchestrator manifest carries legacy `runtime.kind`. Must be removed in favour of `runtime.type` only.                                            | 8b.2                      |
| F-RUNTIME-KIND-COLLISION      | Orchestrator manifest carries BOTH `runtime.type` and `runtime.kind` (will be a strict-schema collision after Step 9.1).                          | 8b.2                      |
| F-PHASE8-ANCHOR               | Component is named in plan Step 16.4 as the Phase 8 subprocess parity anchor.                                                                    | 16.4                      |

## 9. Components that block migration (explicit summary)

Per Step 2.2, the components that **block migration** (i.e. cannot move without simultaneous edits at other
named sites) are:

1. **`builtin.hype`** — F-KEYSTONE (runner hardcode), F-BRIEF-FRONTMATTER (test imports), F-CORE-INIT-REEXPORT.
2. **`builtin.render`** — F-CANONICAL-CLI (stdout assertions), F-REGISTRY-SCOPES, F-SKILLMD-356, F-INTRA-BUILTIN (`iteration_video`).
3. **`builtin.html_canvas_effect`** — F-HTML-CANVAS (direct `from … import main, scaffold` import in a test).
4. **`builtin.generate_image`** — F-INTRA-BUILTIN with 8 sibling consumers; the largest fan-in inside `builtin/`.
5. **`builtin.iteration_video`** — F-CROSS-PACK (`astrid.packs.iteration.*` imports) plus F-INTRA-BUILTIN (`render`). Cross-pack rewrites must land with the iteration migration (already pre-landed in this branch), not deferred to Step 6.9.
6. **`builtin.understand` / `builtin.video_understand` / `builtin.visual_understand` / `builtin.youtube_audio` / `builtin.scenes`** — F-SEINFELD-SUBPROC / F-ITERATION-SUBPROC: their module paths appear as string arguments inside `python3 -m …` argv lists in other packs. Must be caught by the widened grep gate in Step 6.12.
7. **`upload.youtube`** — F-RUNNER-UPLOAD-DRIFT: `runner.py:171` import path is already stale vs the (pre-landed) `upload/executors/youtube/` layout. Must be rewritten in Step 4.4.
8. **`seinfeld.lora_train`** — F-RUNTIME-KIND-COLLISION: manifest carries both `runtime.type` and `runtime.kind`. Step 8b.2 must drop `kind` before Step 9.1's strict-additionalProperties flip lands.
9. **`external/executors/vibecomfy/executor.yaml`** — F-WRAPPER-SPLIT residual: the manifest is still a `{"executors":[…]}` wrapper carrying `external.vibecomfy.run` and `external.vibecomfy.validate`; the runpod split (already pre-landed) is the template for the remaining vibecomfy work.

(No `pipeline_step` assertions were found inside `tests/` — `pipeline_step` is referenced only in
`astrid/core/executor/runner.py` (3 sites) and `astrid/core/executor/cli.py` (1 site), all of which are
predicates rather than string assertions on a specific value. Those sites are part of the runtime dispatch
the Phase 4 architectural change replaces, not a test-side blocker.)
