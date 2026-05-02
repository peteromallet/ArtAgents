# ArtAgents Architecture

ArtAgents has three canonical public concepts:

- **Orchestrators** coordinate multi-step workflows.
- **Executors** run concrete work.
- **Elements** are render/custom building blocks such as effects, animations, and transitions.

Canonical packages and commands are first-class. Retained `bin/*.py` launchers route to canonical executor or orchestrator folders.

## Onboarding Commands

Run these from the repository root before editing:

```bash
git status --short
python3 pipeline.py doctor
python3 pipeline.py orchestrators list
python3 pipeline.py executors list
python3 pipeline.py elements list
python3 pipeline.py setup
```

`setup` is dry-run by default. `python3 pipeline.py setup --apply` is the explicit local mutation path and delegates to element sync/install helpers.

Canonical discovery commands are:

```bash
python3 pipeline.py orchestrators inspect builtin.hype --json
python3 pipeline.py executors inspect builtin.render --json
python3 pipeline.py elements inspect effects text-card --json
```

These JSON commands are the runtime index for agents. Folder-backed
orchestrators and executors include metadata such as `orchestrator_root`,
`executor_root`, and `skill_file`; agents should load the ArtAgents entrypoint
skill first, then open only the specific folder-level skill needed for the
selected registry item. Do not package every executor and orchestrator skill
into one merged runtime prompt.

Default orchestrators include `builtin.hype`, `builtin.event_talks`, `builtin.thumbnail_maker`, and `builtin.understand`. Default executors include every `STEP_ORDER` built-in, upload/action executors, Moirae, and VibeComfy. Default elements include bundled effects, animations, and transitions that can be synced into `.artagents/elements/managed` and forked into `.artagents/elements/overrides`.

Each runnable orchestrator has exactly one canonical implementation location:
`artagents/orchestrators/<slug>/{orchestrator.yaml,SKILL.md,run.py}` with
optional local `src/` modules. Each runnable executor has exactly one canonical
implementation location:
`artagents/executors/<slug>/{executor.yaml,SKILL.md,run.py}` with optional local
`src/` modules. Top-level `artagents/*.py` modules are shared libraries or
system commands only; they are not alternate executor or orchestrator
implementations.

## Orchestrators

| Module or entry point | Classification | Notes |
| --- | --- | --- |
| `pipeline.py` | System entry point | Root launcher that dispatches to package commands and the canonical hype orchestrator. |
| `artagents/pipeline.py` | System command and dispatcher | Cache-aware hype command support and source of `STEP_ORDER`; not a second orchestrator format. |
| `artagents/orchestrators/hype` | Orchestrator | Canonical built-in hype orchestrator folder. |
| `artagents/orchestrators/event_talks` | Orchestrator | Canonical event-talk discovery and rendering workflow folder. |
| `artagents/orchestrators/thumbnail_maker` | Orchestrator | Canonical source-evidence thumbnail workflow folder. |
| `artagents/orchestrators/understand` | Orchestrator | Canonical dispatcher for audio, visual, and video understanding executors. |
| `bin/event_talks.py`, `bin/thumbnail_maker.py`, `bin/understand.py` | Launchers | Thin direct launchers backed by canonical orchestrator folders. |
| `artagents/orchestrators/*` | Orchestrator canonical package | Folderized orchestrator manifests, registry, runner, and CLI. |

## Built-In Executors

Every `STEP_ORDER` stage is a built-in executor exposed from a canonical folder under `artagents/executors/<slug>/`. Retained `bin/*.py` launchers import canonical executor folder entrypoints.

