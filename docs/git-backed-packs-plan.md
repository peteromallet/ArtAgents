# Git-Backed Astrid Packs Plan

## Intent

Astrid packs should become first-class, schema-validated, Git-backed capability
bundles. A maker should be able to keep everything for a project or domain in a
GitHub repository, install that repository into Astrid, and have agents clearly
understand which executors, orchestrators, and elements it provides.

This means the pack abstraction is real. It is not just an internal folder
grouping inside `astrid/packs/`.

## Product Model

A pack is an uploadable and installable project capability bundle.

It may contain:

- Executors: concrete units of work an agent can run.
- Orchestrators: workflows that coordinate executors and other orchestrators.
- Elements: reusable render building blocks such as effects, animations, and
  transitions.
- Schemas: input, output, and project data contracts used by the pack.
- Human docs: builder-facing and user-facing explanation.
- Agent docs: compact operational instructions for tool choice, constraints,
  and examples.
- Optional examples, fixtures, and test assets.

The target user story is:

1. A builder creates a GitHub repo for a project pack.
2. They define the pack and its components with clear manifests and docs.
3. They run local validation before publishing.
4. A user or agent installs the pack from GitHub.
5. Astrid lists, searches, inspects, and runs the pack's tools alongside
   built-in tools.
6. Agents can read a compact index that explains what the pack is for and which
   component to choose for each task.

## Example Repository Shape

```text
my-project-pack/
  pack.yaml
  README.md
  AGENTS.md
  executors/
    ingest_assets/
      executor.yaml
      STAGE.md
      run.py
      tests/
  orchestrators/
    make_trailer/
      orchestrator.yaml
      STAGE.md
      run.py
      plan_template.py
      tests/
  elements/
    effects/
      project-title-card/
        element.yaml
        component.tsx
  schemas/
    brief.schema.json
    asset-manifest.schema.json
  examples/
    minimal/
```

The exact layout should be declared by `pack.yaml`, not guessed by recursively
scanning the whole repository.

## Pack Manifest Contract

`pack.yaml` should become the source of truth for the pack.

Recommended fields:

```yaml
schema_version: 1
id: my_project
name: My Project Pack
version: 0.1.0
astrid_version: ">=0.3.0"
description: Tools for making videos and assets for My Project.

content:
  executors: executors
  orchestrators: orchestrators
  elements: elements
  schemas: schemas
  examples: examples

capabilities:
  - video-editing
  - image-generation
  - project-assets

keywords:
  - trailer
  - thumbnails
  - brand-assets

agent:
  purpose: Make videos and assets for My Project.
  normal_entrypoints:
    - my_project.make_trailer
  do_not_use_for:
    - generic video editing unrelated to My Project
  required_context:
    - project brief
    - source asset folder

docs:
  user: README.md
  agent: AGENTS.md

dependencies:
  python:
    - requests>=2
  npm: []
  system:
    - ffmpeg

secrets:
  - name: OPENAI_API_KEY
    required: true
    description: Used for image and text generation.
```

`provides` should not be manually authored in v1. Declared content roots and
component manifests define the public search space; validation generates the
component inventory for `inspect`, `agent-index`, and install summaries. Manual
inventories are too likely to drift.

Dependencies are declarative in v1. Astrid validates their shape and surfaces
them in `inspect`, install summaries, and doctor checks, but it does not
automatically install Python, npm, or system dependencies until an explicit
environment model exists.

## Component Manifest Contracts

Each public component should have a manifest validated against a schema:

- `executor.yaml`
- `orchestrator.yaml`
- `element.yaml`
- Future: `theme.yaml`

The schemas should define required fields, allowed values, runtime entrypoints,
input/output declarations, docs references, and searchable metadata.

Manifests should be written for both machines and people. A builder should be
able to read one and understand what the component does, and an agent should be
able to inspect one and decide whether the component fits a task.

The structured manifest fields are authoritative for agent behavior. Markdown
docs such as `README.md`, `AGENTS.md`, and `STAGE.md` are supplemental prose.
They can explain nuance and examples, but they should not be the only source for
normal entrypoints, required inputs, secrets, or "do not use for" guidance.

External manifest runtime fields should describe stable adapter semantics, not
current internal import mechanics. Prefer fields like:

```yaml
runtime:
  type: python-cli
  entrypoint: run.py
  callable: main
```

over internal names such as `runtime_module`.

For v1, `python-cli` is the only external runtime adapter. Its contract should
be explicit before implementation:

- The `entrypoint` path is resolved relative to the component root.
- The entrypoint is invoked through Astrid's normal runner path, not by discovery
  code importing arbitrary pack modules.
- The working directory is the component root unless the runner already has a
  stronger convention.
- CLI arguments are passed exactly as the user supplied them after `--`, plus
  any runner-owned arguments such as `--out` that the manifest declares.
- Environment variables are inherited from the Astrid process except secrets:
  declared secrets are the only secrets Astrid intentionally surfaces in install
  summaries and future secret-passing UX.
- Exit code `0` means success. Non-zero exits are wrapped with the component id,
  command, and relevant stderr/stdout excerpts.
- Outputs are declared in the manifest or stage docs; v1 validation checks the
  declarations but does not enforce every output at runtime unless existing
  executor/orchestrator runners already do.

## Agent-Facing Index

Astrid should expose a compact agent index for installed packs.

Possible commands:

```bash
python3 -m astrid packs agent-index
python3 -m astrid packs inspect my_project --agent
```

The output should answer:

- What is this pack for?
- What should this pack not be used for?
- Which orchestrators are the normal entrypoints?
- Which executors are low-level building blocks?
- Which elements are available for timelines?
- What inputs, outputs, secrets, and dependencies matter?
- What examples should an agent copy?

This should be generated from `pack.yaml`, component manifests, `STAGE.md`
files, and the pack-level agent docs.

