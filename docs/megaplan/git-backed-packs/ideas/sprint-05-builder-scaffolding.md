# Sprint 5: Builder Scaffolding And Templates

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: make pack authoring easy and hard to get subtly wrong beyond the minimal
Sprint 1 scaffolds.

Scope:

- Expand pack, executor, orchestrator, and element templates.
- Add `elements new`.
- Enrich `executors new` and `orchestrators new` with better docs, tests,
  examples, and option handling.
- Extract a small shared plan-v2 builder for orchestrator templates if the
  existing copy-paste remains.
- Update authoring docs to point at scaffolded examples instead of production
  internals.

Out of scope:

- Rich UI for authoring.
- Marketplace.
- Complex orchestrator generation beyond a minimal valid starting point.

Success criteria:

- Generated templates validate.
- Template-generated orchestrators use the canonical runtime path.
- Builders do not need to copy historical built-in packs to get started.
