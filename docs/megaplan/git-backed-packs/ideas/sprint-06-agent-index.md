# Sprint 6: Agent Index And Pack Legibility

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: make installed packs easy for agents and humans to understand.

Scope:

- Implement `packs agent-index`.
- Improve `inspect --json` output for packs and pack components.
- Add guidance for writing pack-level `AGENTS.md`.
- Generate deterministic summaries from structured manifest fields, component
  metadata, docs paths, and bounded stage summaries.
- Keep Markdown supplemental; do not use LLM summarization or heuristic full-doc
  digestion in v1.
- Document secrets, dependencies, and when to use orchestrators vs executors.

Out of scope:

- Automatic prompt injection into every harness.
- Dependency installation.
- Hosted registry.

Success criteria:

- An agent can inspect installed packs and choose the right entrypoint.
- The index identifies normal entrypoints, low-level building blocks, required
  secrets, dependencies, constraints, and examples.