For v1, generation should be deterministic. Structured manifest fields should
dominate; Markdown should be linked, referenced by path, or excerpted only from
explicit bounded sections. Do not use LLM summarization or heuristic full-doc
digestion for the first agent index.

## Required CLI Surface

Pack lifecycle:

```bash
python3 -m astrid packs validate ./my-project-pack
python3 -m astrid packs install https://github.com/user/my-project-pack
python3 -m astrid packs uninstall my_project
python3 -m astrid packs update my_project
python3 -m astrid packs list
python3 -m astrid packs inspect my_project
```

Builder scaffolding:

```bash
python3 -m astrid packs new my_project
python3 -m astrid executors new my_project.ingest_assets
python3 -m astrid orchestrators new my_project.make_trailer
python3 -m astrid elements new effect my_project.project-title-card
```

The install location should be outside the Astrid source tree, for example:

```text
~/.astrid/packs/
  my_project/
  another_pack/
```

Discovery should include:

- Built-in packs shipped with Astrid.
- Installed user packs under `~/.astrid/packs/`.
- Optional project-local packs, if a workspace declares them.

## Templates

Templates are required for this to feel buildable.

Minimum templates:

- Pack template.
- Executor template.
- Orchestrator template.
- Element effect template.
- Element animation template.
- Element transition template.
- Future theme template.

Generated files should include:

- Manifest YAML.
- `STAGE.md`.
- Minimal runtime file.
- Test stub.
- README or docs stub where appropriate.
- Agent-instructions stub where appropriate.

The templates should be the canonical examples. Avoid making users copy a
production pack with historical baggage.

## Validation Requirements

`packs validate` should check:

- `pack.yaml` parses with a real YAML parser.
- All manifests pass schema validation.
- Pack id and component ids are valid and consistently namespaced.
- Declared content roots exist.
- Referenced docs, schemas, runtime files, and examples exist.
- Runtime entrypoint paths exist and are statically well-formed.
- No undeclared manifests are accidentally exposed.
- No duplicate ids collide with installed or built-in packs.
- Required secret declarations are well formed.
- Declared dependency sections are well formed.
- Elements compile or typecheck where practical.
- `STAGE.md` files exist for public executors and orchestrators.

Validation errors should be specific and actionable:

```text
orchestrators/make_trailer/orchestrator.yaml:
  missing required field metadata.runtime_entrypoint
```

The current custom flat YAML parser should be removed or bypassed for manifests
that users author.

Validation must not execute arbitrary pack code by default. A separate trusted
runtime smoke test may import or execute an entrypoint after the user confirms
they trust the pack, but normal schema/path validation should remain static.

## Runtime Resolution

Runtime resolution should become manifest-based and singular.

Canonical flow:

```text
component id
  -> owning pack
  -> validated component manifest
  -> runtime file or module
  -> entrypoint
```

Introduce a `PackResolver` abstraction as part of this work. It should be
read-only and deterministic: resolve pack roots, component roots, docs, schemas,
runtime files, examples, and assets from already-known pack roots. Runtime
resolution, validation, inspect, and agent-index should consume this resolver
instead of assuming components live under the source tree.

Install records, active revisions, rollback pointers, and install/update locks
belong to a separate `InstalledPackStore`, not to `PackResolver`.

This replaces the current split between:

- Registry path reading `orchestrator.yaml` and importing `runtime_module`.
- Author/compile path loading `<pack>/<name>.py` directly.

The `builtin.hype` folder should become the canonical pattern. The legacy
`hype.py` DSL fixture should move to tests, be renamed as a fixture, or be
deleted after resolver unification.

## Review Synthesis

Two independent review panels agreed on the core direction and found the same
high-risk gaps.

High-confidence changes:

- Validation-first sequencing is correct.
- Manual `provides` should be removed in favor of generated inventory.
- Security, trust, versioning, and update semantics must be designed before
  install/runtime, even if full sandboxing ships later.
- Minimal scaffolding should arrive early; a blank-repo builder needs
  `packs new <id>` in the first implementation sprint.
- Agent-legible structured fields should move into the manifest contract early,
  not wait for late-stage polish.
- Dependencies should be declaration-only in v1 unless an environment model is
  deliberately implemented.
- Runtime contracts need to define callable shape, argv/env behavior, output
  conventions, exit codes, and error wrapping.
- `PackResolver`, deterministic discovery, and runtime proof should happen
  before install. An installed pack must not be visible but unrunnable.

Useful cautions:

- Keep structured fields authoritative and Markdown supplemental.
- Consider stronger namespace policy before a public ecosystem grows; bare pack
  ids are acceptable for v1 only if collisions are detected and rejected.
- Treat external elements as a harder problem than executors/orchestrators
  because Remotion registry and compilation paths are source-tree-sensitive.
- Avoid adding a second "inline component" authoring model too early. Lower the
  ceremony with scaffolding and good templates first.

## Release Milestones

The two-week sprints below are implementation slices. They should not be treated
as user-facing releases unless they complete a vertical workflow. "Go all the
way" for this project means shipping fewer surfaces that work end to end, not
many partial surfaces that only validate, only inspect, or only install.

### Milestone 1: Local Executor/Orchestrator Packs Work End To End

This is the first real product milestone.

Ship only when:

- `packs new <id>` creates a valid pack skeleton.
- Minimal `executors new` and `orchestrators new` create runnable component
  skeletons inside that pack.
- The pack can contain at least one executor and one orchestrator.
- `packs validate <path>` gives useful builder-facing errors.
- `packs install <local-path>` activates the pack after validation.
- `packs inspect <id>` and `packs inspect <id> --agent` explain the pack.
- Installed executors/orchestrators run through the normal CLI.
- Secrets and dependencies are visible and explicit, even if Astrid does not
  manage them automatically.
