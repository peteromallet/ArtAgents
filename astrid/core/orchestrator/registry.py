"""Registry and discovery helpers for Astrid orchestrators."""

from __future__ import annotations

import json
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Iterable

from astrid.core.executor.registry import ExecutorRegistry, load_default_registry as load_default_executor_registry
from astrid.core.pack import PackResolver, discover_packs, iter_orchestrator_roots, packs_root, validate_content_id_in_pack

from .schema import (
    OrchestratorDefinition,
    OrchestratorValidationError,
    validate_orchestrator_definition,
)
from .folder import load_folder_orchestrators


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


def load_default_registry(
    *,
    executor_registry: ExecutorRegistry | None = None,
    banodoco_config: Any | None = None,
    extra_pack_roots: tuple[str, ...] = (),
    include_installed: bool = True,
) -> OrchestratorRegistry:
    active_executor_registry = executor_registry
    registry = OrchestratorRegistry(executor_registry=active_executor_registry)
    for orchestrator in load_pack_orchestrators(
        extra_pack_roots=extra_pack_roots, include_installed=include_installed
    ):
        registry.register(orchestrator)
    registry.validate_all(executor_registry=active_executor_registry)
    return registry


def load_pack_orchestrators(
    *,
    extra_pack_roots: tuple[str, ...] = (),
    resolver: PackResolver | None = None,
    include_installed: bool = True,
) -> tuple[OrchestratorDefinition, ...]:
    orchestrators: list[OrchestratorDefinition] = []
    seen_ids: dict[str, str] = {}  # orchestrator_id -> pack_id for duplicate detection
    if resolver is None:
        all_roots = [packs_root(), *extra_pack_roots]
        if include_installed:
            from astrid.core.pack_store import installed_pack_roots
            all_roots.extend(installed_pack_roots())
        resolver = PackResolver(*all_roots)
    for pack in resolver.packs:
        for root in resolver.iter_orchestrator_roots(pack):
            for orchestrator in load_folder_orchestrators(root):
                validate_content_id_in_pack(orchestrator.id, pack, content_type="orchestrator")
                if orchestrator.id in seen_ids:
                    raise OrchestratorRegistryError(
                        f"duplicate orchestrator id {orchestrator.id!r} across packs "
                        f"{seen_ids[orchestrator.id]!r} and {pack.id!r}"
                    )
                seen_ids[orchestrator.id] = pack.id
                orchestrators.append(_attach_pack_metadata(orchestrator, pack.id))
    return tuple(orchestrators)


def _attach_pack_metadata(orchestrator: OrchestratorDefinition, pack_id: str) -> OrchestratorDefinition:
    metadata = dict(orchestrator.metadata)
    metadata["source"] = "pack"
    metadata["source_pack"] = pack_id
    return validate_orchestrator_definition(replace(orchestrator, metadata=metadata))


__all__ = [
    "OrchestratorRegistry",
    "OrchestratorRegistryError",
    "load_pack_orchestrators",
    "load_default_registry",
]