| `STEP_ORDER` stage | Implementation module | Retained launchers | Classification | Notes |
| --- | --- | --- | --- | --- |
| `transcribe` | `artagents/executors/builtin/transcribe.py` | `artagents/executors/transcribe`, `bin/transcribe.py` | Executor | Produces transcript data from audio or video. |
| `scenes` | `artagents/executors/builtin/scenes.py` | `artagents/executors/scenes`, `bin/scenes.py` | Executor | Detects scene boundaries. |
| `quality_zones` | `artagents/executors/builtin/quality_zones.py` | `artagents/executors/quality_zones`, `bin/quality_zones.py` | Executor | Computes source quality ranges. |
| `shots` | `artagents/executors/builtin/shots.py` | `artagents/executors/shots`, `bin/shots.py` | Executor | Splits source video into shots. |
| `triage` | `artagents/executors/builtin/triage.py` | `artagents/executors/triage`, `bin/triage.py` | Executor | Prioritizes scenes and shots for later selection. |
| `scene_describe` | `artagents/executors/builtin/scene_describe.py` | `artagents/executors/scene_describe`, `bin/scene_describe.py` | Executor | Generates visual scene descriptions. |
| `quote_scout` | `artagents/executors/builtin/quote_scout.py` | `artagents/executors/quote_scout`, `bin/quote_scout.py` | Executor | Finds candidate transcript quotes. |
| `pool_build` | `artagents/executors/builtin/pool_build.py` | `artagents/executors/pool_build`, `bin/pool_build.py` | Executor | Builds source pool data from analysis inputs. |
| `pool_merge` | `artagents/executors/builtin/pool_merge.py` | `artagents/executors/pool_merge`, `bin/pool_merge.py` | Executor | Merges pool data and theme defaults. |
| `arrange` | `artagents/executors/builtin/arrange.py` | `artagents/executors/arrange`, `bin/arrange.py` | Executor | Creates a brief-specific arrangement. |
| `cut` | `artagents/executors/builtin/cut.py` | `artagents/executors/cut`, `bin/cut.py` | Executor | Builds Reigh-compatible timeline, assets, and metadata JSON. |
| `refine` | `artagents/executors/builtin/refine.py` | `artagents/executors/refine`, `bin/refine.py` | Executor | Mutates timeline/assets/metadata using review context. |
| `render` | `artagents/executors/builtin/render_remotion.py` | `artagents/executors/render`, `bin/render_remotion.py` | Executor | Renders timeline/assets through Remotion. |
| `editor_review` | `artagents/executors/builtin/editor_review.py` | `artagents/executors/editor_review`, `bin/editor_review.py` | Executor | Reviews generated edits and writes review JSON. |
| `validate` | `artagents/executors/builtin/validate.py` | `artagents/executors/validate`, `bin/validate.py` | Executor | Validates rendered output and timeline metadata. |

## Action-Style Executors

| Module or entry point | Classification | Notes |
| --- | --- | --- |
| `publish_youtube.py`, `bin/publish_youtube.py`, `artagents/publish_youtube.py` | Executor | YouTube upload action. |
| `bin/publish.py`, `artagents/publish.py` | Executor | Publish action facade. |
| `bin/open_in_reigh.py`, `artagents/open_in_reigh.py` | Executor | Opens generated outputs in Reigh. |
| `bin/generate_image.py`, `artagents/generate_image.py` | Executor | GPT image asset generation. |
| `bin/sprite_sheet.py`, `artagents/sprite_sheet.py` | Executor | Sprite sheet generation utility. |
| `artagents/executors/audio_understand`, `bin/audio_understand.py` | Executor | Audio understanding action. |
| `artagents/executors/visual_understand`, `bin/visual_understand.py` | Executor | Image/video-frame understanding action. |
| `artagents/executors/video_understand`, `bin/video_understand.py` | Executor | Video understanding action. |
| `bin/understand.py` | Orchestrator launcher | Convenience launcher for the canonical understand orchestrator. |
| `bin/boundary_candidates.py`, `artagents/boundary_candidates.py` | Executor | Boundary candidate package generation. |
| `bin/inspect_cut.py`, `artagents/inspect_cut.py` | Executor | Cut inspection/reporting. |
| `bin/human_notes.py`, `artagents/human_notes.py` | Executor | Human note capture and conversion. |
| `artagents/executors/*` | Executor canonical package | Folderized executor manifests, registry, install, runner, and CLI. |
| `artagents/executors/vibecomfy` | External executor | VibeComfy is an external executor only, not an orchestrator. |
| `artagents/executors/moirae` | External executor | Moirae is an external executor with folder metadata. |

