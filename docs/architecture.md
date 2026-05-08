# Astrid Architecture

Astrid has three canonical public concepts:

- **Orchestrators** coordinate multi-step workflows.
- **Executors** run concrete work.
- **Elements** are render/custom building blocks such as effects, animations, and transitions.

Canonical packages and commands are first-class. `python3 -m astrid` is the
executable package gateway; every runnable tool is reached via
`python3 -m astrid [executors|orchestrators|elements] …`.

## Onboarding Commands

Run these from the repository root before editing:

```bash
python3 -m astrid --help
git status --short
python3 -m astrid doctor
python3 -m astrid orchestrators list
python3 -m astrid executors list
python3 -m astrid elements list
python3 -m astrid setup
```

`setup` is dry-run by default. `python3 -m astrid setup --apply` is the explicit local mutation path and delegates to element sync/install helpers.

Canonical discovery commands are:

```bash
python3 -m astrid orchestrators inspect builtin.hype --json
python3 -m astrid executors inspect builtin.render --json
python3 -m astrid elements inspect effects text-card --json
```

These JSON commands are the runtime index for agents. Folder-backed
orchestrators and executors include metadata such as `orchestrator_root`,
`executor_root`, and `stage_file`; agents should load the top-level Astrid
skill first, then open only the specific folder-level `STAGE.md` needed for the
selected registry item. Do not package every executor and orchestrator stage
into one merged runtime prompt.

Content ships in **packs** at `astrid/packs/<pack>/`. Each pack carries a `pack.yaml` with `id`, `name`, and `version`, and contains executor folders, orchestrator folders, and an `elements/<kind>/<id>/` tree. The shipped packs are `builtin` (the hype pipeline plus understanding/asset tools and the bundled elements), `external` (Moirae and VibeComfy), `iteration`, and `upload`. A gitignored `local` pack at `astrid/packs/local/` is created on the first `elements fork` and holds user-editable copies. Default orchestrators include `builtin.hype`, `builtin.event_talks`, and `builtin.thumbnail_maker`. Default executors include every `STEP_ORDER` built-in, upload/action executors, `builtin.understand` (audio/visual/video dispatcher), `builtin.generate_image` (with a `saint-peter-of-banodoco` onboarding preset), `external.moirae`, and `external.vibecomfy.run`/`external.vibecomfy.validate`.

Executor and orchestrator ids are always qualified — `<pack>.<name>` (for example `builtin.cut`, `external.vibecomfy.run`). Bare lookups such as `cut` are rejected at the schema and CLI boundaries. Element ids stay bare and are scoped by `kind`, so `animation/fade` and `transition/fade` coexist without collision.

Each runnable orchestrator has exactly one canonical implementation location:
`astrid/packs/<pack>/<name>/{orchestrator.yaml,STAGE.md,run.py}` with
optional local `src/` modules. Each runnable executor has exactly one canonical
implementation location:
`astrid/packs/<pack>/<name>/{executor.yaml,STAGE.md,run.py}` with optional local
`src/` modules. Each element has exactly one canonical layout:
`astrid/packs/<pack>/elements/<kind>/<id>/{component.tsx,element.yaml}`.
Top-level `astrid/*.py` modules are shared libraries or
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
| `python3 -m astrid`, `astrid/__main__.py` | System entry point | Executable package gateway for all canonical commands. |
| `astrid/pipeline.py` | System command and dispatcher | Subcommand router; falls through to `builtin.hype` via the orchestrator registry's `runtime_module` metadata. |
| `astrid/packs/builtin/hype` | Orchestrator | Canonical built-in hype orchestrator folder. |
| `astrid/packs/builtin/event_talks` | Orchestrator | Canonical event-talk discovery and rendering workflow folder. |
| `astrid/packs/builtin/thumbnail_maker` | Orchestrator | Canonical source-evidence thumbnail workflow folder. |
| `astrid/core/orchestrator/{registry,runner,cli,schema,folder}.py` | Orchestrator framework | Pack-discovery registry, runner that reads `metadata.requires_output_path`, qualified-id CLI, schema, and folder loader. |

## Executors

Every runnable tool is a built-in or external executor exposed from exactly one canonical folder under `astrid/packs/<pack>/<name>/`. The pack's id is the first segment of the executor's qualified id.

| Executor group | Canonical location | Notes |
| --- | --- | --- |
| Hype pipeline stages | `astrid/packs/builtin/{transcribe,scenes,quality_zones,shots,triage,scene_describe,quote_scout,pool_build,pool_merge,arrange,cut,refine,render,editor_review,validate}` | `STEP_ORDER` stages used by `builtin.hype`. |
| Understanding tools | `astrid/packs/builtin/{audio_understand,visual_understand,video_understand,understand}` | Concrete media understanding tools, plus a thin `understand` dispatcher executor that selects modality via `--mode`. |
| Standalone/service tools | `astrid/packs/builtin/{asset_cache,boundary_candidates,generate_image,human_notes,inspect_cut,open_in_reigh,publish,reigh_data,sprite_sheet}` | Standalone executor capabilities. |
| External tools | `astrid/packs/external/{moirae,vibecomfy}` | `external.moirae`, `external.vibecomfy.run`, `external.vibecomfy.validate`; the run+validate pair shares a venv via manifest `pack_id: vibecomfy`. |
| Iteration tools | `astrid/packs/iteration/{prepare,assemble}` | `iteration.prepare` and `iteration.assemble` for the iteration_video orchestrator. |
| Upload tools | `astrid/packs/upload/youtube/` | `upload.youtube`. |