- `packs uninstall <id>` removes the pack cleanly.
- At least one real built-in or built-in-shaped pack path has exercised the same
  resolver and manifest path.

Likely implementation coverage: Sprint 0 through Sprint 3.

### Milestone 2: Git-Backed Packs Work End To End

Ship only when:

- A pack can be installed from a Git URL.
- The installed revision is pinned to a concrete commit.
- Install shows a trust summary before activation.
- Validation happens before activation.
- Installed Git-pack components can be inspected and run.
- Updates support dry-run/diff, revalidation, previous-revision retention, and
  rollback.
- Private repos use the user's existing Git credentials without Astrid managing
  GitHub tokens in v1.

Likely implementation coverage: Sprint 4.

### Milestone 3: Builder UX Is First-Class

Ship only when:

- `executors new` and `orchestrators new` create valid component skeletons.
- Templates point at the canonical runtime path.
- The docs cover the blank-repo path from creation to installed runnable pack.
- The shared plan builder removes copy-pasted plan-v2 boilerplate.
- Generated examples are the canonical examples; users do not need to copy
  production internals.

Likely implementation coverage: Sprint 5.

### Milestone 4: Agent UX Is First-Class

Ship only when:

- `packs agent-index` exists.
- `inspect --json` is rich enough for agent selection.
- The index identifies normal entrypoints, low-level building blocks, required
  secrets, dependencies, "do not use for" constraints, and examples.
- Structured manifest fields are authoritative and Markdown is supplemental.

Likely implementation coverage: Sprint 6.

### Milestone 5: External Elements Work End To End

Ship only when:

- External element manifests validate.
- Installed external elements participate in registry generation.
- Type generation and Remotion compilation work.
- A rendered timeline can use an installed external element.
- Element-related failures have a clear debug path.

Likely implementation coverage: Sprint 7.

### Milestone 6: Trust And Sandbox Hardening

Ship only when:

- The install/update/rollback trust model has been exercised on real packs.
- Secret handling is explicit and auditable enough for user-installed code.
- `packs doctor` or equivalent can report readiness problems.
- Optional sandbox mode can run at least validation and one installed-pack
  command with only explicit workspace and credential access.

Likely implementation coverage: Sprint 8, Sprint 9, and optional Sprint 10.

### Milestone 7: Pack Portfolio Rationalized

Ship only when:

- Every existing Astrid pack has an explicit classification: core, bundled
  installable, optional installable, local-only scratch, deprecated, or removed.
- Core packs are the minimum platform surface Astrid needs to function and
  demonstrate the system.
- Installable packs follow the external pack contract and can be validated,
  inspected, installed, and run through the same paths as user packs.
- Deprecated packs have warnings, aliases, or migration notes.
- The capability index, skills installation, and docs reflect the new pack
  taxonomy.

Likely implementation coverage: Sprint 9, after one real built-in migration has
already proved the path.

## Two-Week Sprint Roadmap

This project should be sequenced as several two-week sprints. The right order is
architecture gate, contract, validation, resolver/discovery, local install with
execution, Git install, authoring, agent polish, element hardening, migration
proof, portfolio rationalization, and optional sandboxing. Installing GitHub
repos before the validation/trust contract exists would produce a brittle
plugin surface; installing packs before a local external pack can actually run
creates a user-visible dead zone and hides resolver bugs.

Recommended megaplan settings are intentionally dialed down one notch from the
strictest rubric read. The doc and prior review work have already paid down some
planning uncertainty, so these settings should be the default starting point for
each sprint unless new unknowns appear during brief writing.

| Sprint | Megaplan setting | Notes |
| --- | --- | --- |
| Sprint 0: Architecture Decision Gate | `premium/standard/medium` | Use this if the gate is freezing trust, namespace, versioning, dependency, and migration decisions. |
| Sprint 1: Pack Contract And Validation | `premium/standard/medium` | Use this when schema and manifest contracts are still being frozen. If Sprint 0 resolves those decisions crisply, downgrade to `thoughtful/standard/medium`. |
| Sprint 2: PackResolver, Deterministic Discovery, And Runtime Path | `thoughtful/standard/medium` | Cross-cutting runtime and discovery work, but with major product decisions already made. |
| Sprint 3: Local Pack Install, Trust UX, And Runnable Packs | `thoughtful/standard/low` | Activation and install lifecycle work; should mostly follow the resolver and contract from earlier sprints. |
| Sprint 4: Git Install, Pinning, And Update Safety | `thoughtful/standard/medium` | Git supply-chain mechanics need care, but full robust/premium treatment is reserved for unresolved trust-model changes. |
| Sprint 5: Builder Scaffolding And Templates | `basic/light` or `thoughtful/light` | Use `thoughtful/light` if template sequencing or shared builder extraction needs a smarter plan; otherwise `basic/light`. |
| Sprint 6: Agent Index And Pack Legibility | `thoughtful/light` | Mostly product-shaped summarization and inspect output once the manifest contract is stable. |
| Sprint 7: Rich Example Pack And External Element Hardening | `thoughtful/standard/medium +prep` | Keep prep because Remotion registry, typegen, and external element behavior are integration unknowns. |
| Sprint 8: Legacy Migration | `thoughtful/standard` or `thoughtful/standard/low` | Use the lower-depth option only if the chosen built-in pack does not expose runtime assumptions. |
| Sprint 9: Pack Portfolio Classification And Migration | `thoughtful/standard/medium` | Classify every existing pack and convert, deprecate, or explicitly defer each one. |
| Optional Sprint 10: Sandboxed Pack Runtime | `thoughtful/standard/medium +prep` | Prep is justified by container/runtime behavior and security-boundary unknowns. |

