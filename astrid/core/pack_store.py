"""Installed-pack store: records, paths, symlinks, locks, and root discovery.

Layout under ``~/.astrid/packs/`` (honours ``ASTRID_HOME``)::

    <pack_id>/
      active -> revisions/<pack_id>/          # symlink to active revision
      revisions/
        <pack_id>/                             # active revision directory
          .astrid/
            install.json                       # InstallRecord as JSON
        <pack_id>.<timestamp>/                 # rotated-out old revisions
      staging/                                 # temporary staging area
      .astrid/
        install.lock                           # filelock mutex

The revision directory is named after *pack_id* so that ``PackResolver``
satisfies ``root.name == pack_id`` (an invariant enforced during pack
manifest loading).
"""

from __future__ import annotations

import json as _json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from astrid.core.session.paths import installed_packs_root

try:
    from filelock import FileLock as _FileLock
except ImportError:  # pragma: no cover — dev-friendly fallback
    _FileLock = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Install record
# ---------------------------------------------------------------------------


@dataclass
class InstallRecord:
    """Per-revision install metadata written to ``.astrid/install.json``."""

    pack_id: str
    name: str
    version: str
    schema_version: int | str
    source_path: str
    installed_at: str  # ISO-8601 UTC
    revision: str  # revision directory name, e.g. "<pack_id>" or "<pack_id>.<ts>"
    install_root: str  # absolute path of the per-pack root (<packs root>/<pack_id>)
    active: bool = True

    # Extended fields (populated when available)
    manifest_digest: str = ""
    component_inventory: dict[str, int] = field(default_factory=dict)
    entrypoints: list[str] = field(default_factory=list)
    declared_secrets: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    trust_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InstallRecord":
        # Filter to known fields to stay forward-compatible
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# InstalledPackStore
# ---------------------------------------------------------------------------