Executor-owned complexity stays in the executor folder, usually under optional local `src/` modules. Shared pure hype/editing logic belongs in `astrid/domains/hype`; generic plumbing belongs in `astrid/utilities`.

## Element Support

| Module or path | Classification | Notes |
| --- | --- | --- |
| `astrid/core/element/schema.py` | Element support | `element.yaml` schema (`id`, singular `kind`, `pack_id`, `metadata`, `schema`, `defaults`, `dependencies`) and dependency dataclasses. |
| `astrid/core/element/registry.py` | Element support | Pack-driven resolution: active theme → `pack:local` (priority 10) → `pack:builtin` (priority 30). Fork copies into the local pack and rewrites `pack_id`. |
| `astrid/packs/builtin/elements/{effects,animations,transitions}` | Element support | Default elements shipped in the builtin pack; `kind`-scoped folders so `animations/fade` and `transitions/fade` coexist. |
| `astrid/packs/local/elements/<kind>/<id>` | Element support | Gitignored scratch pack where `elements fork` lands edited copies (auto-creates `astrid/packs/local/pack.yaml`). |
| `astrid/core/element/catalog.py` | Element support | Effect, animation, and transition catalog support used by render validation. |
| `scripts/gen_effect_registry.py` | Element support | Generates Remotion registries from the element registry; emits `@pack-<pack>-elements-<kind>/...` imports. |
| `scripts/gen_capability_index.py` | Capability discovery | Regenerates the capability index block in `SKILL.md` from executor, orchestrator, and element manifests. |
| `astrid/timeline.py` | Shared library and element validator | Reigh-compatible timeline schema and effect/animation/transition validation. |
| `remotion/*` | Element runtime support | TypeScript renderer consuming generated element registries via `@pack-builtin-elements-*` and `@pack-local-elements-*` aliases. |

## Shared Libraries

| Module or package | Classification | Notes |
| --- | --- | --- |
| `astrid/contracts/*` | Shared library | Common schema dataclasses for ports, outputs, cache, commands, and isolation. |
| `astrid/domains/hype/*` | Domain library | Shared hype-cut/editing concepts such as arrangement rules, enriched arrangements, and text matching. |
| `astrid/utilities/llm_clients.py` | Utility library | Generic LLM client construction and environment handling. |
| `astrid/audit/*` | Shared library | Run-local provenance ledger, graph, and HTML report. |
| `astrid/theme_schema.py` | Shared library | Theme schema validation helpers. |
| `astrid/_paths.py` | Shared library | Repository and workspace path resolution. |
| `astrid/packs/builtin/refine/src/reviewers/*` | Executor-owned library | Focused review heuristics used only by `builtin.refine`. |
| `astrid/packs/upload/youtube/src/social_publish.py` | Executor-owned library | Social publishing client logic used by `upload.youtube`. |

This classification keeps only retained root and bin launchers; executor-owned public metadata and entrypoints live in canonical executor folders, and orchestrator-owned public metadata and entrypoints live in canonical orchestrator folders.

## Structure Enforcement

`python3 -m astrid doctor` fails when canonical repository structure drifts.
Public executor folders under `astrid/packs/<pack>/<name>/` must include
`executor.yaml`, `run.py`, and `STAGE.md`, and the executor's qualified id's
first segment must equal the pack id. Public orchestrator folders under
`astrid/packs/<pack>/<name>/` must include `orchestrator.yaml`, `run.py`,
and `STAGE.md` with the same qualified-id rule. Element folders under
`astrid/packs/<pack>/elements/<kind>/<id>/` must include `component.tsx` and
`element.yaml`. Executor folders must not contain orchestrator metadata, and
orchestrator folders must not contain executor metadata. Legacy public package
directories (`astrid/executors/`, `astrid/orchestrators/`,
`astrid/conductors/`, `astrid/performers/`, `astrid/instruments/`,
`astrid/primitives/`) are rejected so developers do not reintroduce removed
concepts. A top-level `astrid/skills/` directory is also rejected;
per-stage guidance lives beside the executor or orchestrator it describes.

## Generated Files and Dirty Worktrees

Normal generated outputs belong under `runs/` or another ignored directory. Do not commit source media, rendered videos, local dependency environments, or secrets.

Element changes may require generated Remotion registry updates. Keep `.ts`, `.js`, `.d.ts`, and `.map` siblings synchronized in `remotion/src`, then scan for stale element aliases:

```bash
python3 scripts/gen_effect_registry.py
rg "@workspace-|workspace-effects|workspace-animations|workspace-transitions" remotion/src scripts remotion -n
```

Always inspect `git status --short` before editing. Preserve unrelated user changes, especially dirty curated executor stage files such as `astrid/packs/external/moirae/STAGE.md` and `astrid/packs/external/vibecomfy/STAGE.md`.