Escalate mid-flight rather than starting every sprint at the highest tier. If a
plan keeps missing issues raised by critique, if revision does not resolve the
critique, or if execution produces work review cannot accept, bump profile,
robustness, or depth for the remainder of that sprint.

### Sprint 0: Architecture Decision Gate

Goal: settle the constraints that would be expensive to change after install and
runtime ship. This should be a short decision gate at the start of Sprint 1, not
a full two-week implementation-free sprint.

Deliverables:

- Define trust tiers: built-in, local workspace pack, installed third-party
  pack, and future curated pack.
- Define security posture for install and run: validation is not a sandbox,
  packs are executable code, and secrets are only passed to components that
  declare them.
- Define version and update semantics: schema version, `astrid_version`
  compatibility, install records, pinned revisions, and rollback expectations.
- Define namespace policy for pack ids and component ids, including collision
  handling and whether stronger namespacing is required before public registry
  use.
- Define dependency policy: declarations are informational/diagnostic in v1;
  no automatic Python/npm/system provisioning.
- Define migration policy for built-in legacy resolver paths.

Explicitly out of scope:

- Implementing sandbox runtime.
- Implementing install/update.
- Migrating every built-in pack.

Exit criteria:

- The plan has crisp answers for trust, security, versioning, dependencies,
  namespace collisions, and migration.
- Later sprints do not need to guess how install or runtime should behave.

### Sprint 1: Pack Contract And Validation

Goal: establish the external pack contract before changing runtime behavior.

Deliverables:

- Decide that packs are installable Git-backed capability bundles.
- Decide that packs remain the top-level grouping and namespace layer.
- Write initial schemas for `pack.yaml`, `executor.yaml`, `orchestrator.yaml`,
  and `element.yaml`.
- Add `schema_version` to pack manifests and reject unknown schema versions.
- Add structured agent fields for purpose, normal entrypoints, "do not use
  for", required context, secrets, and dependencies.
- Define the runtime contract in docs: callable shape, argv/env behavior, output
  conventions, exit codes, and error wrapping.
- Replace or bypass the flat YAML parser on the validation path with a real YAML
  parser.
- Implement `python3 -m astrid packs validate <path>`.
- Implement minimal `python3 -m astrid packs new <id>` that generates a valid
  pack skeleton.
- Implement minimal `python3 -m astrid executors new <pack>.<slug>` and
  `python3 -m astrid orchestrators new <pack>.<slug>` scaffolds for external
  packs.
- Add one minimal external-style example pack under `examples/packs/minimal/`.
- Add `docs/creating-packs.md` and first-pass schema reference docs.
- Add tests for valid and invalid example packs.

Explicitly out of scope:

- Git install/update/uninstall.
- Installed pack discovery.
- Runtime execution from external packs.
- Rich scaffolding templates beyond minimal executor/orchestrator creation.
- Element scaffolding commands.
- Dependency installation.

Exit criteria:

- A builder can read the docs and understand the target layout.
- A valid example pack passes validation.
- `packs new <id>` produces a skeleton that passes validation.
- `executors new` and `orchestrators new` produce minimal component skeletons
  that pass validation inside that pack.
- Broken example packs fail with clear, file-specific errors.
- Existing built-in manifests still parse or are explicitly documented as
  legacy-compatible.

### Sprint 2: PackResolver, Deterministic Discovery, And Runtime Path

Goal: stop discovering product surface by accidental recursive scans and prove
that external-pack-shaped components resolve through the canonical runtime path
before any install UX ships.

Deliverables:

- Introduce and use `PackResolver` for built-in and external-style pack
  resources: component roots, docs, schemas, runtime files, examples, and
  assets.
- Teach discovery to read declared content roots from `pack.yaml`.
- Keep built-in pack lists stable while moving toward declared roots.
- Warn on plausible pack directories that lack a manifest.
- Add an opt-out rule for legitimate non-pack directories, such as `_core`,
  `__pycache__`, or `.no-pack`.
- Detect duplicate ids across all discovered packs.
- Collapse orchestrator resolution to the manifest-based path.
- Preserve current CLI and runner behavior for existing built-in orchestrators.
- Move, rename, or delete the legacy `builtin/hype.py` DSL fixture.
- Define whether the DSL decorator remains supported or becomes legacy.
- Add a small external-style pack fixture and prove one executor/orchestrator
  can run through the standard CLI without being installed yet.
- Prove the minimal Sprint 1 executor/orchestrator scaffolds use the canonical
  runtime path.
- Add tests for undeclared manifests, skipped directories, duplicate ids, and
  built-in list stability.
- Add tests proving the same id resolves the same way from all call sites.

Explicitly out of scope:

- Git install.
- Full installed-pack lifecycle.
- Full pack taxonomy migration.
- Rich component templates.

Exit criteria:

- Discovery is deterministic for built-in and local path-based packs.
- Fixture manifests do not become public tools unless declared.
- The user-facing executor, orchestrator, and element lists do not regress.
- There is one canonical runtime resolution path.
- `builtin.hype` no longer has two different public meanings.
- An external-style executor/orchestrator fixture can run through the standard
  CLI.

### Sprint 3: Local Pack Install, Trust UX, And Runnable Packs

Goal: let a local external pack become installed without opening the Git supply
chain surface yet, and ensure install immediately produces a usable pack rather
than a visible-but-unrunnable component listing.

Deliverables:

- Add installed-pack root, probably `~/.astrid/packs/`.
- Add `InstalledPackStore` for install roots, staging directories, active
  pointers, per-revision install records, locks, update, uninstall, and rollback
  metadata.
- Implement `packs install <local-path>`.
- Implement `packs install --dry-run <local-path>` with a trust summary.
- Implement `packs list`, `packs inspect`, `packs update`, and
  `packs uninstall`.
- Write an install record or lockfile with pack id, source path, installed
  revision marker, pack version, schema version, Astrid compatibility, and
  install time.
