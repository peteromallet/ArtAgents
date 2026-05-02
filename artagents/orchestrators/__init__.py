"""Canonical orchestration APIs."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "CachePolicy": "artagents.orchestrators.schema",
    "CommandSpec": "artagents.orchestrators.schema",
    "IsolationMetadata": "artagents.orchestrators.schema",
    "OrchestratorDefinition": "artagents.orchestrators.schema",
    "OrchestratorPlan": "artagents.orchestrators.runner",
    "OrchestratorPlanStep": "artagents.orchestrators.runner",
    "OrchestratorRegistry": "artagents.orchestrators.registry",
    "OrchestratorRegistryError": "artagents.orchestrators.registry",
    "OrchestratorRunError": "artagents.orchestrators.runner",
    "OrchestratorRunRequest": "artagents.orchestrators.runner",
    "OrchestratorRunResult": "artagents.orchestrators.runner",
    "OrchestratorRunnerError": "artagents.orchestrators.runner",
    "OrchestratorSpec": "artagents.orchestrators.api",
    "OrchestratorValidationError": "artagents.orchestrators.schema",
    "Output": "artagents.orchestrators.schema",
    "Port": "artagents.orchestrators.schema",
    "RuntimeSpec": "artagents.orchestrators.schema",
    "build_orchestrator_command": "artagents.orchestrators.runner",
    "load_builtin_orchestrators": "artagents.orchestrators.registry",
    "load_bundled_orchestrators": "artagents.orchestrators.registry",
    "load_curated_orchestrators": "artagents.orchestrators.registry",
    "load_default_registry": "artagents.orchestrators.registry",
    "load_folder_orchestrator": "artagents.orchestrators.folder",
    "load_folder_orchestrators": "artagents.orchestrators.folder",
    "load_orchestrator_manifest": "artagents.orchestrators.schema",
    "orchestrator": "artagents.orchestrators.api",
    "run_orchestrator": "artagents.orchestrators.runner",
    "validate_orchestrator_definition": "artagents.orchestrators.schema",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name])
    return getattr(module, name)
