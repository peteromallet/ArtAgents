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

# 5. Validate everything
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

- **Identity**: `id` (qualified as `<pack>.<slug>`), `name`, `version`.
- **Runtime**: `type` (currently `python-cli`), `entrypoint` (path to
  `run.py`), `callable` (function name, defaults to `main`).
- **Inputs and outputs**: typed ports with required/optional flags.
- **Dependencies**: Python, npm, and system requirements.
- **Secrets**: environment variables the executor needs at runtime.

Refer to `executor.json` for the full field list.

### Orchestrator Manifest (`orchestrator.yaml`)

An orchestrator is a workflow that coordinates executors and other
orchestrators. The manifest shape mirrors the executor with
additional fields for:

- **child_executors**: qualified ids this orchestrator coordinates.
- **child_orchestrators**: sub-orchestrator ids.

Refer to `orchestrator.json` for the full field list.

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

4. **`packs validate <path>`** — Validates the entire pack statically:
   checks that all manifests parse, conform to their JSON Schemas,
   have known `schema_version` values, and that declared content
   roots, docs, and runtime entrypoint files exist on disk.

All scaffold commands validate their output. A round-trip of
`packs new` → `executors new` → `orchestrators new` →
`packs validate` should succeed with zero errors.

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

## Legacy Templates

The `docs/templates/` directory contains JSON-shaped templates for the
*internal* built-in pack format. These templates describe the legacy
manifest shape used by built-in executors, orchestrators, and elements
inside `astrid/packs/`. They are **not** modified during Sprint 1 and
remain the reference for the built-in format.

The new v1 external pack contract described in this document is a
separate path. The canonical external example is `examples/packs/minimal/`.

## Next Steps

After creating and validating your pack:

1. Implement the `run.py` entrypoints for your executors and
   orchestrators.
2. Add tests in a `tests/` directory beside each component.
3. Document your pack's capabilities in `AGENTS.md`.
4. Share your pack as a Git repository for others to install (Git
   install is planned for Sprint 2).

---

*Last updated: Sprint 1 (Pack Contract and Validation)*
