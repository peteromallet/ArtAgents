# Builtin Executor Argv Inventory

Generated for Sprint 9 Phase 4 Step 8a. Source of truth for the
`runtime.command.argv` value that every builtin executor manifest under
`astrid/packs/builtin/executors/<slug>/executor.yaml` must declare once Step 8a
lands. Wave 3 agents transcribe rows from this table into manifests; do not
re-derive argv ad hoc.

## Placeholder classes

`_placeholder_values` in `astrid/core/executor/runner.py:412+` builds the
substitution dict that resolves `{name}` tokens in `command.argv`. Tokens fall
into three classes:

- **Framework-provided** (no `inputs:` declaration needed):
  `{out}`, `{python_exec}`, `{brief}`, `{brief_slug}`, `{brief_out}`,
  `{brief_copy}`. Always populated by `_placeholder_values`.
- **Per-executor inputs** (must appear in the manifest's `inputs:`):
  e.g. `{audio}`, `{video}`, `{scenes}`, `{shots}`, `{prune_days}`. Populated
  from `request.values` at `runner.py:429-432`.
- **Per-executor outputs** (must appear in the manifest's `outputs:`):
  populated from `_output_value` at `runner.py:441-448`. Output `path_template`
  fields are themselves expanded against the placeholder dict, so e.g. a
  manifest with `outputs: [name: scenes_json, path_template: "{out}/scenes.json"]`
  resolves `{scenes_json}` to the absolute path.

### Conditional-argv exception

Several lambdas in `build_pool_steps()` append an optional flag only when an
input is truthy — most commonly `*(["--env-file", str(args.env_file)] if args.env_file else [])`.
`_placeholder_values` has no conditional argv mechanism: every `{name}` either
resolves or raises. Therefore optional flags are **dropped** from the manifest
`runtime.command.argv` in this inventory; the executor's argparse already
tolerates the flag's absence (the lambda branches on it precisely because the
flag is optional). The same rule applies to other gated tokens like
`--theme`, `--target-duration`, `--allow-generative-effects`, `--no-audio`,
`--primary-asset`, `--asset KEY=PATH`, `--shots`, and `--scenes`/`--transcript`
inside `build_pool_cut_cmd`. If a real run needs those flags, the dispatch
layer that calls the executor (the hype orchestrator, or a future
`orchestrator.command.args.with` block) supplies them via `request.values` and
they go through a different argv-shaping path — not the manifest's static
`argv` list.

## Module path

The builtin restructure (Wave 2) relocates every executor to
`astrid.packs.builtin.executors.<slug>.run`. All argv entries below use that
module path regardless of any transient on-disk state during the restructure.

## Inventory — pool-step executors (source: `astrid/packs/builtin/hype/run.py` `build_pool_steps()` at lines 653-926)

| Slug | Source line | Manifest argv | Required input placeholders | Notes |
|------|-------------|---------------|------------------------------|-------|
| transcribe | hype/run.py:655-670 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.transcribe.run", "--audio", "{audio}", "--out", "{out}"]` | `audio` | Optional `--env-file` dropped (conditional). |
| scenes | hype/run.py:671-679 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.scenes.run", "--video", "{video}", "--out", "{out}/scenes.json"]` | `video` | |
| quality_zones | hype/run.py:680-693 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.quality_zones.run", "{video}", "--out", "{out}/quality_zones.json"]` | `video` | Positional video (not a flag). |
| shots | hype/run.py:694-702 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.shots.run", "--video", "{video}", "--scenes", "{out}/scenes.json", "--out", "{out}"]` | `video` | `--scenes` is a path under `{out}` produced by the `scenes` executor; manifest may also declare an `inputs: scenes` or treat it as an upstream artifact under `{out}`. |
| triage | hype/run.py:703-722 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.triage.run", "--scenes", "{out}/scenes.json", "--shots", "{out}/shots.json", "--shots-dir", "{out}", "--out", "{out}"]` | (none beyond framework `{out}`) | Optional `--env-file` dropped. |
| scene_describe | hype/run.py:723-742 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.scene_describe.run", "--scenes", "{out}/scenes.json", "--triage", "{out}/scene_triage.json", "--video", "{video}", "--out", "{out}"]` | `video` | Optional `--env-file` dropped. |
| quote_scout | hype/run.py:743-758 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.quote_scout.run", "--transcript", "{out}/transcript.json", "--out", "{out}"]` | (none) | Optional `--env-file` dropped. |
| pool_build | hype/run.py:759-783 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.pool_build.run", "--triage", "{out}/scene_triage.json", "--scene-descriptions", "{out}/scene_descriptions.json", "--quote-candidates", "{out}/quote_candidates.json", "--transcript", "{out}/transcript.json", "--scenes", "{out}/scenes.json", "--source-slug", "{source_slug}", "--out", "{out}"]` | `source_slug` | |
| pool_merge | hype/run.py:784-801 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.pool_merge.run", "--pool", "{out}/pool.json", "--out", "{out}/pool.json"]` | (none) | Optional gated `--theme {theme}` dropped (conditional on `theme_explicit`). |
| arrange | hype/run.py:802-833 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.arrange.run", "--pool", "{out}/pool.json", "--brief", "{brief_copy}", "--out", "{brief_out}", "--source-slug", "{source_slug}", "--brief-slug", "{brief_slug}"]` | `source_slug` | All other flags (`--theme`, `--target-duration`, `--allow-generative-effects`, `--no-audio`, `--env-file`) are conditional — dropped. |
| cut | hype/run.py:834 (delegates to `build_pool_cut_cmd` at 622-650) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.cut.run", "--pool", "{out}/pool.json", "--arrangement", "{brief_out}/arrangement.json", "--brief", "{brief_copy}", "--out", "{brief_out}"]` | (none) | All extender flags in `build_pool_cut_cmd` are gated on file existence or option presence (`--scenes`, `--transcript`, `--video`, `--audio`, `--shots`, `--asset`, `--primary-asset`, `--theme`) and are dropped. |
| refine | hype/run.py:836-863 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.refine.run", "--arrangement", "{brief_out}/arrangement.json", "--pool", "{out}/pool.json", "--timeline", "{brief_out}/hype.timeline.json", "--assets", "{brief_out}/hype.assets.json", "--metadata", "{brief_out}/hype.metadata.json", "--transcript", "{out}/transcript.json", "--out", "{brief_out}"]` | (none) | Optional `--primary-asset`, `--env-file` dropped. |
| render | hype/run.py:864-883 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.render.run", "--timeline", "{brief_out}/hype.timeline.json", "--assets", "{brief_out}/hype.assets.json", "--out", "{brief_out}/hype.mp4"]` | (none) | Optional `--theme` dropped. |
| editor_review | hype/run.py:884-904 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.editor_review.run", "--brief-dir", "{brief_out}", "--run-dir", "{out}", "--out", "{brief_out}", "--iteration", "{editor_iteration}"]` | `editor_iteration` (int, default 1) | Optional `--env-file` dropped. Default for `editor_iteration` matches `getattr(args, "editor_iteration", 1)` in the lambda. |
| validate | hype/run.py:905-925 | `["{python_exec}", "-m", "astrid.packs.builtin.executors.validate.run", "--video", "{brief_out}/hype.mp4", "--timeline", "{brief_out}/hype.timeline.json", "--metadata", "{brief_out}/hype.metadata.json", "--out", "{brief_out}/validation.json"]` | (none) | Optional `--env-file` dropped. |

## Inventory — non-pool-step executors (source: each executor's `build_parser()` / `main()` argparse)

For these executors the canonical argv is "every required argument, in
declaration order"; optional flags with defaults are omitted from the manifest
argv because callers that need to override them route values through
`request.values` keyed to a manifest-declared `inputs:` entry.

| Slug | Source | Manifest argv | Required input placeholders | Notes |
|------|--------|---------------|------------------------------|-------|
| asset_cache | asset_cache/run.py:488-506 (`main`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.asset_cache.run", "--prune-older-than", "{prune_days}"]` | `prune_days` (int, default 30) | Phase 8 parity anchor (plan_v5.md §16.4). Reads `HYPE_CACHE_DIR` env var; env knob is not part of argv. |
| audio_understand | audio_understand/run.py:500-529 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.audio_understand.run", "--query", "{query}"]` | `query` (string, default = module DEFAULT_QUERY) | All sources (`--audio`, `--video`, `--at`, `--start`, `--end`) and tuning flags are optional — drop them. `--query` is technically optional with a default but is the primary surface argument; declaring it as an input ensures callers can override it. If a future caller needs `--audio` or `--video`, add the corresponding `inputs:` row plus an additional argv slot. |
| boundary_candidates | boundary_candidates/run.py:255-271 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.boundary_candidates.run", "--video", "{video}", "--manifest", "{manifest}", "--out", "{out}"]` | `video`, `manifest` | Other flags (`--asset-key`, `--transcript`, `--scenes`, `--shots`, `--quality-zones`, `--holding-screens`, `--kind`, `--window`, `--max-candidates`) have defaults and are dropped. |
| foley_review | foley_review/run.py:120-133 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.foley_review.run", "--manifest", "{manifest}", "--out", "{out}"]` | `manifest` | |
| generate_image | generate_image/run.py:447-473 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.generate_image.run"]` | (none required by argparse) | argparse has no `required=True` arguments — prompt source is either `--prompt`, `--prompts-file`, or `--preset`. Manifest can stay parameterless and rely on callers to add `--prompt {prompt}` via `request.values` once a downstream caller is identified. Document this so reviewers know the empty argv tail is intentional. |
| html_canvas_effect | html_canvas_effect/run.py:174-186 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.html_canvas_effect.run", "--effect-id", "{effect_id}", "--out", "{out}"]` | `effect_id` | Optional `--label`, `--description`, `--project-root`, `--timeline`, `--assets`, `--force` dropped. |
| human_notes | human_notes/run.py:28-48 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.human_notes.run", "--instructions", "{instructions}", "--arrangement", "{arrangement}", "--pool", "{pool}", "--out", "{out}"]` | `instructions`, `arrangement`, `pool` | Many optional flags (`--iteration`, `--env-file`, `--model`, `--apply`, `--brief`, `--brief-dir`, `--run-dir`, `--video`, `--asset`, `--primary-asset`, `--shots`, `--python-exec`, `--keep-downloads`) dropped. |
| human_review | human_review/run.py:225-238 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.human_review.run", "--html", "{html}", "--data", "{data}", "--out", "{out}"]` | `html`, `data` | Optional `--serve`, `--state`, `--response-schema`, `--port`, `--no-open`, `--timeout` dropped. |
| inspect_cut | inspect_cut/run.py:23-31 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.inspect_cut.run", "{run_dir}"]` | `run_dir` | Positional argument. Optional `--clip`, `--no-color`, `--json` dropped. |
| open_in_reigh | open_in_reigh/run.py:35-56 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.open_in_reigh.run", "--out", "{out}", "--timeline-id", "{timeline_id}"]` | `timeline_id` | `--project-id` is documented as required for the default DataProvider push but argparse marks only `--out` and `--timeline-id` as `required=True`; callers that need DataProvider push add `--project-id` via `request.values`. |
| pool_build | (also covered in pool-step section above) | see pool-step row | — | Listed twice intentionally so reviewers can confirm parity between hype-orchestrated dispatch and standalone invocation. |
| pool_merge | (also covered in pool-step section above) | see pool-step row | — | |
| publish | publish/run.py:460-491 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.publish.run", "--project-id", "{project_id}", "--timeline-id", "{timeline_id}"]` | `project_id`, `timeline_id` | Optional `--expected-version`, `--create-if-missing`, `--force`, `--timeline-file` dropped. |
| quality_zones | (also covered in pool-step section above) | see pool-step row | — | |
| quote_scout | (also covered in pool-step section above) | see pool-step row | — | |
| refine | (also covered in pool-step section above) | see pool-step row | — | |
| reigh_data | reigh_data/run.py:67-83 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.reigh_data.run", "--project-id", "{project_id}"]` | `project_id` | Optional flags (`--shot-id`, `--task-id`, `--timeline-id`, `--api-url`, `--pat`, `--env-file`, `--timeout`, `--out`, `--compact`) dropped. |
| render | (also covered in pool-step section above) | see pool-step row | — | |
| scene_describe | (also covered in pool-step section above) | see pool-step row | — | |
| scenes | (also covered in pool-step section above) | see pool-step row | — | |
| shots | (also covered in pool-step section above) | see pool-step row | — | |
| spatial_audio_page | spatial_audio_page/run.py:186-194 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.spatial_audio_page.run", "--manifest", "{manifest}", "--out", "{out}"]` | `manifest` | Optional `--no-copy-assets` dropped. |
| sprite_sheet | sprite_sheet/run.py:1359-1416 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.sprite_sheet.run", "--animation", "{animation}", "--subject", "{subject}"]` | `animation`, `subject` | Only two `required=True` args. ~50 optional flags (style, background, transparent, key-color, frames, cols/rows, model, quality, etc.) are dropped. |
| tile_video | tile_video/run.py:120-131 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.tile_video.run", "--video", "{video}", "--out", "{out}"]` | `video` | Optional `--grid`, `--overlap`, `--trim`, `--force`, `--dry-run` dropped. |
| transcribe | (also covered in pool-step section above) | see pool-step row | — | |
| triage | (also covered in pool-step section above) | see pool-step row | — | |
| understand | understand/run.py:26-48 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.understand.run", "--mode", "{mode}"]` | `mode` | This is a dispatcher: it `parse_known_args`'s `--mode` and forwards the remainder to the chosen sub-executor (`audio_understand`, `visual_understand`, `video_understand`). Manifest argv covers only the dispatcher's own surface; remaining args are passed by callers as `request.values` mapped to an open-ended `--` extra block. If a downstream caller standardises a richer surface (e.g. `--query`, `--image`, `--video`), add inputs + argv slots in a follow-up sprint. |
| validate | (also covered in pool-step section above) | see pool-step row | — | |
| video_understand | video_understand/run.py:286-310 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.video_understand.run", "--video", "{video}"]` | `video` | `--query` is optional with a default (the JSON rubric); declare an `inputs: query` row only if a caller needs to override it. Other tuning flags dropped. |
| visual_understand | visual_understand/run.py:451-481 (`build_parser`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.visual_understand.run", "--query", "{query}"]` | `query` | Only `--query` is `required=True`. Either `--image` or `--video` is needed at run time but neither is marked required at argparse — callers add the relevant flag via `request.values`. |
| youtube_audio | youtube_audio/run.py:17-53 (`main`) | `["{python_exec}", "-m", "astrid.packs.builtin.executors.youtube_audio.run", "--out", "{out_path}"]` | `out_path` (string path; distinct from framework `{out}` because argparse uses `--out` for the *file* path, not the run directory) | The mutually-exclusive `--query` / `--url` group is required, but neither is individually marked `required=True`. Callers supply exactly one via `request.values` keyed to a manifest input (`query` or `url`) and the executor's argparse rejects the missing case at runtime. Recommend declaring both inputs in the manifest with `required: false` and a manifest-level cross-field validator (or rely on the executor's own error). |

## Cross-check

For every row above, every `{name}` token in the manifest argv is either:

- a framework-provided key (`{out}`, `{python_exec}`, `{brief}`, `{brief_slug}`,
  `{brief_out}`, `{brief_copy}`), **or**
- declared in the "Required input placeholders" column (so Wave 3 will add an
  `inputs:` row for it), **or**
- a path constructed from `{out}` / `{brief_out}` and a literal filename
  (e.g. `{out}/scenes.json`) — this is plain string substitution, not a token
  lookup, and needs no `inputs:` declaration.

No row uses an output placeholder in argv yet; if Wave 3 elects to switch
e.g. `{out}/scenes.json` to a declared output token `{scenes_json}`, both the
argv and the `outputs:` block must be updated together.

## Module-path verification

Every row uses the post-restructure module path
`astrid.packs.builtin.executors.<slug>.run`. The Wave 2 restructure already
landed `executors/<slug>/run.py` in the worktree (verified by listing
`astrid/packs/builtin/executors/`); each `run.py` has an
`if __name__ == "__main__":` guard, so `python3 -m <module>` is a valid entry
point for every slug listed here.
