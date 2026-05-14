# Sprint 7: Rich Example Pack And External Element Hardening

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: prove the system on a realistic media pack and make external elements work
end to end.

Scope:

- Add a richer media example pack with at least one executor, orchestrator,
  element, schema, and example input.
- Run validate -> install -> inspect -> agent-index -> run on the example pack.
- Validate external element manifests.
- Include installed external elements in registry generation and typegen.
- Prove a rendered timeline can use an installed external element.
- Add regression tests and clear failure/debug paths for validation, registry,
  typegen, and render.
- Tighten validation around secrets, dependency declarations, and docs.

Out of scope:

- Full migration of every built-in pack.
- Marketplace.
- Sandbox execution.

Success criteria:

- The example resembles real user content, not only a minimal fixture.
- External elements work through render, not just validate/list/inspect.