- Validate packs before completing installation.
- Use activation language: copy/clone, validate, then activate. Failed
  validation leaves no active pack.
- Include installed packs in executor, orchestrator, and element list/search/
  inspect commands.
- Reject or clearly report id collisions with built-in and installed packs.
- Add a basic `packs inspect <id> --agent` summary using structured manifest
  fields.
- Exercise an installed local pack through validate -> install -> inspect -> run
  in tests.

Explicitly out of scope:

- Git URL install.
- Automatic dependency provisioning.
- Pack registry or marketplace.

Exit criteria:

- A valid local external pack can be installed.
- Invalid packs are rejected before installation completes.
- Installed pack components appear in list/search/inspect output.
- Installed pack executors/orchestrators can run through the standard CLI.
- Uninstall removes the pack cleanly from discovery.
- Install summaries clearly show tools, executable entrypoints, secrets,
  dependencies, docs, and warnings.

### Sprint 4: Git Install, Pinning, And Update Safety

Goal: support Git-backed packs without making arbitrary branch tips silently
executable.

Deliverables:

- Implement `packs install <git-url-or-path>` for Git URLs.
- Resolve and record a concrete commit SHA for every Git install.
- Show a confirmation summary before activation unless `--yes` is passed.
- Revalidate before activation.
- Implement `packs update --dry-run` with manifest diff summary.
- Keep the previous installed revision and support rollback.
- Define private-repo behavior: use the user's existing Git credentials via the
  Git subprocess; do not manage GitHub tokens directly in v1.

Explicitly out of scope:

- Marketplace or curated registry.
- Signature verification.
- Automatic dependency provisioning.

Exit criteria:

- Git installs are pinned, inspectable, and reversible.
- Updates cannot silently swap executable code without validation and summary.
- The install record is sufficient to reproduce which pack revision was active.

### Sprint 5: Builder Scaffolding And Templates

Goal: make pack authoring easy and hard to get subtly wrong beyond the minimal
component scaffolds needed for Milestone 1.

Deliverables:

- Expand templates for packs, executors, orchestrators, and elements beyond the
  minimal Sprint 1 scaffolds.
- Add `elements new` and enrich `executors new` / `orchestrators new` with
  better docs, tests, examples, and option prompts.
- Extract a small plan-v2 builder for orchestrator plan templates.
- Ensure generated templates validate without manual edits except ids/names.
- Update authoring docs to point at scaffolded examples instead of historical
  built-in files.

Explicitly out of scope:

- Rich UI for pack authoring.
- Pack marketplace.
- Complex orchestrator generation beyond a minimal valid starting point.

Exit criteria:

- A builder can generate a minimal pack and pass `packs validate`.
- Template-generated orchestrators use the canonical runtime path.
- The canonical examples no longer require copying production pack internals.

### Sprint 6: Agent Index And Pack Legibility

Goal: make installed packs easy for agents and humans to understand.

Deliverables:

- Implement `packs agent-index`.
- Improve `inspect --json` output for pack components.
- Add guidance for writing pack-level `AGENTS.md`.
- Generate or assemble a compact summary from `pack.yaml`, component manifests,
  `STAGE.md`, and pack-level docs.
- Add docs for secrets, dependencies, and when to use orchestrators versus
  executors.

Explicitly out of scope:

- Automatic agent prompt injection into every harness.
- Dependency installation.
- Hosted registry.

Exit criteria:

- An agent can inspect installed packs and choose the right entrypoint.
- The index explains normal entrypoints, low-level building blocks, required
  secrets, and important constraints.
- Human docs and agent docs have clear separate roles.

### Sprint 7: Rich Example Pack And External Element Hardening

Goal: prove the system on a realistic media pack and fix the rough edges found
by using it.

Deliverables:

- Add a richer media example pack with at least one executor, one orchestrator,
  one element, one schema, and example inputs.
- Run the full validate -> install -> inspect -> agent-index -> run path on the
  example pack.
- Explicitly handle external element discovery, Remotion registry generation,
  compilation/type generation, and render-time asset resolution.
- Add regression tests for the full path.
- Tighten validation around secrets, dependency declarations, and docs
  references.
- Document migration guidance for existing internal packs.

Explicitly out of scope:

- Full migration of every built-in pack to a new taxonomy.
- Marketplace/index service.
- Sandboxed execution.

Exit criteria:

- The system works for a pack that resembles real user content, not only a
  minimal fixture.
- The docs can guide a builder from blank repo to runnable installed pack.
- The remaining limitations are explicit.

### Sprint 8: Legacy Migration

Goal: prevent a permanent two-world system where built-ins keep historical
rules while external packs follow stricter contracts. This sprint proves the
migration approach on one real pack; it is not the full portfolio migration.

Deliverables:

- Convert one real built-in pack fully to the external pack contract.
- Document compatibility gaps found during migration.
- Add deprecation warnings for legacy resolver paths.
- Decide whether remaining built-ins migrate immediately or through an alias/
  compatibility window.
- Update tests so the converted built-in pack exercises the same resolver and
  validation code as external packs.

Explicitly out of scope:

- Renaming every pack or changing public ids without aliases.
- Marketplace work.

Exit criteria:

- At least one real built-in pack proves the external contract is not only for
  fixtures.
- Legacy resolver behavior has a clear end state.

### Sprint 9: Pack Portfolio Classification And Migration

Goal: convert the existing Astrid pack inventory from historical grouping into
an intentional product taxonomy.

Classification categories:

- Core: required platform packs that ship with Astrid and are always available.
- Bundled installable: useful first-party packs that ship with Astrid but use
  the same installable-pack contract as user packs.
- Optional installable: packs that should live outside the core tree and be
  installed only when needed.
- Local-only scratch: project/user scratch packs that should not be presented as
  public product surface.
