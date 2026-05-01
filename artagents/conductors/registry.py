"""Registry and discovery helpers for ArtAgents conductors."""

from __future__ import annotations

import json
from importlib import resources
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable

from .banodoco_catalog import BanodocoCatalogConfig, load_banodoco_catalog_conductors
from artagents.performers.registry import PerformerRegistry, load_default_registry as load_default_performer_registry

from .folder import load_folder_conductors
from .schema import (
    ConductorDefinition,
    ConductorValidationError,
    load_conductor_manifest,
    validate_conductor_definition,
)


CURATED_PACKAGE = "artagents.conductors.curated"


class ConductorRegistryError(ConductorValidationError):
    """Raised when a conductor registry is inconsistent."""


class ConductorRegistry:
    """Small in-memory registry keyed by conductor id."""

    def __init__(
        self,
        conductors: Iterable[ConductorDefinition | dict[str, Any]] = (),
        *,
        performer_registry: PerformerRegistry | None = None,
    ) -> None:
        self._conductors: dict[str, ConductorDefinition] = {}
        self._performer_registry = performer_registry
        for conductor in conductors:
            self.register(conductor)

    def register(self, conductor: ConductorDefinition | dict[str, Any]) -> ConductorDefinition:
        definition = validate_conductor_definition(conductor)
        if definition.id in self._conductors:
            raise ConductorRegistryError(f"duplicate conductor id {definition.id!r}")
        self._conductors[definition.id] = definition
        return definition

    def get(self, conductor_id: str) -> ConductorDefinition:
        try:
            return self._conductors[conductor_id]
        except KeyError as exc:
            raise KeyError(f"unknown conductor id {conductor_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[ConductorDefinition, ...]:
        if kind is not None and kind not in {"built_in", "external"}:
            raise ConductorRegistryError("kind must be one of ['built_in', 'external']")
        conductors: Iterable[ConductorDefinition] = self._conductors.values()
        if kind is not None:
            conductors = [conductor for conductor in conductors if conductor.kind == kind]
        return tuple(sorted(conductors, key=lambda conductor: conductor.id))

    def validate_all(
        self,
        *,
        performer_registry: PerformerRegistry | None = None,
    ) -> tuple[ConductorDefinition, ...]:
        for conductor in self._conductors.values():
            validate_conductor_definition(conductor)
        self._validate_child_performers(performer_registry=performer_registry)
        self._validate_child_conductors()
        return self.list()

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        return {"conductors": [conductor.to_dict() for conductor in self.list(kind=kind)]}

    def to_json(self, *, kind: str | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(kind=kind), indent=indent, sort_keys=True)

    def as_mapping(self) -> MappingProxyType[str, ConductorDefinition]:
        return MappingProxyType(dict(self._conductors))

    def _validate_child_performers(self, *, performer_registry: PerformerRegistry | None) -> None:
        registry = performer_registry or self._performer_registry or load_default_performer_registry()
        known_performer_ids = set(registry.as_mapping())
        for conductor in self._conductors.values():
            for child_performer in conductor.child_performers:
                if child_performer not in known_performer_ids:
                    raise ConductorRegistryError(
                        f"conductor {conductor.id!r} references unknown child performer {child_performer!r}"
                    )

    def _validate_child_conductors(self) -> None:
        known_conductor_ids = set(self._conductors)
        graph: dict[str, tuple[str, ...]] = {}
        for conductor in self._conductors.values():
            children: list[str] = []
            for child_conductor in conductor.child_conductors:
                if child_conductor not in known_conductor_ids:
                    raise ConductorRegistryError(
                        f"conductor {conductor.id!r} references unknown child conductor {child_conductor!r}"
                    )
                if child_conductor == conductor.id:
                    raise ConductorRegistryError(f"conductor {conductor.id!r} cannot reference itself as a child conductor")
                children.append(child_conductor)
            graph[conductor.id] = tuple(children)
        self._validate_no_cycles(graph)

    def _validate_no_cycles(self, graph: dict[str, tuple[str, ...]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(conductor_id: str) -> None:
            if conductor_id in visited:
                return
            if conductor_id in visiting:
                cycle = stack[stack.index(conductor_id) :] + [conductor_id]
                raise ConductorRegistryError(f"conductor cycle detected: {' -> '.join(cycle)}")
            visiting.add(conductor_id)
            stack.append(conductor_id)
            for child in graph.get(conductor_id, ()):
                visit(child)
            stack.pop()
            visiting.remove(conductor_id)
            visited.add(conductor_id)

        for conductor_id in sorted(graph):
            visit(conductor_id)


def load_builtin_conductors() -> tuple[ConductorDefinition, ...]:
    from artagents.conductors.curated.event_talks.conductor import conductor as event_talks_conductor
    from artagents.conductors.curated.hype.conductor import conductor as hype_conductor
    from artagents.conductors.curated.thumbnail_maker.conductor import conductor as thumbnail_maker_conductor

    return (
        _attach_builtin_metadata(_to_definition(hype_conductor), legacy_entrypoint="pipeline.py"),
        _attach_builtin_metadata(_to_definition(event_talks_conductor), legacy_entrypoint="event_talks.py"),
        _attach_builtin_metadata(_to_definition(thumbnail_maker_conductor), legacy_entrypoint="thumbnail_maker.py"),
    )


def load_curated_conductors() -> tuple[ConductorDefinition, ...]:
    conductors: list[ConductorDefinition] = []
    for path in _curated_manifest_paths():
        definition = load_conductor_manifest(path)
        if not _is_builtin_definition(definition):
            conductors.append(definition)
    for path in _curated_folder_roots():
        conductors.extend(definition for definition in load_folder_conductors(path) if not _is_builtin_definition(definition))
    return tuple(conductors)


def load_default_registry(
    *,
    performer_registry: PerformerRegistry | None = None,
    banodoco_config: BanodocoCatalogConfig | None = None,
) -> ConductorRegistry:
    registry = ConductorRegistry(performer_registry=performer_registry)
    for conductor in load_builtin_conductors():
        registry.register(conductor)
    for conductor in load_curated_conductors():
        registry.register(conductor)
    if banodoco_config is not None and banodoco_config.enabled:
        for conductor in load_banodoco_catalog_conductors(banodoco_config):
            registry.register(conductor)
    registry.validate_all(performer_registry=performer_registry)
    return registry


def _curated_manifest_paths() -> tuple[Path, ...]:
    paths: list[Path] = []
    try:
        curated_root = resources.files(CURATED_PACKAGE)
        paths.extend(Path(str(item)) for item in curated_root.iterdir() if item.name.endswith(".json"))
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        pass

    if paths:
        return tuple(sorted(paths))

    source_root = Path(__file__).with_name("curated")
    if not source_root.is_dir():
        return ()
    return tuple(sorted(source_root.glob("*.json")))


def _curated_folder_roots() -> tuple[Path, ...]:
    paths: list[Path] = []
    try:
        curated_root = resources.files(CURATED_PACKAGE)
        paths.extend(Path(str(item)) for item in curated_root.iterdir() if item.is_dir())
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        pass

    if paths:
        return tuple(sorted(paths))

    source_root = Path(__file__).with_name("curated")
    if not source_root.is_dir():
        return ()
    return tuple(sorted(path for path in source_root.iterdir() if path.is_dir()))


def _to_definition(raw: Any) -> ConductorDefinition:
    if isinstance(raw, ConductorDefinition):
        return validate_conductor_definition(raw)
    to_definition = getattr(raw, "to_definition", None)
    if callable(to_definition):
        return validate_conductor_definition(to_definition())
    return validate_conductor_definition(raw)


def _attach_builtin_metadata(conductor: ConductorDefinition, *, legacy_entrypoint: str) -> ConductorDefinition:
    metadata = dict(conductor.metadata)
    metadata.update({"source": "built_in", "legacy_entrypoint": legacy_entrypoint})
    return validate_conductor_definition(replace(conductor, metadata=metadata))


def _is_builtin_definition(conductor: ConductorDefinition) -> bool:
    return conductor.kind == "built_in" or conductor.id.startswith("builtin.")


__all__ = [
    "ConductorRegistry",
    "ConductorRegistryError",
    "load_builtin_conductors",
    "load_curated_conductors",
    "load_default_registry",
]