class InstalledPackStore:
    """Manage installed packs under the per-user packs home.

    The *packs_home* parameter (defaults to ``installed_packs_root()``)
    exists so tests can use temporary directories.
    """

    def __init__(self, packs_home: str | Path | None = None) -> None:
        self._home = Path(packs_home) if packs_home else installed_packs_root()

    # -- path helpers --------------------------------------------------------

    def install_root_for(self, pack_id: str) -> Path:
        """Return ``<packs_home>/<pack_id>``."""
        return self._home / pack_id

    def active_symlink_path(self, pack_id: str) -> Path:
        """Return ``<packs_home>/<pack_id>/active`` (the symlink)."""
        return self.install_root_for(pack_id) / "active"

    def revisions_dir(self, pack_id: str) -> Path:
        """Return ``<packs_home>/<pack_id>/revisions``."""
        return self.install_root_for(pack_id) / "revisions"

    def active_revision_path(self, pack_id: str) -> Path | None:
        """Resolve the *active* symlink to the real revision directory.

        Returns ``None`` when the symlink does not exist or is broken.
        """
        link = self.active_symlink_path(pack_id)
        try:
            resolved = link.resolve(strict=False)
        except OSError:
            return None
        if not resolved.is_dir():
            return None
        return resolved

    def staging_path_for(self, pack_id: str) -> Path:
        """Return ``<packs_home>/<pack_id>/staging``."""
        return self.install_root_for(pack_id) / "staging"

    def lock_path_for(self, pack_id: str) -> Path:
        """Return ``<packs_home>/<pack_id>/.astrid/install.lock``."""
        return self.install_root_for(pack_id) / ".astrid" / "install.lock"

    # -- locking -------------------------------------------------------------

    def _acquire_lock(self, pack_id: str, timeout: float = 30.0):
        """Acquire a filelock for *pack_id*.  Returns a context-manager.

        If *filelock* is not available, returns a no-op context manager and
        emits a warning.
        """
        if _FileLock is None:
            import warnings
            warnings.warn(
                "filelock not installed; concurrent install protection disabled"
            )
            return _NoOpLock()

        lock_path = self.lock_path_for(pack_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return _FileLock(str(lock_path), timeout=timeout)

    # -- listing / querying --------------------------------------------------

    def list_installed(self) -> list[InstallRecord]:
        """Return all installed pack records, newest-first.

        When ``~/.astrid/packs/`` does not exist, returns an empty list.
        """
        if not self._home.is_dir():
            return []
        records: list[InstallRecord] = []
        try:
            for child in sorted(self._home.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                rec = self._read_active_record(child.name)
                if rec is not None:
                    records.append(rec)
        except OSError:
            return []
        # Sort newest-first by installed_at
        records.sort(key=lambda r: r.installed_at, reverse=True)
        return records

    def get_active(self, pack_id: str) -> InstallRecord | None:
        """Return the active InstallRecord for *pack_id*, or ``None``."""
        return self._read_active_record(pack_id)

    def is_installed(self, pack_id: str) -> bool:
        """Return ``True`` when *pack_id* has an active install."""
        return self.get_active(pack_id) is not None

    # -- active pack roots ---------------------------------------------------

    def active_pack_roots(self) -> tuple[Path, ...]:
        """Return resolved revision directories for every active installed pack.

        Each returned path is the real revision directory (not the ``active``
        symlink), satisfying ``PackResolver``'s ``root.name == pack_id``
        invariant.

        Returns an empty tuple when ``~/.astrid/packs/`` does not exist.
        """
        if not self._home.is_dir():
            return ()
        roots: list[Path] = []
        try:
            for child in sorted(self._home.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                rev = self.active_revision_path(child.name)
                if rev is not None:
                    roots.append(rev)
        except OSError:
            return ()
        return tuple(roots)

    # -- mutations -----------------------------------------------------------

    def record_install(self, record: InstallRecord) -> None:
        """Persist *record* to ``<revision>/.astrid/install.json``."""
        rev_dir = Path(record.install_root) / "revisions" / record.revision
        astrid_dir = rev_dir / ".astrid"
        astrid_dir.mkdir(parents=True, exist_ok=True)
        record_path = astrid_dir / "install.json"
        record_path.write_text(
            _json.dumps(record.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def mark_inactive(self, pack_id: str) -> None:
        """Remove the *active* symlink so the pack is no longer discoverable."""
        link = self.active_symlink_path(pack_id)
        try:
            link.unlink(missing_ok=True)
        except OSError:
            pass

    def remove_install(self, pack_id: str, *, keep_revisions: bool = False) -> None:
        """Remove an installed pack completely (or keep revision dirs).

        Args:
            pack_id: The pack to remove.
            keep_revisions: If ``True``, leave the revisions directory intact.
        """
        root = self.install_root_for(pack_id)
        if not root.is_dir():
            return

        # Remove active symlink
        self.mark_inactive(pack_id)

        # Remove staging area if present
        staging = self.staging_path_for(pack_id)
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)

        # Remove lock file
        lock = self.lock_path_for(pack_id)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass

        if keep_revisions:
            # Preserve revisions dir, just clean up the per-pack root metadata
            astrid_meta = root / ".astrid"
            if astrid_meta.is_dir():
                shutil.rmtree(astrid_meta, ignore_errors=True)
        else:
            shutil.rmtree(root, ignore_errors=True)

    # -- internal helpers ----------------------------------------------------

    def _read_active_record(self, pack_id: str) -> InstallRecord | None:
        """Read the install.json from the active revision, or return None."""
        rev = self.active_revision_path(pack_id)
        if rev is None:
            return None
        record_path = rev / ".astrid" / "install.json"
        if not record_path.is_file():
            return None
        try:
            data = _json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            return None
        try:
            return InstallRecord.from_dict(data)
        except TypeError:
            return None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# No-op lock for environments without filelock
# ---------------------------------------------------------------------------


class _NoOpLock:
    """Context manager that does nothing (fallback when filelock is absent)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def installed_pack_roots() -> tuple[Path, ...]:
    """Convenience: return active revision directories for all installed packs.

    Uses the default ``InstalledPackStore`` (``installed_packs_root()``).
    Gracefully returns an empty tuple when the packs directory is missing.
    """
    store = InstalledPackStore()
    return store.active_pack_roots()


# ---------------------------------------------------------------------------
# Timestamp helpers (used by install.py)
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string (suitable for filenames)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _revision_timestamp() -> str:
    """Return a compact UTC timestamp string suitable for revision dir names."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


__all__ = [
    "InstallRecord",
    "InstalledPackStore",
    "installed_pack_roots",
]