- Deprecated: packs kept temporarily with warnings, aliases, or migration notes.
- Removed: obsolete packs with no supported path forward.

Deliverables:

- Inventory every existing pack and component.
- Classify each pack using the categories above.
- Define the minimum core pack set.
- Convert all core and bundled installable packs to the new contract.
- Move optional installable packs to the installable-pack path or document their
  extraction path if moving them is too large for the sprint.
- Add deprecation warnings, aliases, or migration docs for renamed or retired
  public ids.
- Refresh capability index, skills installation docs, and authoring docs.
- Add tests proving core packs and bundled installable packs use the same
  resolver, validation, inspect, and runtime paths.

Explicitly out of scope:

- Hosted marketplace.
- Signature verification.
- Perfect migration of every experimental or local scratch component.

Exit criteria:

- Every existing pack has an explicit status: core, bundled installable,
  optional installable, local-only scratch, deprecated, or removed.
- There is no ambiguous "historical built-in but not really core" category left.
- Users and agents can tell which capabilities are always available and which
  must be installed.

### Optional Sprint 10: Sandboxed Pack Runtime

Goal: provide an opt-in security boundary for running user-installed packs.

Deliverables:

- Add a documented sandbox mode strategy, likely container-based.
- Define credential passing and blocked host access.
- Add a prototype `astrid --sandbox ...` or sibling shim.
- Run validation and at least one installed-pack command inside the sandbox.

Explicitly out of scope:

- Making sandbox mode the default.
- Hosted cloud execution.
- Perfect network allowlisting for every provider.

Exit criteria:

- Security-conscious users can run Astrid with only the workspace and explicit
  credentials exposed.
- The docs clearly explain what sandbox mode does and does not protect.

## Sequencing Rationale

The critical dependency chain is:

```text
architecture decisions -> contract -> validation -> deterministic discovery ->
runtime resolver -> local install and run -> Git install -> scaffolding ->
agent index -> realistic examples -> migration proof -> portfolio
rationalization -> sandbox
```

Key reasons:

- Validation must come before install, otherwise Astrid can install ambiguous or
  malformed repositories.
- Trust, versioning, and dependency policy must come before install, otherwise
  unsafe defaults harden into product behavior.
- Declared discovery must come before runtime execution, otherwise stray
  manifests can become runnable product surface.
- Runtime resolution must come before install, otherwise Astrid creates a pack
  surface that can be listed and inspected but not actually used.
- Local install should precede Git install so the activation and discovery model
  can stabilize before handling authentication, pinning, and updates.
- Git install should come after one local installed pack can run, otherwise
  supply-chain mechanics are tested before the installed artifact is usable.
- Runtime unification must come before full component scaffolding, otherwise
  templates may teach the wrong authoring pattern.
- Scaffolding must come before broad docs polish, otherwise docs will describe
  manual copy-paste rather than the intended builder flow.
- Agent index should come after manifests and inspect output stabilize.
- Sandbox mode is valuable, but it should wrap a coherent pack system rather
  than compensate for an unclear one.

## Initial Architecture Decisions

These decisions should be treated as the starting point for Sprint 0. Sprint 0
can revise them if implementation research exposes a serious flaw, but later
sprints should not proceed with these questions still open.

### V1 Threat Model

Installed packs are trusted executable code.

- Validation proves structure and declared references, not safety.
- `packs install` for local paths and Git URLs should show a trust summary
  before activation unless `--yes` is passed.
- The trust summary should include source, resolved revision or source path,
  pack id, component inventory, declared runtime entrypoints, declared secrets,
  dependency declarations, docs paths, and warnings.
- Pack subprocesses inherit the normal Astrid process environment in v1.
- Astrid should only intentionally surface and summarize secrets declared by the
  pack, but declaration is not a sandbox or permission boundary.
- Users should treat third-party Git packs like scripts they chose to run.

Reasoning: v1 can make installed code explicit and auditable, but it should not
claim isolation until sandbox mode exists.

### Install Mode

Installed packs should be copied or cloned into Astrid's managed install root,
not referenced in place by default.

- Local path installs copy the pack into `~/.astrid/packs/<pack-id>/`.
- Git installs clone into the same managed root and pin a concrete commit SHA.
- Local path copies respect the source repository's `.gitignore`.
- Referencing a source directory in place is a future developer mode, not the v1
  default.

Reasoning: an installed pack should not change just because a builder edits a
working tree. Activation should be explicit, repeatable, and reversible. Using
`.gitignore` keeps local caches, media outputs, virtualenvs, and other non-source
artifacts out of installed packs without introducing a second ignore language in
v1.

### Local Updates

`packs update <id>` for a local-path install should recopy from the original
source path recorded at install time.

- If the original path no longer exists, update fails with a clear message.
- Update should support dry-run before replacing the active copy.
- Update should validate the recopied pack before activation.
- The previous active copy should remain available for rollback once rollback
  exists.

Reasoning: local installs are snapshots, but builders still need an explicit way
to refresh from their working tree. Recopy-on-update preserves snapshot
semantics while avoiding silent mutation.

### Pack Ids And Namespacing

Pack ids should remain simple strings in v1, with strict validation and
collision rejection.

- Valid pack ids should be lowercase ASCII identifiers such as `my_project`.
- Executor and orchestrator ids remain `<pack>.<slug>`.
- Installed packs cannot collide with built-in or already-installed pack ids.
- Git URL, requested ref, resolved commit SHA, and local source path are source
  identity metadata in the install record, not the CLI id.
- Public registry or publisher namespacing can be added later as metadata
  without changing the local runtime id scheme.

Reasoning: stronger public namespacing is useful later, but adding it before a
registry exists would add ceremony without solving a current local-install
problem.

### Element Ids

Installed external element ids should remain bare within their element kind for
v1, but collisions are rejected.

