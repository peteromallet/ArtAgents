"""Orchestrator content package with compatibility aliases for framework modules."""

from __future__ import annotations

import sys
from typing import Any

from artagents.core.orchestrator import api, cli, folder, registry, runner, schema

_ALIASES = {
    "api": api,
    "cli": cli,
    "folder": folder,
    "registry": registry,
    "runner": runner,
    "schema": schema,
}

for _name, _module in _ALIASES.items():
    sys.modules[f"{__name__}.{_name}"] = _module

_EXPORTS = {
    "CachePolicy": schema,
    "CommandSpec": schema,
    "IsolationMetadata": schema,
    "OrchestratorDefinition": schema,
    "OrchestratorPlan": runner,
    "OrchestratorPlanStep": runner,
    "OrchestratorRegistry": registry,
    "OrchestratorRegistryError": registry,
    "OrchestratorRunError": runner,
    "OrchestratorRunRequest": runner,
    "OrchestratorRunResult": runner,
    "OrchestratorRunnerError": runner,
    "OrchestratorSpec": api,
    "OrchestratorValidationError": schema,
    "Output": schema,
    "Port": schema,
    "RuntimeSpec": schema,
    "build_orchestrator_command": runner,
    "load_builtin_orchestrators": registry,
    "load_bundled_orchestrators": registry,
    "load_curated_orchestrators": registry,
    "load_default_registry": registry,
    "load_folder_orchestrator": folder,
    "load_folder_orchestrators": folder,
    "load_orchestrator_manifest": schema,
    "orchestrator": api,
    "run_orchestrator": runner,
    "validate_orchestrator_definition": schema,
}

__all__ = sorted([*_ALIASES, *_EXPORTS])


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_EXPORTS[name], name)
