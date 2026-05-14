# Sprint 1: Pack Contract And Validation

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: establish the external pack contract before changing runtime behavior.

Scope:

- Add JSON Schema contracts for `pack.yaml`, `executor.yaml`,
  `orchestrator.yaml`, and `element.yaml`.
- Add `schema_version` support and reject unknown schema versions.
- Parse author-facing YAML with PyYAML `safe_load`; do not use the flat parser
  for user-authored pack manifests.
- Implement `python3 -m astrid packs validate <path>` with static validation.
- Implement minimal `packs new <id>`, `executors new <pack>.<slug>`, and
  `orchestrators new <pack>.<slug>` scaffolds that validate.
- Add `examples/packs/minimal/` with one executor and one orchestrator.
- Add first-pass `docs/creating-packs.md`.
- Add focused tests for valid/invalid examples and scaffolds.

Out of scope:

- Git install.
- Installed-pack discovery.
- Runtime execution from installed packs.
- Element scaffolding.
- Dependency provisioning.

Success criteria:

- A builder can create a minimal pack and validate it.
- Broken pack examples fail with clear file-specific messages.
- Validation does not import or execute arbitrary pack code by default.
