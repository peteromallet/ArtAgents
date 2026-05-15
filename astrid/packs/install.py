"""``packs install`` / ``packs uninstall`` / ``packs update`` commands.

``packs install <path-or-git-url>`` installs a pack from a local directory
or a Git URL.  Git installs are pinned to a concrete commit SHA so that
updates never silently swap executable code.

``packs install --dry-run <path-or-git-url>`` prints a trust summary
without mutating any state.

``packs update <pack_id>`` refreshes an installed pack from its source.

``packs uninstall <pack_id>`` removes an installed pack.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import indent
from typing import Optional

import yaml

from astrid.core.pack import pack_manifest_path
from astrid.core.pack_store import (
    InstallRecord,
    InstalledPackStore,
    _revision_timestamp,
    _utc_now_iso,
)
from astrid.packs.gitignore import gitignore_filter
from astrid.packs.validate import extract_trust_summary, validate_pack

# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------


def _format_trust_summary(
    summary: dict,
    *,
    git_url: str = "",
    commit_sha: str = "",
    astrid_version: str = "",
    trust_tier: str = "",
) -> str:
    """Format an extract_trust_summary dict for display.

    When *git_url* is non-empty the ``Source`` line shows the durable Git
    URL instead of ``summary['source_path']`` (which holds a temp path
    during Git installs).  *commit_sha* is displayed as the pinned
    revision (first 8 chars).  *astrid_version* and *trust_tier* are shown
    when non-empty.
    """
    lines: list[str] = []
    lines.append("━━━ Trust Summary ━━━")
    lines.append(f"  Pack ID:       {summary.get('pack_id', '?')}")
    lines.append(f"  Name:          {summary.get('name', '?')}")
    lines.append(f"  Version:       {summary.get('version', '?')}")
    lines.append(f"  Schema:        {summary.get('schema_version', '?')}")

    # For Git installs, show the durable git_url (not the temp checkout path)
    source_display = git_url if git_url else summary.get("source_path", "?")
    lines.append(f"  Source:        {source_display}")

    if commit_sha:
        lines.append(f"  Pinned Commit: {commit_sha[:8]}")

    if astrid_version:
        lines.append(f"  Astrid Ver:    {astrid_version}")

    if trust_tier:
        lines.append(f"  Trust Tier:    {trust_tier}")

    # Component counts
    counts = summary.get("component_counts", {})
    if counts:
        parts = []
        for k in ("executors", "orchestrators", "elements"):
            if counts.get(k, 0):
                parts.append(f"{counts[k]} {k}")
        if parts:
            lines.append(f"  Components:    {', '.join(parts)}")
        else:
            lines.append("  Components:    (none)")
    else:
        lines.append("  Components:    (none)")

    # Entrypoints
    entrypoints = summary.get("entrypoints", [])
    if entrypoints:
        lines.append(f"  Entrypoints:   {', '.join(entrypoints)}")

    # Declared secrets
    secrets = summary.get("declared_secrets", [])
    if secrets:
        lines.append(f"  Secrets:       {', '.join(secrets)}")

    # Dependencies
    deps = summary.get("dependencies", [])
    if deps:
        lines.append(f"  Dependencies:  {', '.join(deps)}")

    # Docs
    docs = summary.get("docs", {})
    if docs:
        doc_parts = [f"{k}={v}" for k, v in docs.items() if v]
        if doc_parts:
            lines.append(f"  Docs:          {', '.join(doc_parts)}")

    # Warnings
    warnings = summary.get("warnings", [])
    if warnings:
        lines.append("  ⚠ Warnings:")
        for w in warnings:
            lines.append(f"    • {w}")

    return "\n".join(lines)


def _confirm(prompt: str, default_yes: bool = False) -> bool:
    """Ask the user for confirmation."""
    if default_yes:
        prompt += " [Y/n] "
    else:
        prompt += " [y/N] "
    try:
        response = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(1)
    if default_yes:
        return response != "n"
    return response in ("y", "yes")


# ---------------------------------------------------------------------------
# Core install logic
# ---------------------------------------------------------------------------


def install_pack(
    source_path: str | Path,
    store: InstalledPackStore | None = None,
    *,
    dry_run: bool = False,
    skip_confirm: bool = False,
    force: bool = False,
    git_url: str = "",
    commit_sha: str = "",
    requested_ref: str = "",
    source_type: str = "local",
    skip_name_check: bool = False,
) -> int:
    """Install a pack from a local directory or Git URL.

    Args:
        source_path: Path to the pack source directory, or a Git URL
            (``https://...``, ``git@...``, ``ssh://...``, ``git://...``).
        store: The ``InstalledPackStore`` to use.  Defaults to a new one.
        dry_run: If ``True``, print the trust summary and return 0 without
            mutating state.
        skip_confirm: If ``True``, skip the confirmation prompt.
        force: If ``True``, overwrite an existing install (old revision is
            renamed to ``<pack_id>.<timestamp>``).
        git_url: Durable Git URL (set by the Git branch).
        commit_sha: Pinned commit SHA (set by the Git branch).
        requested_ref: Branch/tag requested at install time (set by the Git
            branch).
        source_type: ``"local"`` or ``"git"``.
        skip_name_check: If ``True``, skip the directory-name-matches-pack-id
            check (used when the source has already been staged).

    Returns:
        Exit code (0 on success).
    """
    if store is None:
        store = InstalledPackStore()

    # ── Git URL detection MUST happen BEFORE Path().resolve() ──────────
    source_str = str(source_path)
    is_git = _is_git_url(source_str)

    if is_git:
        return _install_from_git(
            source_str,
            store,
            dry_run=dry_run,
            skip_confirm=skip_confirm,
            force=force,
        )

    source = Path(source_path).resolve()

    # ------------------------------------------------------------------
    # 1. Resolve the pack manifest
    # ------------------------------------------------------------------
    manifest_path = pack_manifest_path(source)
    if manifest_path is None:
        print(
            f"install: no pack manifest found in {source} "
            f"(expected pack.yaml, pack.yml, or pack.json)",
            file=sys.stderr,
        )
        return 2

    # ------------------------------------------------------------------
    # 2. Parse manifest with yaml.safe_load directly (NOT load_pack_manifest)
    # ------------------------------------------------------------------
    try:
        if manifest_path.suffix == ".json":
            import json as _json

            raw = _json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"install: failed to parse pack manifest: {e}", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print(
            "install: pack manifest is not a mapping", file=sys.stderr
        )
        return 2

    pack_id = raw.get("id")
    if not isinstance(pack_id, str) or not pack_id:
        print(
            "install: pack manifest missing required 'id' field",
            file=sys.stderr,
        )
        return 2

    # ------------------------------------------------------------------
    # 3. Source directory name must match pack id (PackResolver invariant)
    # ------------------------------------------------------------------
    if not skip_name_check and source.name != pack_id:
        print(
            f"install: source directory name {source.name!r} must match "
            f"pack id {pack_id!r} declared in pack manifest.",
            file=sys.stderr,
        )
        return 2

    # ------------------------------------------------------------------
    # 4. Check collision
    # ------------------------------------------------------------------
    existing = store.get_active(pack_id)
    if existing is not None and not force:
        print(
            f"install: pack {pack_id!r} is already installed.\n"
            f"  Installed at: {existing.installed_at}\n"
            f"  Source:       {existing.source_path}\n"
            f"  Use --force to overwrite (old revision will be preserved).",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # 5. Extract trust summary
    # ------------------------------------------------------------------
    try:
        trust_summary = extract_trust_summary(source)
    except Exception as e:
        print(f"install: cannot extract trust summary: {e}", file=sys.stderr)
        return 2

    # ------------------------------------------------------------------
    # 6. Dry-run: print trust summary and exit
    # ------------------------------------------------------------------
    if dry_run:
        print(
            _format_trust_summary(
                trust_summary,
                astrid_version=str(raw.get("astrid_version", "")),
                trust_tier="local",
            )
        )
        return 0

    # ------------------------------------------------------------------
    # 7. Validate source pack
    # ------------------------------------------------------------------
    errors, warnings = validate_pack(source)
    if warnings:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)

    if errors:
        print(
            f"install: source pack validation failed with {len(errors)} error(s):",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        print(
            "install: refusing to install an invalid pack.",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # 8. Confirmation
    # ------------------------------------------------------------------
    if not skip_confirm:
        print(
            _format_trust_summary(
                trust_summary,
                astrid_version=str(raw.get("astrid_version", "")),
                trust_tier="local",
            )
        )
        print()
        action = "overwrite" if existing else "install"
        if not _confirm(f"Proceed with {action}?"):
            print("Cancelled.", file=sys.stderr)
            return 1

    # ------------------------------------------------------------------
    # 9. Acquire lock
    # ------------------------------------------------------------------
    lock = store._acquire_lock(pack_id)

    try:
        with lock:
            return _do_install(
                source, pack_id, trust_summary, store, force, existing,
                manifest_raw=raw,
            )
    except Exception:
        # Ensure no broken state — clean up staging if it exists
        staging = store.staging_path_for(pack_id)
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _install_from_git(
    git_url: str,
    store: InstalledPackStore,
    *,
    dry_run: bool = False,
    skip_confirm: bool = False,
    force: bool = False,
) -> int:
    """Install a pack from a Git URL (called by :func:`install_pack`).

    Clones the repository to a temporary directory, resolves the commit
    SHA and requested ref, auto-detects the pack root, and delegates to
    :func:`_do_install`.  Temporary directories are cleaned up in a
    ``try``/``finally`` block on every exit path.
    """
    _check_git_available()

    checkout_path: str | None = None
    pack_root_copy: str | None = None

    try:
        # 1. Clone to temp (shallow) and get commit SHA
        checkout_path, commit_sha = _clone_git_pack(git_url)

        # 2. Resolve the requested ref (branch/tag) for the record
        try:
            requested_ref = _resolve_git_ref(git_url)
        except Exception:
            requested_ref = "HEAD"

        # 3. Auto-detect pack root inside the checkout
        pack_root = _find_pack_root_in_checkout(checkout_path)

        # 4. Parse manifest to extract pack_id
        manifest_path = pack_manifest_path(pack_root)
        if manifest_path is None:
            print(
                f"install: no pack manifest found in {pack_root} "
                f"(expected pack.yaml, pack.yml, or pack.json)",
                file=sys.stderr,
            )
            return 2

        try:
            if manifest_path.suffix == ".json":
                import json as _json

                raw = _json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"install: failed to parse pack manifest: {e}", file=sys.stderr)
            return 2

        if not isinstance(raw, dict):
            print("install: pack manifest is not a mapping", file=sys.stderr)
            return 2

        pack_id = raw.get("id")
        if not isinstance(pack_id, str) or not pack_id:
            print(
                "install: pack manifest missing required 'id' field",
                file=sys.stderr,
            )
            return 2

        # 5. Extract trust summary from the pack root
        try:
            trust_summary = extract_trust_summary(pack_root)
        except Exception as e:
            print(f"install: cannot extract trust summary: {e}", file=sys.stderr)
            return 2

        # 6. Dry-run: print trust summary with Git metadata and exit
        if dry_run:
            print(
                _format_trust_summary(
                    trust_summary,
                    git_url=git_url,
                    commit_sha=commit_sha,
                    astrid_version=str(raw.get("astrid_version", "")),
                    trust_tier="git",
                )
            )
            return 0

        # 7. Check collision
        existing = store.get_active(pack_id)
        if existing is not None and not force:
            print(
                f"install: pack {pack_id!r} is already installed.\n"
                f"  Installed at: {existing.installed_at}\n"
                f"  Source:       {existing.source_path}\n"
                f"  Use --force to overwrite (old revision will be preserved).",
                file=sys.stderr,
            )
            return 1

        # 8. Copy pack root to temp dir named after pack_id so that
        #    ``source.name == pack_id`` holds (PackResolver invariant).
        pack_root_copy = tempfile.mkdtemp(prefix="astrid_pack_")
        target_copy = Path(pack_root_copy) / pack_id
        shutil.copytree(
            str(pack_root), str(target_copy),
            ignore=gitignore_filter(Path(pack_root)),
            symlinks=True,
        )

        # 9. Validate the staged copy
        errors, warnings = validate_pack(target_copy)
        if warnings:
            for w in warnings:
                print(f"warning: {w}", file=sys.stderr)

        if errors:
            print(
                f"install: source pack validation failed with {len(errors)} error(s):",
                file=sys.stderr,
            )
            for err in errors:
                print(f"  {err}", file=sys.stderr)
            print(
                "install: refusing to install an invalid pack.",
                file=sys.stderr,
            )
            return 1

        # 10. Confirmation
        if not skip_confirm:
            print(
                _format_trust_summary(
                    trust_summary,
                    git_url=git_url,
                    commit_sha=commit_sha,
                    astrid_version=str(raw.get("astrid_version", "")),
                    trust_tier="git",
                )
            )
            print()
            action = "overwrite" if existing else "install"
            if not _confirm(f"Proceed with {action}?"):
                print("Cancelled.", file=sys.stderr)
                return 1

        # 11. Acquire lock and install
        lock = store._acquire_lock(pack_id)
        with lock:
            return _do_install(
                target_copy,
                pack_id,
                trust_summary,
                store,
                force,
                existing,
                manifest_raw=raw,
                git_url=git_url,
                commit_sha=commit_sha,
                requested_ref=requested_ref,
                source_type="git",
            )
    finally:
        # Clean up temporary directories on every exit path
        if checkout_path is not None:
            shutil.rmtree(checkout_path, ignore_errors=True)
        if pack_root_copy is not None:
            shutil.rmtree(pack_root_copy, ignore_errors=True)


def _do_install(
    source: Path,
    pack_id: str,
    trust_summary: dict,
    store: InstalledPackStore,
    force: bool,
    existing: InstallRecord | None,
    *,
    git_url: str = "",
    commit_sha: str = "",
    requested_ref: str = "",
    source_type: str = "local",
    manifest_raw: dict | None = None,
) -> int:
    """Perform the actual install (called under lock)."""

    install_root = store.install_root_for(pack_id)
    revisions_dir = store.revisions_dir(pack_id)
    staging = store.staging_path_for(pack_id)

    # Derive trust_tier from source_type
    trust_tier = source_type  # "local" or "git"

    # Compute manifest_digest from pack manifest file
    manifest_path = pack_manifest_path(source)
    manifest_digest = ""
    if manifest_path is not None and manifest_path.is_file():
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    # Derive astrid_version from manifest raw dict
    astrid_version = ""
    if manifest_raw:
        astrid_version = str(manifest_raw.get("astrid_version", ""))

    # last_validation_time: record that we validated before install
    last_validation_time = _utc_now_iso()

    # Clean up any leftover staging
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)

    # Ensure directory structure
    install_root.mkdir(parents=True, exist_ok=True)
    revisions_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 10. Copy to staging with gitignore filter
    # ------------------------------------------------------------------
    try:
        shutil.copytree(
            source,
            str(staging),
            ignore=gitignore_filter(source),
            symlinks=True,
        )
    except Exception as e:
        print(f"install: copy to staging failed: {e}", file=sys.stderr)
        # Clean up partial staging
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
        return 1

    # ------------------------------------------------------------------
    # 11. Validate staging
    # ------------------------------------------------------------------
    errors, _warnings = validate_pack(staging)
    if errors:
        print(
            f"install: staging validation failed with {len(errors)} error(s):",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    # ------------------------------------------------------------------
    # 12. Handle force: rename old revision
    # ------------------------------------------------------------------
    previous_active_revision = ""
    if existing is not None:
        old_rev_dir = store.active_revision_path(pack_id)
        if old_rev_dir is not None and old_rev_dir.is_dir():
            ts = _revision_timestamp()
            renamed = revisions_dir / f"{pack_id}.{ts}"
            try:
                old_rev_dir.rename(renamed)
                previous_active_revision = renamed.name
            except OSError as e:
                print(
                    f"install: cannot rename old revision: {e}",
                    file=sys.stderr,
                )
                shutil.rmtree(staging, ignore_errors=True)
                return 1

        # Remove old active symlink
        store.mark_inactive(pack_id)

    # ------------------------------------------------------------------
    # 13. Move staging → revisions/<pack_id>/
    # ------------------------------------------------------------------
    rev_target = revisions_dir / pack_id
    if rev_target.exists():
        shutil.rmtree(rev_target, ignore_errors=True)

    try:
        staging.rename(rev_target)
    except OSError as e:
        print(f"install: move staging to revisions failed: {e}", file=sys.stderr)
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    # ------------------------------------------------------------------
    # 14. Create active symlink
    # ------------------------------------------------------------------
    active_link = store.active_symlink_path(pack_id)
    if active_link.exists() or active_link.is_symlink():
        active_link.unlink(missing_ok=True)

    active_link.symlink_to(
        os.path.relpath(rev_target, active_link.parent)
    )

    # ------------------------------------------------------------------
    # 15. Write .astrid/install.json
    # ------------------------------------------------------------------
    # For Git installs, source_path stores the durable git_url (not temp path)
    source_path_str = git_url if source_type == "git" and git_url else str(source)
    record = InstallRecord(
        pack_id=pack_id,
        name=trust_summary.get("name", pack_id),
        version=str(trust_summary.get("version", "0.0.0")),
        schema_version=trust_summary.get("schema_version", 1),
        source_path=source_path_str,
        installed_at=_utc_now_iso(),
        revision=pack_id,
        install_root=str(install_root),
        active=True,
        component_inventory=trust_summary.get("component_counts", {}),
        entrypoints=trust_summary.get("entrypoints", []),
        declared_secrets=trust_summary.get("declared_secrets", []),
        dependencies=trust_summary.get("dependencies", []),
        trust_summary=trust_summary,
        manifest_digest=manifest_digest,
        source_type=source_type,
        git_url=git_url,
        commit_sha=commit_sha,
        requested_ref=requested_ref,
        astrid_version=astrid_version,
        trust_tier=trust_tier,
        last_validation_time=last_validation_time,
        previous_active_revision=previous_active_revision,
    )
    store.record_install(record)

    # ------------------------------------------------------------------
    # 16. Print success
    # ------------------------------------------------------------------
    print(
        _format_trust_summary(
            trust_summary,
            git_url=git_url,
            commit_sha=commit_sha,
            astrid_version=astrid_version,
            trust_tier=trust_tier,
        )
    )
    print()
    print(f"✓ Pack {pack_id!r} installed successfully.")
    print(f"  Location: {install_root}")
    return 0


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def uninstall_pack(
    pack_id: str,
    store: InstalledPackStore | None = None,
    *,
    keep_revisions: bool = False,
    skip_confirm: bool = False,
) -> int:
    """Uninstall a pack.

    Args:
        pack_id: The pack to uninstall.
        store: The ``InstalledPackStore`` to use.
        keep_revisions: If ``True``, leave the revisions directory.
        skip_confirm: If ``True``, skip the confirmation prompt.

    Returns:
        Exit code.
    """
    if store is None:
        store = InstalledPackStore()

    existing = store.get_active(pack_id)
    if existing is None:
        print(
            f"uninstall: pack {pack_id!r} is not installed.",
            file=sys.stderr,
        )
        return 1

    if not skip_confirm:
        print(f"Pack:  {existing.name} ({existing.pack_id})")
        print(f"Ver:   {existing.version}")
        print(f"From:  {existing.source_path}")
        if not _confirm(f"Uninstall {pack_id!r}?"):
            print("Cancelled.", file=sys.stderr)
            return 1

    lock = store._acquire_lock(pack_id)
    with lock:
        store.remove_install(pack_id, keep_revisions=keep_revisions)

    print(f"✓ Pack {pack_id!r} uninstalled.")
    return 0


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def _diff_component_inventories(
    old_summary: dict,
    new_summary: dict,
    *,
    old_version: str = "",
    new_version: str = "",
    old_commit: str = "",
    new_commit: str = "",
) -> str:
    """Produce a human-readable diff between two trust summaries.

    Args:
        old_summary: Trust summary for the currently installed revision.
        new_summary: Trust summary for the candidate (would-be-installed)
            revision.
        old_version: Semantic version string for the old revision.
        new_version: Semantic version string for the new revision.
        old_commit: Commit SHA (or empty) for the old revision.
        new_commit: Commit SHA (or empty) for the new revision.

    Returns:
        A formatted multi-line string suitable for console display.
    """
    lines: list[str] = []
    lines.append("═══ Diff Summary ═══")

    # Version change
    if old_version != new_version:
        lines.append(f"  Version:  {old_version} → {new_version}")
    else:
        lines.append(f"  Version:  {old_version} (unchanged)")

    # Commit SHA change (Git only)
    if old_commit and new_commit and old_commit != new_commit:
        lines.append(
            f"  Commit:   {old_commit[:8]} → {new_commit[:8]}"
        )
    elif old_commit and new_commit:
        lines.append(f"  Commit:   {old_commit[:8]} (unchanged)")

    # Component count deltas
    old_counts = old_summary.get("component_counts", {})
    new_counts = new_summary.get("component_counts", {})
    for kind in ("executors", "orchestrators", "elements"):
        old_n = old_counts.get(kind, 0)
        new_n = new_counts.get(kind, 0)
        if old_n != new_n:
            delta = new_n - old_n
            sign = "+" if delta > 0 else ""
            lines.append(f"  {kind.capitalize()}:{old_n} → {new_n} ({sign}{delta})")
        else:
            lines.append(f"  {kind.capitalize()}:{old_n} (unchanged)")

    # Entrypoint additions/removals
    old_eps = set(old_summary.get("entrypoints", []))
    new_eps = set(new_summary.get("entrypoints", []))
    added_eps = new_eps - old_eps
    removed_eps = old_eps - new_eps
    if added_eps:
        lines.append(f"  Entrypoints added:   {', '.join(sorted(added_eps))}")
    if removed_eps:
        lines.append(f"  Entrypoints removed: {', '.join(sorted(removed_eps))}")
    if not added_eps and not removed_eps and old_eps:
        lines.append("  Entrypoints: (unchanged)")

    # Declared secrets deltas
    old_secrets = set(old_summary.get("declared_secrets", []))
    new_secrets = set(new_summary.get("declared_secrets", []))
    added_secrets = new_secrets - old_secrets
    removed_secrets = old_secrets - new_secrets
    if added_secrets:
        lines.append(f"  Secrets added:   {', '.join(sorted(added_secrets))}")
    if removed_secrets:
        lines.append(f"  Secrets removed: {', '.join(sorted(removed_secrets))}")
    if not added_secrets and not removed_secrets and (old_secrets or new_secrets):
        lines.append("  Secrets: (unchanged)")

    return "\n".join(lines)


def update_pack(
    pack_id: str,
    store: InstalledPackStore | None = None,
    *,
    dry_run: bool = False,
    skip_confirm: bool = False,
) -> int:
    """Update an installed pack from its source.

    Args:
        pack_id: The pack to update.
        store: The ``InstalledPackStore`` to use.
        dry_run: If ``True``, print a diff summary without mutating.
        skip_confirm: If ``True``, skip confirmation.

    Returns:
        Exit code.
    """
    if store is None:
        store = InstalledPackStore()

    existing = store.get_active(pack_id)
    if existing is None:
        print(
            f"update: pack {pack_id!r} is not installed.",
            file=sys.stderr,
        )
        return 1

    # ── Branch: Git-backed packs ──────────────────────────────────────
    if existing.source_type == "git":
        return _update_git_pack(
            existing, pack_id, store,
            dry_run=dry_run,
            skip_confirm=skip_confirm,
        )

    # ── Local-path packs ──────────────────────────────────────────────
    source_path = Path(existing.source_path)
    if not source_path.is_dir():
        print(
            f"update: source directory {source_path} no longer exists. "
            f"Cannot update.",
            file=sys.stderr,
        )
        return 1

    # Verify source pack id matches installed pack id
    manifest_path = pack_manifest_path(source_path)
    if manifest_path is None:
        print(
            f"update: no pack manifest found in source {source_path}",
            file=sys.stderr,
        )
        return 2

    try:
        if manifest_path.suffix == ".json":
            import json as _json

            raw = _json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"update: failed to parse pack manifest: {e}", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print("update: pack manifest is not a mapping", file=sys.stderr)
        return 2

    source_pack_id = raw.get("id")
    if source_pack_id != pack_id:
        print(
            f"update: source pack id {source_pack_id!r} does not match "
            f"installed pack id {pack_id!r}. Refusing to update — "
            f"the pack identity has changed.",
            file=sys.stderr,
        )
        return 1

    # Extract trust summary for display
    try:
        trust_summary = extract_trust_summary(source_path)
    except Exception as e:
        print(f"update: cannot extract trust summary: {e}", file=sys.stderr)
        return 2

    # Dry-run: print diff
    if dry_run:
        print("═══ Currently Installed ═══")
        print(f"  Version:  {existing.version}")
        print(f"  Source:   {existing.source_path}")
        print(f"  Installed:{existing.installed_at}")
        print()
        print("═══ Source (would install) ═══")
        print(
            _format_trust_summary(
                trust_summary,
                git_url=existing.git_url,
                commit_sha=existing.commit_sha,
                astrid_version=str(raw.get("astrid_version", "")),
                trust_tier=existing.trust_tier or existing.source_type,
            )
        )
        return 0

    # Real update: same flow as install with force
    return install_pack(
        source_path,
        store=store,
        dry_run=False,
        skip_confirm=skip_confirm,
        force=True,
    )


def _update_git_pack(
    existing: InstallRecord,
    pack_id: str,
    store: InstalledPackStore,
    *,
    dry_run: bool = False,
    skip_confirm: bool = False,
) -> int:
    """Update a Git-backed pack from its remote.

    Args:
        existing: The active ``InstallRecord`` for the pack.
        pack_id: The pack identifier.
        store: The ``InstalledPackStore`` to use.
        dry_run: If ``True``, print a structured diff without mutating.
        skip_confirm: If ``True``, skip the confirmation prompt.

    Returns:
        Exit code.
    """
    git_url = existing.git_url
    if not git_url:
        print(
            "update: existing pack has no Git URL recorded. Cannot update.",
            file=sys.stderr,
        )
        return 1

    _check_git_available()

    # ── Resolve the remote ref and its commit SHA ─────────────────────
    ref = existing.requested_ref or "HEAD"
    try:
        result = _run_git(
            ("ls-remote", git_url, ref),
            error_msg="git ls-remote failed",
            timeout=30,
        )
    except RuntimeError as e:
        print(f"update: {e}", file=sys.stderr)
        return 1

    remote_sha = ""
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if parts:
            remote_sha = parts[0].strip()
            break

    if not remote_sha:
        # Fallback: try HEAD explicitly
        try:
            result = _run_git(
                ("ls-remote", git_url, "HEAD"),
                error_msg="git ls-remote HEAD failed",
                timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if parts:
                    remote_sha = parts[0].strip()
                    break
        except RuntimeError:
            pass

    if not remote_sha:
        print(
            f"update: could not resolve remote ref for {git_url}",
            file=sys.stderr,
        )
        return 1

    # ── Dry-run: compare SHAs, clone new, show structured diff ────────
    if dry_run:
        # Build old trust summary from existing record
        old_summary = existing.trust_summary if existing.trust_summary else {}
        old_version = existing.version

        # Check if already up to date
        if remote_sha == existing.commit_sha:
            print(f"Pack {pack_id!r} is already up to date.")
            print(f"  Pinned:  {existing.commit_sha[:8]}")
            print(f"  Remote:  {remote_sha[:8]}")
            return 0

        # Clone new version to temp for trust summary
        checkout_path = None
        try:
            checkout_path, clone_sha = _clone_git_pack(git_url)
            pack_root = _find_pack_root_in_checkout(checkout_path)
            new_summary = extract_trust_summary(pack_root)

            # Parse manifest for version
            mp = pack_manifest_path(pack_root)
            new_version = ""
            if mp is not None:
                try:
                    if mp.suffix == ".json":
                        import json as _json

                        new_raw = _json.loads(mp.read_text(encoding="utf-8"))
                    else:
                        new_raw = yaml.safe_load(mp.read_text(encoding="utf-8"))
                    if isinstance(new_raw, dict):
                        new_version = str(new_raw.get("version", ""))
                except Exception:
                    pass

            print("═══ Currently Installed ═══")
            print(f"  Version:  {old_version}")
            print(f"  Source:   {git_url}")
            print(f"  Commit:   {existing.commit_sha[:8]}")
            print(f"  Installed:{existing.installed_at}")
            print()
            print("═══ Remote (would install) ═══")
            print(f"  Version:  {new_version}")
            print(f"  Source:   {git_url}")
            print(f"  Commit:   {remote_sha[:8]}")
            print()

            # Structured diff
            print(
                _diff_component_inventories(
                    old_summary,
                    new_summary,
                    old_version=old_version,
                    new_version=new_version,
                    old_commit=existing.commit_sha,
                    new_commit=remote_sha,
                )
            )
        except Exception as e:
            print(f"update: cannot inspect remote: {e}", file=sys.stderr)
            # Show what we can: SHA comparison
            print()
            print("═══ Currently Installed ═══")
            print(f"  Commit:   {existing.commit_sha[:8]}")
            print(f"  Source:   {git_url}")
            print()
            print(f"  Remote HEAD is now at {remote_sha[:8]} (pinned was {existing.commit_sha[:8]})")
        finally:
            if checkout_path is not None:
                shutil.rmtree(checkout_path, ignore_errors=True)
        return 0

    # ── Real update: clone, install with force ────────────────────────
    checkout_path = None
    pack_root_copy = None
    try:
        checkout_path, new_commit_sha = _clone_git_pack(git_url)
        pack_root = _find_pack_root_in_checkout(checkout_path)

        # Copy pack root to temp dir named after pack_id
        pack_root_copy = tempfile.mkdtemp(prefix="astrid_update_")
        target_copy = Path(pack_root_copy) / pack_id
        shutil.copytree(
            str(pack_root), str(target_copy),
            ignore=gitignore_filter(Path(pack_root)),
            symlinks=True,
        )

        # Resolve requested_ref from remote
        try:
            new_requested_ref = _resolve_git_ref(git_url)
        except Exception:
            new_requested_ref = ref

        return install_pack(
            target_copy,
            store=store,
            dry_run=False,
            skip_confirm=skip_confirm,
            force=True,
            git_url=git_url,
            commit_sha=new_commit_sha,
            requested_ref=new_requested_ref,
            source_type="git",
            skip_name_check=True,
        )
    finally:
        if checkout_path is not None:
            shutil.rmtree(checkout_path, ignore_errors=True)
        # pack_root_copy cleanup: install_pack moves it away on success,
        # but we clean up here as a safety net
        if pack_root_copy is not None:
            shutil.rmtree(pack_root_copy, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_pack(
    pack_id: str,
    store: InstalledPackStore | None = None,
    *,
    revision: str | None = None,
    skip_confirm: bool = False,
) -> int:
    """Rollback an installed pack to a previous revision.

    Args:
        pack_id: The pack to rollback.
        store: The ``InstalledPackStore`` to use.
        revision: The revision directory name to activate.  When ``None``
            (the default), the user is shown a numbered list of available
            revisions and asked to choose one interactively.
        skip_confirm: If ``True``, skip the confirmation prompt (the
            revision selection prompt is still shown when *revision* is
            ``None``).

    Returns:
        Exit code (0 on success).
    """
    if store is None:
        store = InstalledPackStore()

    existing = store.get_active(pack_id)
    if existing is None:
        print(
            f"rollback: pack {pack_id!r} is not installed.",
            file=sys.stderr,
        )
        return 1

    # List available revisions
    revisions = store.list_revisions(pack_id)
    if not revisions:
        print(
            f"rollback: no revisions found for pack {pack_id!r}.",
            file=sys.stderr,
        )
        return 1

    # Determine the current active revision
    active_rev = store.active_revision_path(pack_id)
    current_rev_name = active_rev.name if active_rev is not None else None

    # ── Revision selection ────────────────────────────────────────────
    target_rev_name: str | None = revision

    if target_rev_name is None:
        # Interactive: show numbered prompt
        print(f"Available revisions for {pack_id!r}:")
        for i, rev_path in enumerate(revisions, start=1):
            rev_name = rev_path.name
            marker = " ← active" if rev_name == current_rev_name else ""
            # Try to read the revision record for a short description
            rec = store._read_revision_record(pack_id, rev_name)
            if rec is not None:
                print(
                    f"  [{i}] {rev_name}  "
                    f"v{rec.version}  "
                    f"{rec.installed_at}{marker}"
                )
            else:
                print(f"  [{i}] {rev_name}{marker}")

        print()
        try:
            choice = input(
                "Choose revision number (or press Enter to cancel): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.", file=sys.stderr)
            return 1

        if not choice:
            print("Cancelled.", file=sys.stderr)
            return 1

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(revisions):
                print(
                    f"rollback: invalid choice {choice!r}. "
                    f"Must be between 1 and {len(revisions)}.",
                    file=sys.stderr,
                )
                return 1
        except ValueError:
            print(
                f"rollback: invalid choice {choice!r}.",
                file=sys.stderr,
            )
            return 1

        target_rev_name = revisions[idx].name

    # Validate target exists
    if target_rev_name is None:
        print("rollback: no revision selected.", file=sys.stderr)
        return 1

    target_path = store.revisions_dir(pack_id) / target_rev_name
    if not target_path.is_dir():
        print(
            f"rollback: revision {target_rev_name!r} does not exist.",
            file=sys.stderr,
        )
        return 1

    # Reject rolling back to the currently active revision
    if target_rev_name == current_rev_name:
        print(
            f"rollback: revision {target_rev_name!r} is already active.",
            file=sys.stderr,
        )
        return 1

    # ── Validate target pack manifest ─────────────────────────────────
    target_manifest = pack_manifest_path(target_path)
    if target_manifest is None:
        print(
            f"rollback: no pack manifest found in target revision "
            f"{target_rev_name!r}.",
            file=sys.stderr,
        )
        return 1

    # ── Extract trust summaries for current and target ────────────────
    try:
        target_summary = extract_trust_summary(target_path)
    except Exception as e:
        print(
            f"rollback: cannot extract trust summary from target: {e}",
            file=sys.stderr,
        )
        return 1

    old_summary = existing.trust_summary if existing.trust_summary else {}

    # Read target revision record for version etc.
    target_record = store._read_revision_record(pack_id, target_rev_name)
    target_version = target_record.version if target_record is not None else str(
        target_summary.get("version", "?")
    )

    old_commit = existing.commit_sha
    target_commit = target_record.commit_sha if target_record is not None else ""

    # ── Display trust summaries and diff ──────────────────────────────
    print("═══ Currently Active ═══")
    print(f"  Revision:  {current_rev_name}")
    print(f"  Version:   {existing.version}")
    if old_commit:
        print(f"  Commit:    {old_commit[:8]}")
    print(f"  Source:    {existing.source_path}")
    print()

    print("═══ Target Revision ═══")
    print(f"  Revision:  {target_rev_name}")
    print(f"  Version:   {target_version}")
    if target_commit:
        print(f"  Commit:    {target_commit[:8]}")
    if target_record is not None:
        print(f"  Source:    {target_record.source_path}")
    print()

    # Structured diff
    print(
        _diff_component_inventories(
            old_summary,
            target_summary,
            old_version=existing.version,
            new_version=target_version,
            old_commit=old_commit,
            new_commit=target_commit,
        )
    )
    print()

    # ── Confirmation ──────────────────────────────────────────────────
    if not skip_confirm:
        if not _confirm(
            f"Rollback {pack_id!r} to revision {target_rev_name!r}?"
        ):
            print("Cancelled.", file=sys.stderr)
            return 1

    # ── Perform rollback ──────────────────────────────────────────────
    lock = store._acquire_lock(pack_id)
    try:
        with lock:
            store.rollback_to_revision(pack_id, target_rev_name)
    except FileNotFoundError as e:
        print(f"rollback: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"rollback: unexpected error: {e}", file=sys.stderr)
        return 1

    # ── Re-validate the rolled-back pack ──────────────────────────────
    new_active = store.active_revision_path(pack_id)
    if new_active is not None:
        errors, warnings = validate_pack(new_active)
        if warnings:
            for w in warnings:
                print(f"warning: {w}", file=sys.stderr)
        if errors:
            print(
                f"rollback: rolled-back pack validation failed with "
                f"{len(errors)} error(s) — the revision may be "
                f"incompatible with the current Astrid version.",
                file=sys.stderr,
            )
            for err in errors:
                print(f"  {err}", file=sys.stderr)
            print(
                "rollback: the rollback has been applied, but the pack "
                "may not function correctly.",
                file=sys.stderr,
            )
            return 1

    print(f"✓ Pack {pack_id!r} rolled back to revision {target_rev_name!r}.")
    print(f"  Location: {store.install_root_for(pack_id)}")
    return 0


# ---------------------------------------------------------------------------
# Git helper functions
# ---------------------------------------------------------------------------


def _is_git_url(source: str) -> bool:
    """Return ``True`` if *source* looks like a Git URL.

    Accepts ``https://``, ``git@``, ``ssh://``, and ``git://`` schemes.
    Rejects ``http://`` and ``file://`` as insecure or non-Git.

    Args:
        source: The source string to check.

    Returns:
        ``True`` if the source is a recognized Git URL.
    """
    if not source:
        return False
    lower = source.strip().lower()
    # Accept secure and SSH Git schemes
    if lower.startswith("https://"):
        return True
    if lower.startswith("git@"):
        return True
    if lower.startswith("ssh://"):
        return True
    if lower.startswith("git://"):
        return True
    # Explicitly reject http:// and file://
    if lower.startswith("http://"):
        return False
    if lower.startswith("file://"):
        return False
    return False


def _check_git_available() -> None:
    """Verify that ``git`` is available on the system PATH.

    Raises:
        RuntimeError: If ``git --version`` returns a non-zero exit code,
            with a clear message instructing the user to install Git.
    """
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Git is not available on this system. "
            "Install Git (https://git-scm.com) to install packs from Git URLs."
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Git is not functioning correctly: {exc}"
        ) from exc
    except subprocess.TimeoutExpired:
        raise RuntimeError("Git check timed out. Is Git installed and working?")


def _run_git(
    command: tuple[str, ...],
    error_msg: str = "",
    *,
    cwd: str | Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    """Run a Git subprocess and raise ``RuntimeError`` on failure.

    Args:
        command: The git command and arguments as a tuple (e.g., ``("clone", url)``).
        error_msg: Optional context string for richer error messages.
        cwd: Working directory for the subprocess.
        timeout: Maximum seconds to wait.

    Returns:
        The completed process on success.

    Raises:
        RuntimeError: If the Git command fails.
    """
    full_cmd = ("git",) + tuple(command)
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        msg = f"Git command timed out: {' '.join(full_cmd)}"
        if error_msg:
            msg = f"{error_msg}: {msg}"
        raise RuntimeError(msg)
    except FileNotFoundError:
        raise RuntimeError(
            "Git is not available on this system. "
            "Install Git (https://git-scm.com) to install packs from Git URLs."
        )

    if result.returncode != 0:
        msg = (
            f"Git command failed (exit {result.returncode}): "
            f"{' '.join(full_cmd)}\n{result.stderr.strip()}"
        )
        if error_msg:
            msg = f"{error_msg}: {msg}"
        raise RuntimeError(msg)

    return result


def _clone_git_pack(git_url: str) -> tuple[str, str]:
    """Clone a Git repository into a temporary directory and return its commit SHA.

    Performs a shallow clone (``--depth 1``) for speed.

    Args:
        git_url: The Git URL to clone.

    Returns:
        A tuple ``(checkout_path, commit_sha)`` where *checkout_path* is the
        absolute path to the temporary directory and *commit_sha* is the
        full 40-character commit hash of HEAD.
    """
    checkout_path = tempfile.mkdtemp(prefix="astrid_git_")

    try:
        _run_git(
            ("clone", "--depth", "1", git_url, checkout_path),
            error_msg="git clone failed",
            timeout=300,
        )
    except Exception:
        # Clean up temp dir on clone failure
        shutil.rmtree(checkout_path, ignore_errors=True)
        raise

    try:
        result = _run_git(
            ("rev-parse", "HEAD"),
            error_msg="git rev-parse failed",
            cwd=checkout_path,
        )
    except Exception:
        shutil.rmtree(checkout_path, ignore_errors=True)
        raise

    commit_sha = result.stdout.strip()
    return checkout_path, commit_sha


def _resolve_git_ref(git_url: str) -> str:
    """Determine the default branch ref for a remote Git repository.

    First tries ``git ls-remote --symref`` (Git >= 2.37).
    Falls back to parsing ``git ls-remote --heads`` output for older Git versions.

    Args:
        git_url: The remote Git URL.

    Returns:
        The requested ref name (e.g., ``"HEAD"``, ``"refs/heads/main"``).
        Defaults to ``"HEAD"`` if parsing fails.
    """
    # Try --symref first (Git >= 2.37)
    try:
        result = _run_git(
            ("ls-remote", "--symref", git_url, "HEAD"),
            error_msg="",
            timeout=30,
        )
        stderr = result.stderr.strip()
        if stderr:
            # --symref info is on stderr: "ref: refs/heads/main\tHEAD\n"
            for line in stderr.splitlines():
                if line.startswith("ref: ") and "\t" in line:
                    ref = line.split("\t", 1)[0][5:].strip()
                    return ref
    except RuntimeError:
        pass  # Fall through to fallback

    # Fallback: parse --heads output for older Git
    try:
        result = _run_git(
            ("ls-remote", "--heads", git_url),
            error_msg="git ls-remote failed",
            timeout=30,
        )
        stdout = result.stdout.strip()
        if stdout:
            lines = stdout.splitlines()
            # Look for HEAD line or common default branches
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2:
                    ref_name = parts[1].strip()
                    if ref_name in (
                        "refs/heads/main",
                        "refs/heads/master",
                        "refs/heads/HEAD",
                    ):
                        return ref_name
            # If no common branch found, return the first ref
            parts = lines[0].split("\t")
            if len(parts) >= 2:
                return parts[1].strip()
    except RuntimeError:
        pass

    return "HEAD"


def _find_pack_root_in_checkout(checkout: str | Path) -> Path:
    """Auto-detect the pack root directory inside a Git checkout.

    Strategy:
    1. If the checkout root itself contains ``pack.yaml`` (or ``pack.yml``,
       ``pack.json``), return the checkout root.
    2. Otherwise, look for exactly one direct subdirectory containing a pack
       manifest. If found, return that subdirectory.
    3. If zero or multiple subdirectories have pack manifests, raise an error.

    Args:
        checkout: The path to the cloned repository.

    Returns:
        The absolute path to the detected pack root.

    Raises:
        RuntimeError: If no pack root or multiple pack roots are found.
    """
    checkout_path = Path(checkout).resolve()

    # Strategy 1: checkout root has pack manifest
    if pack_manifest_path(checkout_path) is not None:
        return checkout_path

    # Strategy 2: look for exactly one subdir with a pack manifest
    candidates: list[Path] = []
    try:
        for child in checkout_path.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                if pack_manifest_path(child) is not None:
                    candidates.append(child)
    except OSError:
        pass

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) == 0:
        raise RuntimeError(
            f"No pack manifest found in {checkout_path} or its immediate subdirectories. "
            "Expected pack.yaml, pack.yml, or pack.json."
        )

    # Multiple candidates
    candidate_names = ", ".join(f"'{c.name}'" for c in candidates)
    raise RuntimeError(
        f"Multiple pack roots found in {checkout_path}: {candidate_names}. "
        "Move the desired pack to the repository root or leave only one pack in the repository."
    )


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def cmd_install(argv: list[str]) -> int:
    """``packs install`` CLI handler."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs install",
        description="Install a pack from a local directory or Git URL.",
    )
    parser.add_argument(
        "source",
        help="Path to the pack source directory or a Git URL "
        "(https://..., git@..., ssh://..., git://...).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print trust summary without installing.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing install (preserve old revision).",
    )
    args = parser.parse_args(argv)

    # Git URLs are detected BEFORE any filesystem path resolution
    if _is_git_url(args.source):
        return install_pack(
            args.source,
            dry_run=args.dry_run,
            skip_confirm=args.yes,
            force=args.force,
        )

    # Local path: resolve and check existence
    source = Path(args.source).expanduser()
    if not source.is_dir():
        print(
            f"install: {args.source} is not a directory or does not exist",
            file=sys.stderr,
        )
        return 2

    return install_pack(
        source,
        dry_run=args.dry_run,
        skip_confirm=args.yes,
        force=args.force,
    )


