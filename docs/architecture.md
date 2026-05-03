# ArtAgents Architecture

ArtAgents has three canonical public concepts:

- **Orchestrators** coordinate multi-step workflows.
- **Executors** run concrete work.
- **Elements** are render/custom building blocks such as effects, animations, and transitions.

Canonical packages and commands are first-class. `python3 -m artagents` is the
executable package gateway; every runnable tool is reached via
`python3 -m artagents [executors|orchestrators|elements] …`.

## Onboarding Commands

Run these from the repository root before editing:

```bash
python3 -m artagents --help
git status --short
python3 -m artagents doctor
python3 -m artagents orchestrators list
python3 -m artagents executors list
python3 -m artagents elements list
python3 -m artagents setup
```

`setup` is dry-run by default. `python3 -m artagents setup --apply` is the explicit local mutation path and delegates to element sync/install helpers.

Canonical discovery commands are:

```bash
python3 -m artagents orchestrators inspect builtin.hype --json
python3 -m artagents executors inspect builtin.render --json
python3 -m artagents elements inspect effects text-card --json
```

These JSON commands are the runtime index for agents. Folder-backed
orchestrators and executors include metadata such as `orchestrator_root`,
`executor_root`, and `stage_file`; agents should load the top-level ArtAgents
skill first, then open only the specific folder-level `STAGE.md` needed for the
selected registry item. Do not package every executor and orchestrator stage
into one merged runtime prompt.

Default orchestrators include `builtin.hype`, `builtin.event_talks`, `builtin.thumbnail_maker`, and `builtin.understand`. Default executors include every `STEP_ORDER` built-in, upload/action executors, Moirae, and VibeComfy. Default elements include bundled effects, animations, and transitions that can be synced into `.artagents/elements/managed` and forked into `.artagents/elements/overrides`.

Each runnable orchestrator has exactly one canonical implementation location:
`artagents/orchestrators/<slug>/{orchestrator.yaml,STAGE.md,run.py}` with
optional local `src/` modules. Each runnable executor has exactly one canonical
implementation location:
`artagents/executors/<slug>/{executor.yaml,STAGE.md,run.py}` with optional local
`src/` modules. Top-level `artagents/*.py` modules are shared libraries or
system commands only; they are not alternate executor or orchestrator
implementations.

For creation decisions, use `docs/creating-tools.md` and the templates under
`docs/templates/`. Add an executor for one concrete action, an orchestrator for
a workflow, and an element for a reusable render primitive. Agents should avoid
manual chains of low-level stage artifacts unless they are debugging a specific
executor.

## Orchestrators

| Module or entry point | Classification | Notes |
| --- | --- | --- |
| `python3 -m artagents`, `artagents/__main__.py` | System entry point | Executable package gateway for all canonical commands. |
| `artagents/pipeline.py` | System command and dispatcher | Cache-aware hype command support and source of `STEP_ORDER`; not a second orchestrator format. |
| `artagents/orchestrators/hype` | Orchestrator | Canonical built-in hype orchestrator folder. |
| `artagents/orchestrators/event_talks` | Orchestrator | Canonical event-talk discovery and rendering workflow folder. |
| `artagents/orchestrators/thumbnail_maker` | Orchestrator | Canonical source-evidence thumbnail workflow folder. |
| `artagents/orchestrators/understand` | Orchestrator | Canonical dispatcher for audio, visual, and video understanding executors. |
| `artagents/orchestrators/*` | Orchestrator canonical package | Folderized orchestrator manifests, registry, runner, and CLI. |

## Executors

Every runnable tool is a built-in or external executor exposed from exactly one canonical folder under `artagents/executors/<slug>/`.

| Executor group | Canonical location | Notes |
| --- | --- | --- |
| Hype pipeline stages | `artagents/executors/{transcribe,scenes,quality_zones,shots,triage,scene_describe,quote_scout,pool_build,pool_merge,arrange,cut,refine,render,editor_review,validate}` | `STEP_ORDER` stages used by the hype orchestrator. |
| Understanding tools | `artagents/executors/{audio_understand,visual_understand,video_understand}` | Concrete media understanding tools used directly or by the understand orchestrator. |
| Standalone/service tools | `artagents/executors/{asset_cache,boundary_candidates,generate_image,human_notes,inspect_cut,open_in_reigh,publish,reigh_data,sprite_sheet,upload_youtube}` | Standalone executor capabilities. |
| External tools | `artagents/executors/{vibecomfy,moirae}` | VibeComfy and Moirae are external executors only, not orchestrators. |