## Element Support

| Module or path | Classification | Notes |
| --- | --- | --- |
| `artagents/elements/schema.py` | Element support | Element schema and dependency metadata. |
| `artagents/elements/registry.py` | Element support | Deterministic resolution: active theme, overrides, managed, bundled. |
| `artagents/elements/bundled/{effects,animations,transitions}` | Element support | Bundled default managed elements. |
| `.artagents/elements/overrides` | Element support | User-editable fork target for defaults and custom elements. |
| `.artagents/elements/managed` | Element support | Installed managed elements that should not be overwritten by user overrides. |
| `artagents/effects_catalog.py` | Element support | Effect catalog support used by the elements registry. |
| `scripts/gen_effect_registry.py` | Element support | Generates Remotion registries from element source roots. |
| `artagents/timeline.py` | Shared library and element validator | Reigh-compatible timeline schema and effect/animation/transition validation. |
| `remotion/*` | Element runtime support | TypeScript renderer consuming generated element registries. |

## Shared Libraries

| Module or package | Classification | Notes |
| --- | --- | --- |
| `artagents/contracts/*` | Shared library | Common schema dataclasses for ports, outputs, cache, commands, and isolation. |
| `artagents/cache` | Shared library | Cache concept; current concrete asset cache lives in `asset_cache.py`. |
| `artagents/asset_cache.py`, `bin/asset_cache.py` | Shared library | URL and file asset cache helpers used by orchestrators and executors. |
| `artagents/llm_clients.py` | Shared library | LLM client construction and environment handling. |
| `artagents/audit/*` | Shared library | Run-local provenance ledger, graph, and HTML report. |
| `artagents/text_match.py` | Shared library | Text matching helpers. |
| `artagents/reigh_data.py`, `reigh_data.py` | Shared library and executor entry point | Reigh data fetch helper with root compatibility launcher. |
| `artagents/theme_schema.py` | Shared library | Theme schema validation helpers. |
| `artagents/arrangement_rules.py` | Shared library | Arrangement validation and rule helpers. |
| `artagents/social_publish.py` | Shared library | Shared social publishing client logic. |
| `reviewers/*` | Shared library | Focused review heuristics used by editor and validation workflows. |
| `artagents/_paths.py` | Shared library | Repository and workspace path resolution. |

This classification keeps only retained root and bin launchers; executor-owned public metadata and entrypoints live in canonical executor folders, and orchestrator-owned public metadata and entrypoints live in canonical orchestrator folders.

## Structure Enforcement

`python3 pipeline.py doctor` fails when canonical repository structure drifts.
Public executor folders under `artagents/executors/<slug>/` must include
`executor.yaml`, `run.py`, and `SKILL.md`. Public orchestrator folders under
`artagents/orchestrators/<slug>/` must include `orchestrator.yaml`, `run.py`,
and `SKILL.md`. Executor folders must not contain orchestrator metadata, and
orchestrator folders must not contain executor metadata. Legacy public package
directories are rejected so developers do not reintroduce removed concepts.

## Generated Files and Dirty Worktrees

Normal generated outputs belong under `runs/` or another ignored directory. Do not commit source media, rendered videos, local dependency environments, or secrets.

Element changes may require generated Remotion registry updates. Keep `.ts`, `.js`, `.d.ts`, and `.map` siblings synchronized in `remotion/src`, then scan for stale element aliases:

```bash
python3 scripts/gen_effect_registry.py
rg "@workspace-|workspace-effects|workspace-animations|workspace-transitions" remotion/src scripts remotion -n
```

Always inspect `git status --short` before editing. Preserve unrelated user changes, especially dirty curated executor skill files such as `artagents/executors/moirae/SKILL.md` and `artagents/executors/vibecomfy/SKILL.md`.
