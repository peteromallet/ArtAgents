"""Registry and discovery helpers for ArtAgents executors."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable

from artagents.core.pack import discover_packs, iter_executor_roots, validate_content_id_in_pack

from .banodoco_catalog import BanodocoCatalogConfig, load_banodoco_catalog_executors
from .folder import load_folder_executors
from .schema import ExecutorDefinition, ExecutorValidationError, load_executor_manifest, validate_executor_definition


BUNDLED_PACKAGE = "artagents.executors.bundled"
CURATED_PACKAGE = "artagents.executors.curated"
BUILTIN_STEP_ORDER: tuple[str, ...] = (
    "transcribe",
    "scenes",
    "quality_zones",
    "shots",
    "triage",
    "scene_describe",
    "quote_scout",
    "pool_build",
    "pool_merge",
    "arrange",
    "cut",
    "refine",
    "render",
    "editor_review",
    "validate",
)


class ExecutorRegistryError(ExecutorValidationError):
    """Raised when a executor registry is inconsistent."""


class ExecutorRegistry:
    """Small in-memory registry keyed by executor id."""

    def __init__(self, executors: Iterable[ExecutorDefinition | dict[str, Any]] = ()) -> None:
        self._executors: dict[str, ExecutorDefinition] = {}
        for executor in executors:
            self.register(executor)

    def register(self, executor: ExecutorDefinition | dict[str, Any]) -> ExecutorDefinition:
        definition = validate_executor_definition(executor)
        if definition.id in self._executors:
            raise ExecutorRegistryError(f"duplicate executor id {definition.id!r}")
        self._executors[definition.id] = definition
        return definition

    def get(self, executor_id: str) -> ExecutorDefinition:
        try:
            return self._executors[executor_id]
        except KeyError as exc:
            raise KeyError(f"unknown executor id {executor_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[ExecutorDefinition, ...]:
        if kind is not None and kind not in {"built_in", "external"}:
            raise ExecutorRegistryError("kind must be one of ['built_in', 'external']")
        executors = self._executors.values()
        if kind is not None:
            executors = [executor for executor in executors if executor.kind == kind]
        return tuple(sorted(executors, key=lambda executor: executor.id))

    def validate_all(self) -> tuple[ExecutorDefinition, ...]:
        for executor in self._executors.values():
            validate_executor_definition(executor)
        self._validate_graph_references()
        return self.list()

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        return {"executors": [executor.to_dict() for executor in self.list(kind=kind)]}

    def to_json(self, *, kind: str | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(kind=kind), indent=indent, sort_keys=True)

    def as_mapping(self) -> MappingProxyType[str, ExecutorDefinition]:
        return MappingProxyType(dict(self._executors))

    def _validate_graph_references(self) -> None:
        known_ids = set(self._executors)
        for executor in self._executors.values():
            for dependency in executor.graph.depends_on:
                if dependency not in known_ids:
                    raise ExecutorRegistryError(f"executor {executor.id!r} depends on unknown executor {dependency!r}")
                if dependency == executor.id:
                    raise ExecutorRegistryError(f"executor {executor.id!r} cannot depend on itself")


def load_builtin_executors() -> tuple[ExecutorDefinition, ...]:
    folder_executors: list[ExecutorDefinition] = []
    expected_ids = {f"builtin.{step_name}" for step_name in BUILTIN_STEP_ORDER}
    for path in _builtin_folder_roots():
        folder_executors.extend(load_folder_executors(path))
    by_id = {executor.id: executor for executor in folder_executors if executor.id in expected_ids}
    missing = [f"builtin.{step_name}" for step_name in BUILTIN_STEP_ORDER if f"builtin.{step_name}" not in by_id]
    if missing:
        raise ExecutorRegistryError(f"missing built-in executor folder metadata: {', '.join(missing)}")
    return tuple(by_id[f"builtin.{step_name}"] for step_name in BUILTIN_STEP_ORDER)


def load_curated_executors() -> tuple[ExecutorDefinition, ...]:
    executors: list[ExecutorDefinition] = []
    for path in _curated_manifest_paths():
        executors.append(load_executor_manifest(path))
    for path in _curated_folder_roots():
        executors.extend(load_folder_executors(path))
    return tuple(executors)


def load_bundled_executors() -> tuple[ExecutorDefinition, ...]:
    executors: list[ExecutorDefinition] = []
    for path in _bundled_manifest_paths():
        executors.append(load_executor_manifest(path))
    for path in _bundled_folder_roots():
        executors.extend(load_folder_executors(path))
    return tuple(executors)


def load_default_registry(banodoco_config: BanodocoCatalogConfig | None = None) -> ExecutorRegistry:
    registry = ExecutorRegistry()
    for executor in load_pack_executors():
        registry.register(executor)
    for executor in load_builtin_executors():
        registry.register(executor)
    for executor in load_bundled_executors():
        registry.register(executor)
    for executor in load_curated_executors():
        registry.register(executor)
    for executor in load_project_executors():
        if executor.id not in registry.as_mapping():
            registry.register(executor)
    if banodoco_config is not None and banodoco_config.enabled:
        for executor in load_banodoco_catalog_executors(banodoco_config):
            registry.register(executor)
    registry.validate_all()
    return registry


def load_project_executors() -> tuple[ExecutorDefinition, ...]:
    executors: list[ExecutorDefinition] = []
    for path in _project_folder_roots():
        executors.extend(load_folder_executors(path))
    return tuple(executors)


def load_pack_executors() -> tuple[ExecutorDefinition, ...]:
    executors: list[ExecutorDefinition] = []
    for pack in discover_packs():
        for root in iter_executor_roots(pack):
            for executor in load_folder_executors(root):
                validate_content_id_in_pack(executor.id, pack, content_type="executor")
                executors.append(_attach_pack_metadata(executor, pack.id))
    return tuple(executors)


def _attach_pack_metadata(executor: ExecutorDefinition, pack_id: str) -> ExecutorDefinition:
    metadata = dict(executor.metadata)
    metadata.update({"pack_id": pack_id, "source": "pack"})
    return validate_executor_definition(replace(executor, metadata=metadata))


def _curated_manifest_paths() -> tuple[Path, ...]:
    return _package_manifest_paths(CURATED_PACKAGE, _content_root() / "curated")


def _curated_folder_roots() -> tuple[Path, ...]:
    return _package_folder_roots(CURATED_PACKAGE, _content_root() / "curated")


def _bundled_manifest_paths() -> tuple[Path, ...]:
    return _package_manifest_paths(BUNDLED_PACKAGE, _content_root() / "bundled")


def _bundled_folder_roots() -> tuple[Path, ...]:
    return _package_folder_roots(BUNDLED_PACKAGE, _content_root() / "bundled")


def _builtin_folder_roots() -> tuple[Path, ...]:
    source_root = _content_root()
    return tuple(source_root / step_name for step_name in BUILTIN_STEP_ORDER if (source_root / step_name).is_dir())


def _project_folder_roots() -> tuple[Path, ...]:
    source_root = _content_root()
    skipped = {"__pycache__", "actions", "builtin", "bundled", "curated"}
    if not source_root.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in source_root.iterdir()
            if path.is_dir() and path.name not in skipped and not path.name.startswith(".")
        )
    )


def _content_root() -> Path:
    return Path(__file__).resolve().parents[2] / "executors"


def _package_manifest_paths(package: str, source_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    try:
        package_root = resources.files(package)
        paths.extend(Path(str(item)) for item in package_root.iterdir() if item.name.endswith(".json"))
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        pass

    if paths:
        return tuple(sorted(paths))

    if not source_root.is_dir():
        return ()
    return tuple(sorted(source_root.glob("*.json")))


def _package_folder_roots(package: str, source_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    try:
        package_root = resources.files(package)
        paths.extend(Path(str(item)) for item in package_root.iterdir() if item.is_dir())
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        pass

    if paths:
        return tuple(sorted(paths))

    if not source_root.is_dir():
        return ()
    return tuple(sorted(path for path in source_root.iterdir() if path.is_dir()))


__all__ = [
    "ExecutorRegistry",
    "ExecutorRegistryError",
    "BanodocoCatalogConfig",
    "load_builtin_executors",
    "load_bundled_executors",
    "load_curated_executors",
    "load_project_executors",
    "load_pack_executors",
    "load_default_registry",
]