def cmd_update(argv: list[str]) -> int:
    """``packs update`` CLI handler."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs update",
        description="Update an installed pack from its source.",
    )
    parser.add_argument(
        "pack_id",
        help="Pack identifier to update.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print diff summary without updating.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args(argv)

    return update_pack(
        args.pack_id,
        dry_run=args.dry_run,
        skip_confirm=args.yes,
    )


def cmd_uninstall(argv: list[str]) -> int:
    """``packs uninstall`` CLI handler."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs uninstall",
        description="Uninstall an installed pack.",
    )
    parser.add_argument(
        "pack_id",
        help="Pack identifier to uninstall.",
    )
    parser.add_argument(
        "--keep-revisions",
        action="store_true",
        help="Keep revision directories on disk.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args(argv)

    return uninstall_pack(
        args.pack_id,
        keep_revisions=args.keep_revisions,
        skip_confirm=args.yes,
    )


def cmd_rollback(argv: list[str]) -> int:
    """``packs rollback`` CLI handler."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs rollback",
        description="Rollback an installed pack to a previous revision.",
    )
    parser.add_argument(
        "pack_id",
        help="Pack identifier to rollback.",
    )
    parser.add_argument(
        "--revision",
        help="Specific revision directory name to activate. "
        "If omitted, shows an interactive numbered list.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args(argv)

    return rollback_pack(
        args.pack_id,
        revision=args.revision,
        skip_confirm=args.yes,
    )


__all__ = [
    "install_pack",
    "uninstall_pack",
    "update_pack",
    "rollback_pack",
    "cmd_install",
    "cmd_update",
    "cmd_uninstall",
    "cmd_rollback",
    "_install_from_git",
    "_update_git_pack",
    "_diff_component_inventories",
    "_is_git_url",
    "_check_git_available",
    "_run_git",
    "_clone_git_pack",
    "_resolve_git_ref",
    "_find_pack_root_in_checkout",
]
