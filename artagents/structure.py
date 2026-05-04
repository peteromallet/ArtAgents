"""Repository structure guardrails for ArtAgents canonical concepts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artagents._paths import REPO_ROOT
from artagents.core.executor.folder import load_folder_executors
from artagents.core.orchestrator.folder import load_folder_orchestrators


LEGACY_PUBLIC_DIRS = ("conductors", "performers", "instruments", "primitives", "executors", "orchestrators")
LEGACY_LOCAL_DIRS = ("performers", "conductors", "nodes", "instruments", "primitives")
INTERNAL_PACK_DIRS = {"__pycache__"}
TOP_LEVEL_ARTAGENTS_FILES = {
    "__init__.py",
    "__main__.py",
    "_paths.py",
    "doctor.py",
    "pipeline.py",
    "setup_cli.py",
    "structure.py",
    "theme_schema.py",
    "timeline.py",
}
TOP_LEVEL_ARTAGENTS_DIRS = {
    "__pycache__",
    "audit",
    "contracts",
    "core",
    "domains",
    "elements",
    "modalities",
    "packs",
    "threads",
    "utilities",
}


@dataclass(frozen=True)
class StructureReport:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_repo_structure(root: str | Path = REPO_ROOT) -> StructureReport:
    repo_root = Path(root)
    errors: list[str] = []
    errors.extend(_validate_legacy_dirs(repo_root))
    errors.extend(_validate_local_state_dirs(repo_root))
    errors.extend(_validate_top_level_artagents(repo_root / "artagents"))
    errors.extend(_validate_pack_executor_folders(repo_root / "artagents" / "packs"))
    errors.extend(_validate_pack_orchestrator_folders(repo_root / "artagents" / "packs"))
    return StructureReport(errors=tuple(errors))


def _validate_legacy_dirs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for dirname in LEGACY_PUBLIC_DIRS:
        candidate = repo_root / "artagents" / dirname
        if candidate.exists():
            errors.append(f"legacy public package must not exist: {candidate.relative_to(repo_root)}")
    return errors


def _validate_local_state_dirs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    local_root = repo_root / ".artagents"
    if not local_root.exists():
        return errors
    for dirname in LEGACY_LOCAL_DIRS:
        candidate = local_root / dirname
        if candidate.exists():
            errors.append(f"legacy local state directory must not exist: {candidate.relative_to(repo_root)}")
    return errors


def _validate_top_level_artagents(package_root: Path) -> list[str]:
    errors: list[str] = []
    for child in sorted(package_root.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix == ".py" and child.name not in TOP_LEVEL_ARTAGENTS_FILES:
            errors.append(f"top-level artagents module must move to a canonical package: {child.relative_to(package_root.parents[0])}")
        if child.is_dir() and child.name not in TOP_LEVEL_ARTAGENTS_DIRS:
            errors.append(f"top-level artagents directory is not a canonical concept: {child.relative_to(package_root.parents[0])}")
    return errors


def _validate_pack_executor_folders(packs_root: Path) -> list[str]:
    if not packs_root.is_dir():
        return [f"missing packs directory: {packs_root}"]

    errors: list[str] = []
    repo_root = packs_root.parents[1]
    for pack_dir in _public_child_dirs(packs_root, INTERNAL_PACK_DIRS):
        for folder in _public_child_dirs(pack_dir, INTERNAL_PACK_DIRS):
            if not _has_any(folder, ("executor.yaml", "executor.yml", "executor.json", "executor.py")):
                continue
            errors.extend(_require_files(folder, ("executor.yaml", "run.py", "STAGE.md"), root=repo_root))
            if _has_any(folder, ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json", "orchestrator.py")):
                errors.append(f"executor folder contains orchestrator metadata: {folder.relative_to(repo_root)}")
            try:
                definitions = load_folder_executors(folder)
            except Exception as exc:
                errors.append(f"invalid executor folder {folder.relative_to(repo_root)}: {exc}")
                continue
            if not definitions:
                errors.append(f"executor folder emitted no executor metadata: {folder.relative_to(repo_root)}")
                continue
            for definition in definitions:
                pack_segment = definition.id.split(".", 1)[0]
                if pack_segment != pack_dir.name:
                    errors.append(
                        f"executor {definition.id!r} must live in pack {pack_segment!r} but was found in pack {pack_dir.name!r}"
                    )
    return errors


def _validate_pack_orchestrator_folders(packs_root: Path) -> list[str]:
    if not packs_root.is_dir():
        return [f"missing packs directory: {packs_root}"]

    errors: list[str] = []
    repo_root = packs_root.parents[1]
    for pack_dir in _public_child_dirs(packs_root, INTERNAL_PACK_DIRS):
        for folder in _public_child_dirs(pack_dir, INTERNAL_PACK_DIRS):
            if not _has_any(folder, ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json", "orchestrator.py")):
                continue
            errors.extend(_require_files(folder, ("orchestrator.yaml", "run.py", "STAGE.md"), root=repo_root))
            if _has_any(folder, ("executor.yaml", "executor.yml", "executor.json", "executor.py")):
                errors.append(f"orchestrator folder contains executor metadata: {folder.relative_to(repo_root)}")
            try:
                definitions = load_folder_orchestrators(folder)
            except Exception as exc:
                errors.append(f"invalid orchestrator folder {folder.relative_to(repo_root)}: {exc}")
                continue
            if not definitions:
                errors.append(f"orchestrator folder emitted no orchestrator metadata: {folder.relative_to(repo_root)}")
                continue
            for definition in definitions:
                pack_segment = definition.id.split(".", 1)[0]
                if pack_segment != pack_dir.name:
                    errors.append(
                        f"orchestrator {definition.id!r} must live in pack {pack_segment!r} but was found in pack {pack_dir.name!r}"
                    )
    return errors


def _public_child_dirs(root: Path, skipped: set[str]) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.iterdir() if path.is_dir() and path.name not in skipped and not path.name.startswith(".")))


def _require_files(folder: Path, filenames: tuple[str, ...], *, root: Path) -> list[str]:
    return [f"{folder.relative_to(root)} missing {filename}" for filename in filenames if not (folder / filename).is_file()]


def _has_any(folder: Path, filenames: tuple[str, ...]) -> bool:
    return any((folder / filename).exists() for filename in filenames)


__all__ = ["StructureReport", "validate_repo_structure"]
