"""Abstract base for the per-harness install adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

from ..discovery import SkillDescriptor

Action = Literal["install", "uninstall"]


@dataclass(frozen=True)
class PlannedStep:
    description: str
    target: Path | None = None
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InstallRecord:
    """Filesystem-discovered evidence that a pack is installed for a harness.

    Returned by ``HarnessAdapter.discover_installed``. Mirrors the shape we
    persist in the state file (target/mechanism) but is reconstructed purely
    from on-disk reality, so it can be used to detect and self-heal drift.
    """

    pack_id: str
    target: Path
    mechanism: str


class HarnessAdapter:
    name: str = ""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home

    @property
    def home(self) -> Path:
        return self._home if self._home is not None else self._default_home()

    def _default_home(self) -> Path:  # pragma: no cover - overridden
        raise NotImplementedError

    def detect(self) -> bool:
        return self.home.exists() and self.home.is_dir()

    def target_for(self, descriptor: SkillDescriptor) -> Path:  # pragma: no cover - overridden
        raise NotImplementedError

    def plan(self, action: Action, descriptors: Iterable[SkillDescriptor], **opts) -> list[PlannedStep]:  # pragma: no cover - overridden
        raise NotImplementedError

    def apply(self, action: Action, descriptors: Iterable[SkillDescriptor], **opts) -> list[PlannedStep]:  # pragma: no cover - overridden
        raise NotImplementedError

    def verify(self, descriptor: SkillDescriptor) -> tuple[bool, str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def discover_installed(self, descriptor: SkillDescriptor) -> Optional[InstallRecord]:
        """Probe the filesystem and return an InstallRecord if the pack is installed.

        Default implementation reuses ``verify`` semantics: if verify passes,
        the install is considered present at ``target_for(descriptor)`` with
        mechanism "symlink". Adapters with multi-mechanism or composite
        evidence (codex AGENTS.md, hermes external-dir) override.
        """
        try:
            ok, _ = self.verify(descriptor)
        except Exception:
            return None
        if not ok:
            return None
        return InstallRecord(
            pack_id=descriptor.pack_id,
            target=self.target_for(descriptor),
            mechanism="symlink",
        )


def ensure_symlink(target: Path, source: Path, *, force: bool = False) -> bool:
    """Idempotently create ``target`` as a symlink → ``source``.

    Returns True if the FS state changed, False if already correct.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    source_resolved = source.resolve()
    if target.is_symlink():
        try:
            existing = Path(target).resolve()
        except OSError:
            existing = None
        if existing == source_resolved:
            return False
        if not force:
            # Different existing symlink — replace anyway, install is the
            # authoritative writer for these paths.
            pass
        target.unlink()
    elif target.exists():
        if not force:
            raise FileExistsError(f"{target} exists and is not a symlink; use --force to replace")
        if target.is_dir():
            import shutil

            shutil.rmtree(target)
        else:
            target.unlink()
    target.symlink_to(source_resolved)
    return True


def remove_symlink(target: Path) -> bool:
    if target.is_symlink():
        target.unlink()
        return True
    if target.exists():
        # Refuse to remove a non-symlink we didn't create.
        return False
    return False


__all__ = [
    "Action",
    "HarnessAdapter",
    "InstallRecord",
    "PlannedStep",
    "ensure_symlink",
    "remove_symlink",
]
