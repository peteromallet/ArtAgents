# Sprint 2: PackResolver, Deterministic Discovery, And Runtime Path

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: replace accidental recursive discovery and split runtime resolution with a
single manifest-based path.

Scope:

- Introduce read-only `PackResolver` for pack roots, component roots, docs,
  schemas, runtime files, examples, and assets.
- Teach discovery to read declared content roots from `pack.yaml`.
- Preserve existing built-in list/search/inspect behavior while moving toward
  declared roots.
- Warn on likely pack directories with missing manifests and support explicit
  opt-outs such as `.no-pack`.
- Detect duplicate pack/component ids.
- Collapse orchestrator resolution to the manifest-based path.
- Resolve the legacy `builtin/hype.py` vs `builtin/hype/` split.
- Prove one external-style executor/orchestrator fixture runs through the
  standard CLI without being installed yet.
- Prove Sprint 1 scaffolds use the canonical runtime path.

Out of scope:

- Git install.
- Full installed-pack lifecycle.
- Rich component templates.

Success criteria:

- There is one canonical runtime resolution path.
- Stray manifests are not accidentally exposed.
- Built-in user-facing lists do not regress.
