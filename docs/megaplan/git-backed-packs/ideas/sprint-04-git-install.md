# Sprint 4: Git Install, Pinning, And Update Safety

Use `docs/git-backed-packs-plan.md` as the source of truth.

Goal: support Git-backed packs without silently executing arbitrary branch tips.

Scope:

- Implement `packs install <git-url-or-path>` for Git URLs.
- Resolve and record a concrete commit SHA for every Git install.
- Show trust summary before activation unless `--yes` is passed.
- Revalidate before activation.
- Implement `packs update --dry-run` with manifest/component diff summary.
- Keep the previous active revision and support rollback.
- Use the user's existing Git credentials through the Git subprocess; do not
  manage GitHub tokens in v1.

Out of scope:

- Marketplace/curated registry.
- Signature verification.
- Dependency provisioning.

Success criteria:

- Git installs are pinned, inspectable, reversible, and validated before
  activation.
- Updates cannot silently swap executable code.
