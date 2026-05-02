"""Repository structure guardrails for ArtAgents canonical concepts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artagents._paths import REPO_ROOT
from artagents.executors.folder import load_folder_executors
from artagents.orchestrators.folder import load_folder_orchestrators


LEGACY_PUBLIC_DIRS = ("conductors", "performers", "instruments", "primitives")
INTERNAL_EXECUTOR_DIRS = {"__pycache__", "actions", "builtin", "bundled", "curated"}
INTERNAL_ORCHESTRATOR_DIRS = {"__pycache__", "bundled", "curated"}


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
    errors.extend(_validate_executor_folders(repo_root / "artagents" / "executors"))
    errors.extend(_validate_orchestrator_folders(repo_root / "artagents" / "orchestrators"))
    return StructureReport(errors=tuple(errors))


def _validate_legacy_dirs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for dirname in LEGACY_PUBLIC_DIRS:
        candidate = repo_root / "artagents" / dirname
        if candidate.exists():
            errors.append(f"legacy public package must not exist: {candidate.relative_to(repo_root)}")
    return errors


def _validate_executor_folders(executors_root: Path) -> list[str]:
    if not executors_root.is_dir():
        return [f"missing executors directory: {executors_root}"]

    errors: list[str] = []
    for folder in _public_child_dirs(executors_root, INTERNAL_EXECUTOR_DIRS):
        errors.extend(_require_files(folder, ("executor.yaml", "run.py", "SKILL.md"), root=executors_root.parents[1]))
        if _has_any(folder, ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json", "orchestrator.py")):
            errors.append(f"executor folder contains orchestrator metadata: {folder.relative_to(executors_root.parents[1])}")
        try:
            definitions = load_folder_executors(folder)
        except Exception as exc:
            errors.append(f"invalid executor folder {folder.relative_to(executors_root.parents[1])}: {exc}")
            continue
        if not definitions:
            errors.append(f"executor folder emitted no executor metadata: {folder.relative_to(executors_root.parents[1])}")
            continue
        for definition in definitions:
            if definition.kind == "built_in" and definition.id.startswith("builtin."):
                expected = f"builtin.{folder.name}"
                if definition.id != expected:
                    errors.append(f"built-in executor {definition.id!r} must live in artagents/executors/{definition.id.removeprefix('builtin.')}")
            elif definition.kind == "external" and definition.id.startswith("external."):
                package = definition.metadata.get("package_id") or definition.id.removeprefix("external.").split(".", 1)[0]
                if package != folder.name:
                    errors.append(f"external executor {definition.id!r} package {package!r} must live in artagents/executors/{package}")
    return errors


def _validate_orchestrator_folders(orchestrators_root: Path) -> list[str]:
    if not orchestrators_root.is_dir():
        return [f"missing orchestrators directory: {orchestrators_root}"]

    errors: list[str] = []
    for folder in _public_child_dirs(orchestrators_root, INTERNAL_ORCHESTRATOR_DIRS):
        errors.extend(_require_files(folder, ("orchestrator.yaml", "run.py", "SKILL.md"), root=orchestrators_root.parents[1]))
        if _has_any(folder, ("executor.yaml", "executor.yml", "executor.json", "executor.py")):
            errors.append(f"orchestrator folder contains executor metadata: {folder.relative_to(orchestrators_root.parents[1])}")
        try:
            definitions = load_folder_orchestrators(folder)
        except Exception as exc:
            errors.append(f"invalid orchestrator folder {folder.relative_to(orchestrators_root.parents[1])}: {exc}")
            continue
        if not definitions:
            errors.append(f"orchestrator folder emitted no orchestrator metadata: {folder.relative_to(orchestrators_root.parents[1])}")
            continue
        for definition in definitions:
            expected = f"builtin.{folder.name}"
            if definition.kind != "built_in" or definition.id != expected:
                errors.append(f"built-in orchestrator folder {folder.name!r} must expose id {expected!r}")
    return errors


def _public_child_dirs(root: Path, skipped: set[str]) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.iterdir() if path.is_dir() and path.name not in skipped and not path.name.startswith(".")))


def _require_files(folder: Path, filenames: tuple[str, ...], *, root: Path) -> list[str]:
    return [f"{folder.relative_to(root)} missing {filename}" for filename in filenames if not (folder / filename).is_file()]


def _has_any(folder: Path, filenames: tuple[str, ...]) -> bool:
    return any((folder / filename).exists() for filename in filenames)


__all__ = ["StructureReport", "validate_repo_structure"]