- Timeline references keep the existing `{kind, id}` shape.
- Installed element manifests also carry `pack_id`.
- An installed element cannot collide with a built-in element or another
  installed element of the same kind.
- Pack-qualified element references or aliases can be added later if a public
  ecosystem needs multiple same-named elements active at once.

Reasoning: this preserves current timeline compatibility while avoiding implicit
override behavior. The cost is that users cannot install two packs that provide
the same element id until a future aliasing model exists.

### Overrides

Installed packs should not override built-in executors, orchestrators, or
elements in v1.

- Executor and orchestrator collisions are rejected.
- Installed element collisions are rejected.
- The existing explicit project-local element override layer can remain special
  because it is an intentional editing workflow, not a third-party install
  behavior.

Reasoning: implicit override semantics create confusing and potentially unsafe
tool selection. Overrides should require an explicit project-local action.

### Activation Semantics

A pack is active only after Astrid has:

1. Acquired an install/update lock for the target pack id.
2. Copied or cloned it into a staging directory under the managed install root.
3. Parsed `pack.yaml` with the supported schema version.
4. Validated all declared component manifests and referenced files.
5. Checked id collisions against built-in and installed packs.
6. Written the staged install record.
7. Atomically moved the staging directory into the revision store.
8. Atomically updated the active pointer for the pack id.
9. Refreshed discovery so list/search/inspect/run all see the same state.

Failed validation leaves no active pack. A partially copied or cloned pack is
staging data, not an installed pack.

The managed install root should separate revisions from the active pointer, for
example:

```text
~/.astrid/packs/
  my_project/
    active -> revisions/<revision-id>/
    revisions/
      <revision-id>/
        pack.yaml
        .astrid/install.json
```

Read commands use the active pointer. Update and uninstall commands take the
install lock. If another process is already running a component from the old
active path, v1 does not have to interrupt it; the new active revision applies
to subsequent discovery and runs.

### Install Record

Each installed pack should have a machine-readable install record containing at
least:

- Pack id, name, pack version, schema version, and Astrid compatibility range.
- Source type: local path or Git.
- Source path or Git URL.
- For Git installs: requested ref and resolved commit SHA.
- For local installs: original source path and copied content digest where
  practical.
- Install time and last validation time.
- Trust tier.
- Manifest digest.
- Generated component inventory.
- Declared secrets and dependencies summary.
- Previous active revision pointer when update/rollback exists.

The authoritative install record for each revision should live at:

```text
~/.astrid/packs/<pack-id>/revisions/<revision-id>/.astrid/install.json
```

A central index may be generated later for faster list/search, but it should be
a cache rebuilt from per-pack install records rather than the only source of
truth.

Reasoning: inspect, update, rollback, doctor, and agent-index all need the same
source of truth for what is installed and why it is trusted enough to run.

### External `STAGE.md`

`STAGE.md` should remain mandatory for public external executors and
orchestrators in v1.

- The structured manifest is authoritative for machine behavior.
- `STAGE.md` is the human and agent operational guide.
- Elements may rely on manifest metadata and component source unless they need
  non-obvious usage instructions.

Reasoning: the current Astrid operating model already expects stages to have
nearby operational instructions. Removing that requirement before agent-index
and inspect output are mature would make external tools harder to use safely.

### Validation And Sandboxing

CLI wording should state plainly that validation is not sandboxing.

- Validation means the pack is well-formed, inspectable, and points at declared
  files.
- Running an installed pack executes code from that pack.
- Secrets are passed only to components that declare them, but declaration is
  not a security boundary.
- Users should install third-party packs only from sources they trust until
  sandbox mode exists.

Reasoning: install UX should not imply a safety guarantee that validation cannot
provide.

### Validation Strictness

`packs validate` should be strict by default about correctness errors and
non-fatal about warnings.

- Errors fail validation and block install.
- Warnings are shown but do not fail validation by default.
- `--warnings-as-errors` should be available for CI and curated-pack checks.
- A separate `--strict` mode is not needed in v1 unless a concrete second tier
  of checks emerges.

Reasoning: one normal validation mode keeps builder UX simple. Warnings still
leave room for advisory checks such as docs quality, optional examples, or future
best practices.

### Runtime Boundary

External executor and orchestrator `run.py` files should execute through the
same runner path as existing folder-backed tools, using the manifest runtime
adapter rather than importing arbitrary modules directly from discovery code.

- The manifest declares the runtime adapter, entrypoint file, and callable or
  command shape.
- Runtime execution receives argv/env according to the documented adapter
  contract.
- Validation checks runtime paths statically. Any import or execution-based smoke
  test is a separate trusted action, not the default validation path.

Reasoning: external packs should not introduce a second execution model. The
runner path is where output conventions, errors, and future sandbox wrapping
belong.

### Schema Technology

The published pack and component contracts should be JSON Schema documents,
validated with `jsonschema`.

- Author-facing manifests remain YAML or JSON.
- YAML should be parsed with PyYAML `safe_load`; PyYAML should become an explicit
  dependency instead of relying on indirect installs.
- JSON Schema is the published contract for docs, validation, editor tooling,
  and cross-language consumers.
- Python dataclasses or typed helpers may wrap validated data internally, but
  they should not replace JSON Schema as the external contract.

Reasoning: Astrid already depends on `jsonschema`, and JSON Schema gives a
language-neutral contract for agents, docs, editors, and future non-Python pack
tooling.

### Examples And Test Assets

Example packs may include small fixtures and media assets when they are needed
to prove behavior.

- Keep example assets small and source-controlled only when they are genuinely
  part of the example.
- Generated outputs, rendered videos, caches, model weights, virtualenvs, and
  downloaded media stay out of packs.
- Larger examples should fetch or generate their heavy inputs during the run, or
  document where the user should place them.
