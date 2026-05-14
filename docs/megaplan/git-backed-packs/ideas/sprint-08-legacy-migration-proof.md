# Sprint 8: Legacy Migration Proof

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: prove the external pack contract on one real built-in pack before
rationalizing the whole portfolio.

Scope:

- Select one representative built-in pack.
- Convert it fully to the external pack contract.
- Document compatibility gaps found during migration.
- Add deprecation warnings for legacy resolver paths.
- Decide whether the remaining built-ins migrate immediately or through an
  alias/compatibility window.
- Update tests so the converted built-in pack uses the same resolver,
  validation, inspect, and runtime code as external packs.

Out of scope:

- Renaming every pack without aliases.
- Migrating every existing pack.
- Marketplace.

Success criteria:

- At least one real built-in proves the contract is not fixture-only.
- Legacy resolver behavior has a clear end state.
