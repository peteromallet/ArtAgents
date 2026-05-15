"""``packs install`` / ``packs uninstall`` / ``packs update`` commands.

``packs install <source-path>`` installs a local external pack as a snapshot
under ``~/.astrid/packs/<pack_id>/``.

``packs install --dry-run <source-path>`` prints a trust summary without
mutating any state.

``packs update <pack_id>`` refreshes an installed pack from its source.

``packs uninstall <pack_id>`` removes an installed pack.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
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


def _format_trust_summary(summary: dict) -> str:
    """Format an extract_trust_summary dict for display."""
    lines: list[str] = []
    lines.append("━━━ Trust Summary ━━━")
    lines.append(f"  Pack ID:       {summary.get('pack_id', '?')}")
    lines.append(f"  Name:          {summary.get('name', '?')}")
    lines.append(f"  Version:       {summary.get('version', '?')}")
    lines.append(f"  Schema:        {summary.get('schema_version', '?')}")
    lines.append(f"  Source:        {summary.get('source_path', '?')}")

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
) -> int:
    """Install a local external pack.

    Args:
        source_path: Path to the pack source directory.
        store: The ``InstalledPackStore`` to use.  Defaults to a new one.
        dry_run: If ``True``, print the trust summary and return 0 without
            mutating state.
        skip_confirm: If ``True``, skip the confirmation prompt.
        force: If ``True``, overwrite an existing install (old revision is
            renamed to ``<pack_id>.<timestamp>``).

    Returns:
        Exit code (0 on success).
    """
    if store is None:
        store = InstalledPackStore()

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
    if source.name != pack_id:
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
        print(_format_trust_summary(trust_summary))
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
        print(_format_trust_summary(trust_summary))
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
            return _do_install(source, pack_id, trust_summary, store, force, existing)
    except Exception:
        # Ensure no broken state — clean up staging if it exists
        staging = store.staging_path_for(pack_id)
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _do_install(
    source: Path,
    pack_id: str,
    trust_summary: dict,
    store: InstalledPackStore,
    force: bool,
    existing: InstallRecord | None,
) -> int:
    """Perform the actual install (called under lock)."""

    install_root = store.install_root_for(pack_id)
    revisions_dir = store.revisions_dir(pack_id)
    staging = store.staging_path_for(pack_id)

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
    if existing is not None:
        old_rev_dir = store.active_revision_path(pack_id)
        if old_rev_dir is not None and old_rev_dir.is_dir():
            ts = _revision_timestamp()
            renamed = revisions_dir / f"{pack_id}.{ts}"
            try:
                old_rev_dir.rename(renamed)
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
    record = InstallRecord(
        pack_id=pack_id,
        name=trust_summary.get("name", pack_id),
        version=str(trust_summary.get("version", "0.0.0")),
        schema_version=trust_summary.get("schema_version", 1),
        source_path=str(source),
        installed_at=_utc_now_iso(),
        revision=pack_id,
        install_root=str(install_root),
        active=True,
        component_inventory=trust_summary.get("component_counts", {}),
        entrypoints=trust_summary.get("entrypoints", []),
        declared_secrets=trust_summary.get("declared_secrets", []),
        dependencies=trust_summary.get("dependencies", []),
        trust_summary=trust_summary,
    )
    store.record_install(record)

    # ------------------------------------------------------------------
    # 16. Print success
    # ------------------------------------------------------------------
    print(_format_trust_summary(trust_summary))
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
        print(_format_trust_summary(trust_summary))
        return 0

    # Real update: same flow as install with force
    return install_pack(
        source_path,
        store=store,
        dry_run=False,
        skip_confirm=skip_confirm,
        force=True,
    )


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def cmd_install(argv: list[str]) -> int:
    """``packs install`` CLI handler."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs install",
        description="Install a local external pack.",
    )
    parser.add_argument(
        "source",
        help="Path to the pack source directory.",
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


__all__ = [
    "install_pack",
    "uninstall_pack",
    "update_pack",
    "cmd_install",
    "cmd_update",
    "cmd_uninstall",
]
