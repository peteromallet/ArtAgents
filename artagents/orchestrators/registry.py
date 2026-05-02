"""Registry and discovery helpers for ArtAgents orchestrators."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable

from artagents.executors.registry import ExecutorRegistry, load_default_registry as load_default_executor_registry

from .schema import (
    CachePolicy,
    CommandSpec,
    OrchestratorDefinition,
    OrchestratorValidationError,
    RuntimeSpec,
    load_orchestrator_manifest,
    validate_orchestrator_definition,
)
from .folder import load_folder_orchestrators


BUNDLED_PACKAGE = "artagents.orchestrators.bundled"
CURATED_PACKAGE = "artagents.orchestrators.curated"
HYPE_STEP_ORDER: tuple[str, ...] = (
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


class OrchestratorRegistryError(OrchestratorValidationError):
    """Raised when an orchestrator registry is inconsistent."""


class OrchestratorRegistry:
    """Small in-memory registry keyed by orchestrator id."""

    def __init__(
        self,
        orchestrators: Iterable[OrchestratorDefinition | dict[str, Any]] = (),
        *,
        executor_registry: ExecutorRegistry | None = None,
    ) -> None:
        self._orchestrators: dict[str, OrchestratorDefinition] = {}
        self._executor_registry = executor_registry
        for orchestrator in orchestrators:
            self.register(orchestrator)

    def register(self, orchestrator: OrchestratorDefinition | dict[str, Any]) -> OrchestratorDefinition:
        definition = validate_orchestrator_definition(orchestrator)
        if definition.id in self._orchestrators:
            raise OrchestratorRegistryError(f"duplicate orchestrator id {definition.id!r}")
        self._orchestrators[definition.id] = definition
        return definition

    def get(self, orchestrator_id: str) -> OrchestratorDefinition:
        try:
            return self._orchestrators[orchestrator_id]
        except KeyError as exc:
            raise KeyError(f"unknown orchestrator id {orchestrator_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[OrchestratorDefinition, ...]:
        if kind is not None and kind not in {"built_in", "external"}:
            raise OrchestratorRegistryError("kind must be one of ['built_in', 'external']")
        orchestrators: Iterable[OrchestratorDefinition] = self._orchestrators.values()
        if kind is not None:
            orchestrators = [orchestrator for orchestrator in orchestrators if orchestrator.kind == kind]
        return tuple(sorted(orchestrators, key=lambda orchestrator: orchestrator.id))

    def validate_all(
        self,
        *,
        executor_registry: ExecutorRegistry | None = None,
    ) -> tuple[OrchestratorDefinition, ...]:
        for orchestrator in self._orchestrators.values():
            validate_orchestrator_definition(orchestrator)
        self._validate_child_executors(executor_registry=executor_registry)
        self._validate_child_orchestrators()
        return self.list()

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        return {"orchestrators": [orchestrator.to_dict() for orchestrator in self.list(kind=kind)]}

    def to_json(self, *, kind: str | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(kind=kind), indent=indent, sort_keys=True)

    def as_mapping(self) -> MappingProxyType[str, OrchestratorDefinition]:
        return MappingProxyType(dict(self._orchestrators))

    def _validate_child_executors(self, *, executor_registry: ExecutorRegistry | None) -> None:
        registry = executor_registry or self._executor_registry or load_default_executor_registry()
        known_executor_ids = set(registry.as_mapping())
        for orchestrator in self._orchestrators.values():
            for child_executor in orchestrator.child_executors:
                if child_executor not in known_executor_ids:
                    raise OrchestratorRegistryError(
                        f"orchestrator {orchestrator.id!r} references unknown child executor {child_executor!r}"
                    )

    def _validate_child_orchestrators(self) -> None:
        known_orchestrator_ids = set(self._orchestrators)
        graph: dict[str, tuple[str, ...]] = {}
        for orchestrator in self._orchestrators.values():
            children: list[str] = []
            for child_orchestrator in orchestrator.child_orchestrators:
                if child_orchestrator not in known_orchestrator_ids:
                    raise OrchestratorRegistryError(
                        f"orchestrator {orchestrator.id!r} references unknown child orchestrator {child_orchestrator!r}"
                    )
                if child_orchestrator == orchestrator.id:
                    raise OrchestratorRegistryError(f"orchestrator {orchestrator.id!r} cannot reference itself")
                children.append(child_orchestrator)
            graph[orchestrator.id] = tuple(children)
        self._validate_no_cycles(graph)

    def _validate_no_cycles(self, graph: dict[str, tuple[str, ...]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(orchestrator_id: str) -> None:
            if orchestrator_id in visited:
                return
            if orchestrator_id in visiting:
                cycle = stack[stack.index(orchestrator_id) :] + [orchestrator_id]
                raise OrchestratorRegistryError(f"orchestrator cycle detected: {' -> '.join(cycle)}")
            visiting.add(orchestrator_id)
            stack.append(orchestrator_id)
            for child in graph.get(orchestrator_id, ()):
                visit(child)
            stack.pop()
            visiting.remove(orchestrator_id)
            visited.add(orchestrator_id)

        for orchestrator_id in sorted(graph):
            visit(orchestrator_id)


def load_builtin_orchestrators() -> tuple[OrchestratorDefinition, ...]:
    folder_orchestrators: list[OrchestratorDefinition] = []
    for root in _builtin_folder_roots():
        folder_orchestrators.extend(load_folder_orchestrators(root))
    by_id = {orchestrator.id: orchestrator for orchestrator in folder_orchestrators}
    expected = {"builtin.hype", "builtin.event_talks", "builtin.thumbnail_maker", "builtin.understand"}
    if expected.issubset(by_id):
        return tuple(by_id[orchestrator_id] for orchestrator_id in sorted(expected))
    return (
        _builtin_hype(),
        _builtin_event_talks(),
        _builtin_thumbnail_maker(),
        _builtin_understand(),
    )


def load_curated_orchestrators() -> tuple[OrchestratorDefinition, ...]:
    orchestrators: list[OrchestratorDefinition] = []
    for path in _curated_manifest_paths():
        definition = load_orchestrator_manifest(path)
        if not _is_builtin_definition(definition):
            orchestrators.append(definition)
    for path in _curated_folder_roots():
        orchestrators.extend(definition for definition in load_folder_orchestrators(path) if not _is_builtin_definition(definition))
    return tuple(orchestrators)


def load_bundled_orchestrators() -> tuple[OrchestratorDefinition, ...]:
    orchestrators: list[OrchestratorDefinition] = []
    for path in _bundled_manifest_paths():
        definition = load_orchestrator_manifest(path)
        if not _is_builtin_definition(definition):
            orchestrators.append(definition)
    for path in _bundled_folder_roots():
        orchestrators.extend(definition for definition in load_folder_orchestrators(path) if not _is_builtin_definition(definition))
    return tuple(orchestrators)


def load_default_registry(
    *,
    executor_registry: ExecutorRegistry | None = None,
    banodoco_config: Any | None = None,
) -> OrchestratorRegistry:
    active_executor_registry = executor_registry
    registry = OrchestratorRegistry(executor_registry=active_executor_registry)
    for orchestrator in load_builtin_orchestrators():
        registry.register(orchestrator)
    for orchestrator in load_bundled_orchestrators():
        registry.register(orchestrator)
    for orchestrator in load_curated_orchestrators():
        registry.register(orchestrator)
    registry.validate_all(executor_registry=active_executor_registry)
    return registry


def _builtin_hype() -> OrchestratorDefinition:
    return validate_orchestrator_definition(
        OrchestratorDefinition(
            id="builtin.hype",
            name="Hype Pipeline",
            kind="built_in",
            version="1.0",
            description="Orchestrates the built-in hype editing pipeline.",
            runtime=RuntimeSpec(
                kind="command",
                command=CommandSpec(argv=("{python_exec}", "-m", "artagents", "{orchestrator_args}")),
            ),
            child_executors=tuple(f"builtin.{name}" for name in HYPE_STEP_ORDER),
            cache=CachePolicy(mode="none"),
            metadata={"entrypoint": "python3 -m artagents"},
        )
    )


def _builtin_event_talks() -> OrchestratorDefinition:
    return validate_orchestrator_definition(
        OrchestratorDefinition(
            id="builtin.event_talks",
            name="Event Talks",
            kind="built_in",
            version="1.0",
            description="Orchestrates event-talk template, search, holding-screen, and render commands.",
            runtime=RuntimeSpec(
                kind="command",
                command=CommandSpec(argv=("{python_exec}", "bin/event_talks.py", "{orchestrator_args}")),
            ),
            cache=CachePolicy(mode="none"),
            metadata={
                "entrypoint": "event_talks.py",
                "subcommands": ["ados-sunday-template", "search-transcript", "find-holding-screens", "render"],
            },
        )
    )


def _builtin_thumbnail_maker() -> OrchestratorDefinition:
    return validate_orchestrator_definition(
        OrchestratorDefinition(
            id="builtin.thumbnail_maker",
            name="Thumbnail Maker",
            kind="built_in",
            version="1.0",
            description="Plans source evidence and thumbnail generation candidates for a video/query pair.",
            runtime=RuntimeSpec(
                kind="command",
                command=CommandSpec(argv=("{python_exec}", "bin/thumbnail_maker.py", "{orchestrator_args}")),
            ),
            cache=CachePolicy(mode="none"),
            metadata={"entrypoint": "thumbnail_maker.py"},
        )
    )


def _builtin_understand() -> OrchestratorDefinition:
    return validate_orchestrator_definition(
        OrchestratorDefinition(
            id="builtin.understand",
            name="Understand",
            kind="built_in",
            version="1.0",
            description="Dispatches to audio, visual, or video understanding executors.",
            runtime=RuntimeSpec(
                kind="command",
                command=CommandSpec(argv=("{python_exec}", "-m", "artagents.orchestrators.understand.run", "{orchestrator_args}")),
            ),
            child_executors=("builtin.audio_understand", "builtin.visual_understand", "builtin.video_understand"),
            cache=CachePolicy(mode="none"),
            metadata={"entrypoint": "understand.py"},
        )
    )


def _curated_manifest_paths() -> tuple[Path, ...]:
    return _package_manifest_paths(CURATED_PACKAGE, Path(__file__).with_name("curated"))


def _curated_folder_roots() -> tuple[Path, ...]:
    return _package_folder_roots(CURATED_PACKAGE, Path(__file__).with_name("curated"))


def _bundled_manifest_paths() -> tuple[Path, ...]:
    return _package_manifest_paths(BUNDLED_PACKAGE, Path(__file__).parents[1] / "orchestrators" / "bundled")


def _bundled_folder_roots() -> tuple[Path, ...]:
    return _package_folder_roots(BUNDLED_PACKAGE, Path(__file__).parents[1] / "orchestrators" / "bundled")


def _builtin_folder_roots() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parent
    return tuple(
        path
        for path in (root / "event_talks", root / "hype", root / "thumbnail_maker", root / "understand")
        if path.is_dir()
    )


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


def _is_builtin_definition(orchestrator: OrchestratorDefinition) -> bool:
    return orchestrator.kind == "built_in" or orchestrator.id.startswith("builtin.")


__all__ = [
    "OrchestratorRegistry",
    "OrchestratorRegistryError",
    "load_builtin_orchestrators",
    "load_bundled_orchestrators",
    "load_curated_orchestrators",
    "load_default_registry",
]
