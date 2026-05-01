"""Registry and discovery helpers for ArtAgents performers."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable

from .banodoco_catalog import BanodocoCatalogConfig, load_banodoco_catalog_performers
from .builtin import builtin_performers
from .folder import load_folder_performers
from .schema import (
    PerformerDefinition,
    PerformerPort,
    PerformerValidationError,
    CachePolicy,
    load_performer_manifest,
    validate_performer_definition,
)


CURATED_PACKAGE = "artagents.performers.curated"


class PerformerRegistryError(PerformerValidationError):
    """Raised when a performer registry is inconsistent."""


class PerformerRegistry:
    """Small in-memory registry keyed by performer id."""

    def __init__(self, performers: Iterable[PerformerDefinition | dict[str, Any]] = ()) -> None:
        self._performers: dict[str, PerformerDefinition] = {}
        for performer in performers:
            self.register(performer)

    def register(self, performer: PerformerDefinition | dict[str, Any]) -> PerformerDefinition:
        definition = validate_performer_definition(performer)
        if definition.id in self._performers:
            raise PerformerRegistryError(f"duplicate performer id {definition.id!r}")
        self._performers[definition.id] = definition
        return definition

    def get(self, performer_id: str) -> PerformerDefinition:
        try:
            return self._performers[performer_id]
        except KeyError as exc:
            raise KeyError(f"unknown performer id {performer_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[PerformerDefinition, ...]:
        if kind is not None and kind not in {"built_in", "external"}:
            raise PerformerRegistryError("kind must be one of ['built_in', 'external']")
        performers = self._performers.values()
        if kind is not None:
            performers = [performer for performer in performers if performer.kind == kind]
        return tuple(sorted(performers, key=lambda performer: performer.id))

    def validate_all(self) -> tuple[PerformerDefinition, ...]:
        for performer in self._performers.values():
            validate_performer_definition(performer)
        self._validate_graph_references()
        return self.list()

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        return {"performers": [performer.to_dict() for performer in self.list(kind=kind)]}

    def to_json(self, *, kind: str | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(kind=kind), indent=indent, sort_keys=True)

    def as_mapping(self) -> MappingProxyType[str, PerformerDefinition]:
        return MappingProxyType(dict(self._performers))

    def _validate_graph_references(self) -> None:
        known_ids = set(self._performers)
        for performer in self._performers.values():
            for dependency in performer.graph.depends_on:
                if dependency not in known_ids:
                    raise PerformerRegistryError(f"performer {performer.id!r} depends on unknown performer {dependency!r}")
                if dependency == performer.id:
                    raise PerformerRegistryError(f"performer {performer.id!r} cannot depend on itself")


def load_builtin_performers() -> tuple[PerformerDefinition, ...]:
    return builtin_performers()


def load_curated_performers() -> tuple[PerformerDefinition, ...]:
    performers: list[PerformerDefinition] = []
    for path in _curated_manifest_paths():
        performers.append(load_performer_manifest(path))
    for path in _curated_folder_roots():
        performers.extend(load_folder_performers(path))
    return tuple(performers)


def load_default_registry(banodoco_config: BanodocoCatalogConfig | None = None) -> PerformerRegistry:
    registry = PerformerRegistry()
    for performer in load_builtin_performers():
        registry.register(performer)
    for performer in load_curated_performers():
        registry.register(performer)
    for performer in load_service_performers():
        registry.register(performer)
    if banodoco_config is not None and banodoco_config.enabled:
        for performer in load_banodoco_catalog_performers(banodoco_config):
            registry.register(performer)
    registry.validate_all()
    return registry


def load_service_performers() -> tuple[PerformerDefinition, ...]:
    return (
        PerformerDefinition(
            id="upload.youtube",
            name="Upload to YouTube",
            kind="built_in",
            version="1.0",
            description="Upload a finished video to YouTube via the shared banodoco-social Zapier integration.",
            inputs=(
                PerformerPort("video_url", "string", description="Reachable http(s) URL for the finished video."),
                PerformerPort("title", "string", description="YouTube video title."),
                PerformerPort("description", "string", description="YouTube video description."),
                PerformerPort("tag", "string", required=False, description="YouTube tag. May be repeated."),
                PerformerPort("tags", "string", required=False, description="Comma-separated YouTube tags."),
                PerformerPort("privacy_status", "string", required=False, description="private, unlisted, or public."),
                PerformerPort("playlist_id", "string", required=False, description="Optional YouTube playlist ID."),
                PerformerPort("made_for_kids", "boolean", required=False, description="Mark the video as made for kids."),
            ),
            cache=CachePolicy(mode="none"),
            metadata={
                "backend": "banodoco-social",
                "command": "pipeline.py upload-youtube",
                "requires_reachable_video_url": True,
            },
        ),
    )


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


__all__ = [
    "PerformerRegistry",
    "PerformerRegistryError",
    "BanodocoCatalogConfig",
    "load_builtin_performers",
    "load_curated_performers",
    "load_service_performers",
    "load_default_registry",
]