- Validation should warn when example assets look unusually large, but size
  limits should not block v1 unless they are causing real repo bloat.

Reasoning: media packs need realistic examples, but installed packs should not
become a dumping ground for generated outputs or heavyweight local state.

### Element V1 Scope

External element support should ship all the way through in v1, not as
validate-only metadata.

- External element manifests validate.
- Installed external elements appear in list/search/inspect output.
- Registry generation and type generation include installed external elements.
- A rendered timeline can use an installed external element.
- Element failures have a clear debug path through validation, registry
  generation, type generation, and render.

Reasoning: elements are part of the core pack promise. They can remain later in
the roadmap because they are harder than executors/orchestrators, but the v1
target should be full working support rather than a partial placeholder.

## Abstraction Levels

The right v1 abstraction level is enough structure to make packs reproducible,
inspectable, and runnable without turning Astrid into a package manager,
marketplace, or policy engine.

| Area | Right v1 level | Avoid in v1 |
| --- | --- | --- |
| `PackResolver` | A read-only concrete resource locator that resolves pack roots, component roots, docs, schemas, runtime files, examples, and assets from known pack roots. It should be the shared path used by validation, discovery, inspect, runtime, and agent-index. | A general plugin framework, dependency solver, trust engine, registry client, install-state manager, or runtime supervisor. |
| `InstalledPackStore` | A small lifecycle/state boundary that owns install roots, staging directories, active pointers, per-revision install records, locks, update, uninstall, and rollback metadata. | A package manager, central database, dependency installer, marketplace client, or security policy engine. |
| Trust tiers | A small enum or string field used for display and warnings: built-in, local, Git, future curated. | A full trust-policy language, permission graph, signing system, or sandbox substitute. |
| Generated component inventory | A generated snapshot for install records, inspect output, summaries, and tests. Source of truth remains `pack.yaml` plus component manifests. | A manually authored `provides` file or a second registry format builders must maintain. |
| Install records | One JSON file per installed revision under `.astrid/install.json`, written before activation and treated as authoritative for that revision. | A central database or global package lock unless performance needs force it later. |
| Schemas and Python types | JSON Schema is the external contract. Python dataclasses or helpers may wrap already-validated data for internal ergonomics. | A parallel Pydantic contract hierarchy that can drift from published schemas. |
| Agent index | Deterministic assembly from structured manifest fields, component metadata, docs paths, and concise stage summaries. | LLM-generated summaries, heuristic doc digestion, or prompt-injection machinery before structured fields prove insufficient. |
| Runtime adapters | One supported external adapter first: `python-cli`. The adapter maps manifest data to the existing runner path and documented argv/env behavior. | A generic adapter marketplace or many runtime types before one external executor/orchestrator path works end to end. |
| External elements | A focused Remotion bridge: validate manifests, include installed element roots in registry/typegen, and prove render use. | A generic frontend asset pipeline, theme marketplace, or element override policy beyond the explicit local override layer. |
| Dependency declarations | Informational metadata surfaced by validate, inspect, install summaries, and doctor checks. | Automatic Python/npm/system provisioning before Astrid has an explicit environment model. |
| Local install/update | Snapshot copy on install, explicit recopy on update, validate before activation, rollback once revision retention exists. | Live references to mutable working trees as the default install mode. |

The abstraction test for v1: if removing the abstraction would reintroduce
duplicate discovery/runtime behavior, keep it. If the abstraction mainly exists
to support a future marketplace, hosted registry, sandbox, or package manager,
defer it.

## Existing Ticket Mapping

Architecture decisions:

- `01KRF1AYT8ANAD47QB1M535SH4`: Keep packs as a real abstraction layer.
- `01KRF156A3M3WTDQVQGX797JAM`: Resolve in favor of installable plugins.
- `01KRF17FVN1C24HQ8TFJJNPW0G`: Define taxonomy around installable capability
  bundles and built-in platform packs.

Pack manifests and discovery:

- `01KRF15VTT59Q0P8N6R2619TRG`: Expand `pack.yaml` into a real contract.
- `01KRF16M8EEZF7475ATCG7GSJ6`: Replace the custom YAML parser.
- `01KRF16MJWRHGWEQZ2A8NTSFSY`: Replace loose `rglob` with declared roots.
- `01KRF17GHJN770ZDRYEKT9R3V0`: Warn on likely pack directories with missing
  manifests.

Orchestrator authoring and runtime:

- `01KRF15VFMCN7SYZ9K4NANXTAT`: Unify resolver behavior.
- `01KRF17G6NARVX8DYSKQCBY8NS`: Move, rename, or delete the legacy `hype.py`
  fixture.
- `01KRF16MX3VWY2Q993VHHAKNTG`: Extract a small shared plan builder.
- `01KRF1AZ4G2V8PKH3DX9FK81D2`: Add scaffolding and authoring docs.

Independent security work:

- `01KREY8RVFADZQK9X3GBBDXD03`: Optional sandboxed runtime. This complements
  installable packs but does not block the pack contract.

## Recommended First Epic

Start with a single epic called:

```text
Local executor/orchestrator packs end to end
```

The first implementation slice should be narrow, but the first releasable
milestone should be vertical. Do the infrastructure in order, but do not present
it as complete until a local pack can be created, validated, installed,
inspected, run, and uninstalled.

Initial implementation steps:

1. Add schemas.
2. Add `packs validate <path>`.
3. Add `packs new <id>`.
4. Add a minimal external example pack.
5. Replace the flat YAML parser on the validation path.
6. Make validation errors good enough that a builder can fix their repo without
   reading Astrid internals.

Then continue through `PackResolver`, deterministic discovery, local install,
and runnable installed executors/orchestrators before calling the first
milestone done. Do not start with Git install. Validation and local runnable
install are the foundation; Git should only install packs whose local contract
already works.
