# Sprint 3: Local Pack Install, Trust UX, And Runnable Packs

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: install a local external pack as a snapshot and make it runnable.

Scope:

- Add `InstalledPackStore` for install roots, staging directories, active
  pointers, per-revision install records, locks, update, uninstall, and rollback
  metadata.
- Implement `packs install <local-path>` and `packs install --dry-run
  <local-path>`.
- Respect the source repository's `.gitignore` for local copies.
- Validate before activation and leave no active pack on validation failure.
- Write per-revision `.astrid/install.json`.
- Implement `packs list`, `packs inspect`, `packs inspect --agent`,
  `packs update`, and `packs uninstall` for local installs.
- Include installed packs in list/search/inspect/run paths.
- Add validate -> install -> inspect -> run -> uninstall tests.

Out of scope:

- Git URL install.
- Automatic dependency provisioning.
- Marketplace/registry.

Success criteria:

- A local external pack can be installed, inspected, run, updated, and
  uninstalled.
- Install summaries show tools, entrypoints, declared secrets, dependencies,
  docs, source, and warnings.