Executor-owned complexity stays in the executor folder, usually under optional local `src/` modules. Shared pure hype/editing logic belongs in `artagents/domains/hype`; generic plumbing belongs in `artagents/utilities`.

## Element Support

| Module or path | Classification | Notes |
| --- | --- | --- |
| `artagents/elements/schema.py` | Element support | Element schema and dependency metadata. |
| `artagents/elements/registry.py` | Element support | Deterministic resolution: active theme, overrides, managed, bundled. |
| `artagents/elements/bundled/{effects,animations,transitions}` | Element support | Bundled default managed elements. |
| `.artagents/elements/overrides` | Element support | User-editable fork target for defaults and custom elements. |
| `.artagents/elements/managed` | Element support | Installed managed elements that should not be overwritten by user overrides. |
| `artagents/elements/catalog.py` | Element support | Effect, animation, and transition catalog support used by render validation. |
| `scripts/gen_effect_registry.py` | Element support | Generates Remotion registries from element source roots. |
| `artagents/timeline.py` | Shared library and element validator | Reigh-compatible timeline schema and effect/animation/transition validation. |
| `remotion/*` | Element runtime support | TypeScript renderer consuming generated element registries. |

## Shared Libraries

| Module or package | Classification | Notes |
| --- | --- | --- |
| `artagents/contracts/*` | Shared library | Common schema dataclasses for ports, outputs, cache, commands, and isolation. |
| `artagents/domains/hype/*` | Domain library | Shared hype-cut/editing concepts such as arrangement rules, enriched arrangements, and text matching. |
| `artagents/utilities/llm_clients.py` | Utility library | Generic LLM client construction and environment handling. |
| `artagents/audit/*` | Shared library | Run-local provenance ledger, graph, and HTML report. |
| `artagents/theme_schema.py` | Shared library | Theme schema validation helpers. |
| `artagents/_paths.py` | Shared library | Repository and workspace path resolution. |
| `artagents/executors/refine/src/reviewers/*` | Executor-owned library | Focused review heuristics used only by the refine executor. |
| `artagents/executors/upload_youtube/src/social_publish.py` | Executor-owned library | Social publishing client logic used by `upload.youtube`. |

This classification keeps only retained root and bin launchers; executor-owned public metadata and entrypoints live in canonical executor folders, and orchestrator-owned public metadata and entrypoints live in canonical orchestrator folders.

## Structure Enforcement

`python3 -m artagents doctor` fails when canonical repository structure drifts.
Public executor folders under `artagents/executors/<slug>/` must include
`executor.yaml`, `run.py`, and `STAGE.md`. Public orchestrator folders under
`artagents/orchestrators/<slug>/` must include `orchestrator.yaml`, `run.py`,
and `STAGE.md`. Executor folders must not contain orchestrator metadata, and
orchestrator folders must not contain executor metadata. Legacy public package
directories are rejected so developers do not reintroduce removed concepts.
A top-level `artagents/skills/` directory is also rejected; per-stage guidance
lives beside the executor or orchestrator it describes.

## Generated Files and Dirty Worktrees

Normal generated outputs belong under `runs/` or another ignored directory. Do not commit source media, rendered videos, local dependency environments, or secrets.

Element changes may require generated Remotion registry updates. Keep `.ts`, `.js`, `.d.ts`, and `.map` siblings synchronized in `remotion/src`, then scan for stale element aliases:

```bash
python3 scripts/gen_effect_registry.py
rg "@workspace-|workspace-effects|workspace-animations|workspace-transitions" remotion/src scripts remotion -n
```

Always inspect `git status --short` before editing. Preserve unrelated user changes, especially dirty curated executor stage files such as `artagents/executors/moirae/STAGE.md` and `artagents/executors/vibecomfy/STAGE.md`.
