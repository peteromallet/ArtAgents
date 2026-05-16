# Creating Astrid Packs

This guide walks you through creating a pack — a reusable bundle of
executors, orchestrators, and elements that Astrid agents can discover
and run.

## Quick Start

```bash
# 1. Scaffold a new pack
python3 -m astrid packs new my_video_tools

# 2. Enter the pack directory
cd my_video_tools

# 3. Add an executor
python3 -m astrid executors new my_video_tools.transcribe

# 4. Add an orchestrator
python3 -m astrid orchestrators new my_video_tools.make_highlight_reel

# 5. Add an element
python3 -m astrid elements new effects my_video_tools.my_effect

# 6. Validate everything
python3 -m astrid packs validate .
# valid: /path/to/my_video_tools
```

## Repository Shape

A pack is a directory with a `pack.yaml` manifest at its root. The
example below shows the canonical layout:

```text
my_video_tools/
  pack.yaml            # Pack manifest (required)
  AGENTS.md            # Agent-facing instructions
  README.md            # Human-facing docs
  STAGE.md             # Pack-level staging notes
  executors/
    transcribe/
      executor.yaml    # Executor manifest (required)
      run.py           # Runtime entrypoint (required)
      STAGE.md         # Component staging notes
  orchestrators/
    make_highlight_reel/
      orchestrator.yaml # Orchestrator manifest (required)
      run.py            # Runtime entrypoint (required)
      STAGE.md          # Component staging notes
  elements/
    ...                # Optional element components
```

The exact layout is declared by `pack.yaml`, not guessed by scanning
the repository. See the `content` section of your pack manifest.

## Manifests

Every pack component has a YAML manifest that declares its identity,
contract, and runtime requirements. The manifest schemas are published
as JSON Schema documents in the repository:

| Manifest | Schema |
|---|---|
| `pack.yaml` | `astrid/packs/schemas/v1/pack.json` |
| `executor.yaml` | `astrid/packs/schemas/v1/executor.json` |
| `orchestrator.yaml` | `astrid/packs/schemas/v1/orchestrator.json` |
| `element.yaml` | `astrid/packs/schemas/v1/element.json` |

Shared constraints (id patterns, version format, runtime shape, etc.)
are defined in `astrid/packs/schemas/v1/_defs.json`.

All v1 manifests require a `schema_version: 1` field. Validation
rejects unknown schema versions with a clear error message. This
contract allows the schemas to evolve without breaking existing packs.

### Pack Manifest (`pack.yaml`)

The pack manifest declares:

- **Identity**: `id`, `name`, `version`, `description`.
- **Content roots**: where to find executor, orchestrator, and element
  manifests (e.g., `executors: executors`).
- **Agent instructions**: `purpose`, `normal_entrypoints`,
  `do_not_use_for`, `required_context`.
- **Documentation references**: paths to `AGENTS.md`, `README.md`, etc.

Refer to `pack.json` for the full field list and constraints.

### Executor Manifest (`executor.yaml`)

An executor is a concrete unit of work an agent can run. Each
executor manifest declares:

- **Identity**: `schema_version: 1`, `id` (qualified as `<pack>.<slug>`),
  `name`, `version`, `kind: external`.
- **Runtime**: a `runtime` object with `type: command` and a nested
  `command.argv` — the full subprocess argument vector with
  `{python_exec}` and `{input_name}` placeholders. There is **no**
  top-level `command:` field; the runtime block is the single source of
  truth.
- **Inputs and outputs**: typed ports with required/optional flags;
  placeholders in `runtime.command.argv` must reference declared
  `inputs[].name` values.
- **Dependencies**: Python, npm, and system requirements.
- **Secrets**: environment variables the executor needs at runtime.

Refer to `executor.json` for the full field list. A working example
ships with the `iteration` pack at
`astrid/packs/iteration/executors/prepare/executor.yaml`.

### Orchestrator Manifest (`orchestrator.yaml`)

An orchestrator is a workflow that coordinates executors and other
orchestrators. The manifest shape mirrors the executor (same
`runtime.type: command` + nested `runtime.command.argv`, no legacy
`runtime.kind` field) with additional fields for:

- **child_executors**: qualified ids this orchestrator coordinates.
- **child_orchestrators**: sub-orchestrator ids.

Refer to `orchestrator.json` for the full field list. A working
example ships with the `seinfeld` pack at
`astrid/packs/seinfeld/orchestrators/dataset_build/orchestrator.yaml`.

### Element Manifest (`element.yaml`)

An element is a visual building block — an effect, animation, or
transition. Each element manifest declares:

- **Identity**: `id` (slug only, e.g., `my_effect`), `kind` (singular:
  `effect`, `animation`, or `transition`), `pack_id` (the owning pack).
- **Inputs and outputs**: a JSON Schema `schema` and `defaults` for
  parameter values.
- **Dependencies**: JS packages and Python requirements.

The CLI uses plural kind names (`effects`, `animations`, `transitions`)
while the manifest `kind` field uses the singular form. Scaffold with:

```bash
python3 -m astrid elements new effects my_pack.my_effect
```

The scaffolded directory contains:

```text
elements/effects/my_effect/
  element.yaml     # Element manifest (required)
  component.tsx    # React component stub
  STAGE.md         # Component staging notes
```

Refer to `element.json` for the full field list.

## Scaffold Flow

The recommended workflow for creating a pack:

1. **`packs new <id>`** — Creates the pack skeleton: `pack.yaml`,
   `AGENTS.md`, `README.md`, `STAGE.md`, and empty `executors/`,
   `orchestrators/`, `elements/` directories. The scaffolded pack
   passes `packs validate` immediately.

2. **`executors new <pack>.<slug>`** — Scaffolds a new executor
   component: `executor.yaml`, `run.py` stub, and `STAGE.md` inside
   the executor content root. Must be run from inside the pack
   directory. The scaffolded component is validated against the v1
   schema before declaring success.

3. **`orchestrators new <pack>.<slug>`** — Same as above for
   orchestrator components.

4. **`elements new <kind> <pack>.<slug>`** — Scaffolds a new element
   component: `element.yaml`, `component.tsx`, and `STAGE.md` inside
   the element content root. The `<kind>` argument is plural
   (`effects`, `animations`, or `transitions`). Must be run from
   inside the pack directory.

5. **`packs validate <path>`** — Validates the entire pack statically:
   checks that all manifests parse, conform to their JSON Schemas,
   have known `schema_version` values, and that declared content
   roots, docs, and runtime entrypoint files exist on disk.

All scaffold commands validate their output. A round-trip of
`packs new` → `executors new` → `orchestrators new` →
`elements new` → `packs validate` should succeed with zero errors.

## Validation

Validation is **static**. It checks:

- `pack.yaml` exists and is valid YAML.
- `schema_version` is a known integer (currently only `1`).
- Each manifest conforms to its JSON Schema.
- Declared content roots and doc references point to existing paths.
- Runtime entrypoint files (`run.py`) exist on disk.
- Component `STAGE.md` files exist (warning, not error).

Validation does **not**:

- Import or execute `run.py` (no sandboxing is needed — the file is
  never loaded).
- Run any code from the pack.
- Require a bound Astrid session.
- Install dependencies.

Errors include the specific file path and field, e.g.:

```
executors/my_exec/executor.yaml: missing required field runtime
pack.yaml: missing required field id
executors/my_exec/run.py: runtime entrypoint file not found
```

## Reference Example

A complete minimal pack is at `examples/packs/minimal/`. It contains:

- One executor (`minimal.ingest_assets`): ingests and validates
  project assets.
- One orchestrator (`minimal.make_trailer`): coordinates asset
  ingestion and assembly.

Validate it with:

```bash
python3 -m astrid packs validate examples/packs/minimal
```

Inspect components without a session:

```bash
python3 -m astrid executors --pack-root examples/packs/minimal inspect minimal.ingest_assets
python3 -m astrid orchestrators --pack-root examples/packs/minimal inspect minimal.make_trailer
```

The ``--pack-root`` flag must appear **before** the subcommand (e.g.,
``inspect``) because it is an option on the parent ``executors`` /
``orchestrators`` parser.

This example lives at the repo root and is *not* a built-in
discovered pack — it demonstrates the external pack contract.

