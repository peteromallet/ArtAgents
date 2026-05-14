# Sprint 9: Pack Portfolio Classification And Migration

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: convert Astrid's existing pack inventory from historical grouping into an
intentional product taxonomy.

Scope:

- Inventory every existing pack and component.
- Classify each pack as core, bundled installable, optional installable,
  local-only scratch, deprecated, or removed.
- Define the minimum core pack set.
- Convert all core and bundled installable packs to the new contract.
- Move optional installable packs to the installable-pack path, or document the
  extraction path if moving them is too large for this sprint.
- Add deprecation warnings, aliases, or migration docs for renamed/retired ids.
- Refresh capability index, skills installation docs, and authoring docs.
- Add tests proving core and bundled installable packs use the same resolver,
  validation, inspect, and runtime paths.

Out of scope:

- Hosted marketplace.
- Signature verification.
- Perfect migration of every experimental/local scratch component.

Success criteria:

- Every existing pack has an explicit status.
- There is no ambiguous "historical built-in but not really core" category left.
- Users and agents can tell which capabilities are always available and which
  must be installed.
