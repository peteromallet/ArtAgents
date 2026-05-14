# Sprint 0: Architecture Decision Gate

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: confirm or revise the initial architecture decisions before implementation
starts. This sprint should end with a crisp decision record, not broad code
changes.

Scope:

- Verify the v1 threat model for installed packs as trusted executable code.
- Verify install mode, local update behavior, activation semantics, install
  record shape, and `InstalledPackStore`/`PackResolver` boundaries.
- Verify simple pack ids plus source identity metadata.
- Verify element id collision policy.
- Verify validation/static-smoke-test boundary.
- Verify dependency policy remains declaration-only.
- Update `docs/git-backed-packs-plan.md` if any decision changes.

Out of scope:

- Implementing pack install.
- Implementing runtime execution.
- Migrating built-in packs.

Success criteria:

- Later sprints do not need to guess trust, namespace, activation, runtime, or
  validation behavior.
- Any changed decisions are recorded in `docs/git-backed-packs-plan.md`.