## Plan-v2 Builder

Orchestrator scaffolds include a `plan_template.py` that imports from
`astrid.core.orchestrator.plan_v2`. This shared module provides:

- `emit_plan_json(plan, path)` — serialize a plan dict as canonical JSON.
- `build_step_command(python_exec, run_root, step_id, module_path)` —
  construct a step command following the canonical runtime path pattern.
- `make_produces(path)` — create a minimal `produces` block with a
  `file_nonempty` check.
- `PlanStep` and `PlanV2` TypedDicts for type-safe plan construction.

See the module docstring in `astrid/core/orchestrator/plan_v2.py` for
the full API.

## Canonical Reference

The scaffolded output from `packs new` / `executors new` /
`orchestrators new` / `elements new` is the canonical reference for
pack structure. See the Quick Start section above.

The `docs/templates/` directory contains legacy templates from the
pre-Sprint-1 internal format and is retained for historical reference
only.

## Writing an Effective AGENTS.md

Every pack should include an `AGENTS.md` at its root. This file helps
AI agents (and human users) understand **when and how** to use your
pack. The structured `agent:` section in `pack.yaml` is the
**authoritative source** for machine-readable metadata; `AGENTS.md` is
supplemental prose that adds context and examples.

### What to Cover

**When to Use This Pack** — Describe the problems this pack solves.
What signals should make an agent reach for this pack instead of
another? Keep it brief and concrete.

**Normal Entrypoints** — List the orchestrator (or executor) IDs that
agents should use as entrypoints for typical work. These map to the
`agent.normal_entrypoints` field in `pack.yaml`. Explain what each
entrypoint does at a high level.

**Low-Level Executors** — Identify executors that are building blocks
rather than standalone entrypoints. Agents should not invoke these
directly unless they have a specific, informed reason. This
corresponds to `agent.do_not_use_for` guidance.

**Required Context and Inputs** — What information does the agent need
before calling this pack? List required secrets, API keys,
configuration values, file paths, or other context. Reference the
`agent.required_context` field and the structured `secrets:` list in
`pack.yaml`.

**Constraints and Limitations** — Document when an agent should
**not** use this pack (the `agent.do_not_use_for` guidance). Note any
performance limits, rate limits, concurrency restrictions, or
environment requirements.

**Secrets and Dependencies** — Describe the secrets and dependencies
declared in `pack.yaml`. Explain how to obtain API keys, what
environment variables to set, and any system packages that must be
installed before using the pack.

**Component Documentation** — Link to `STAGE.md` files inside each
component directory (e.g., `executors/my_exec/STAGE.md`). These files
contain bounded, deterministic stage summaries that agents can read
for detailed usage instructions.

### Machine-Readable Index

Agents can use the `packs agent-index` command to get a structured,
deterministic JSON index of all installed packs:

```bash
# Full index
python3 -m astrid packs agent-index --json

# Filter by pack
python3 -m astrid packs agent-index --pack-id my-pack --json
```

The index includes normal entrypoints, do-not-use-for guidance,
required context, structured secrets and dependencies, component
counts, and bounded stage excerpts — everything an agent needs to
choose the right tool without reading every manifest manually.

### Example AGENTS.md Skeleton

```markdown
# My Pack — AGENTS.md

## When to Use This Pack

Use this pack when you need to [short description of capability].

## Entrypoints

- `my-pack.orchestrator.main` — Primary workflow for [purpose].
- `my-pack.executor.helper` — Utility for [specific task].

## Low-Level Executors

- `my-pack.executor.internal` — Internal building block; do not call
  directly unless you understand [specific reason].

## Required Context

- API key for [service] (set as `MY_API_KEY` environment variable).
- Access to [resource/file path].

## Do Not Use For

Do not use this pack for [scenario where it's inappropriate]. Use
[alternative pack] instead.

## Secrets and Dependencies

- `MY_API_KEY` (required) — Obtain from [service console URL].
- Python packages: `requests`, `pyyaml` (see `dependencies.python` in
  `pack.yaml`).

## Component Docs

- Orchestrator: `orchestrators/main/STAGE.md`
- Executor: `executors/helper/STAGE.md`
```

---

*Last updated: Sprint 6*
