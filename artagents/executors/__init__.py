"""Canonical executor APIs.

Executors are ArtAgents execution units: built-in pipeline stages, action
commands, service integrations, and external tools.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BanodocoCatalogConfig": "artagents.executors.banodoco_catalog",
    "BanodocoCatalogError": "artagents.executors.banodoco_catalog",
    "CachePolicy": "artagents.executors.schema",
    "CommandSpec": "artagents.executors.schema",
    "ConditionResult": "artagents.executors.runner",
    "ConditionSpec": "artagents.executors.schema",
    "ExecutorDefinition": "artagents.executors.schema",
    "ExecutorInstallError": "artagents.executors.install",
    "ExecutorInstallPlan": "artagents.executors.install",
    "ExecutorInstallResult": "artagents.executors.install",
    "ExecutorOutput": "artagents.executors.schema",
    "ExecutorPort": "artagents.executors.schema",
    "ExecutorRegistry": "artagents.executors.registry",
    "ExecutorRegistryError": "artagents.executors.registry",
    "ExecutorRunRequest": "artagents.executors.runner",
    "ExecutorRunResult": "artagents.executors.runner",
    "ExecutorRunnerError": "artagents.executors.runner",
    "ExecutorSpec": "artagents.executors.api",
    "ExecutorValidationError": "artagents.executors.schema",
    "FolderExecutorError": "artagents.executors.folder",
    "GraphMetadata": "artagents.executors.schema",
    "IsolationMetadata": "artagents.executors.schema",
    "build_executor_command": "artagents.executors.runner",
    "build_executor_install_plan": "artagents.executors.install",
    "build_pipeline_context": "artagents.executors.runner",
    "check_executor_binaries": "artagents.executors.runner",
    "discover_folder_executor_roots": "artagents.executors.folder",
    "evaluate_conditions": "artagents.executors.runner",
    "executor": "artagents.executors.api",
    "executor_environment_path": "artagents.executors.install",
    "executor_python_path": "artagents.executors.install",
    "fetch_git_executor_manifest": "artagents.executors.install",
    "install_executor": "artagents.executors.install",
    "load_banodoco_catalog_executors": "artagents.executors.banodoco_catalog",
    "load_builtin_executors": "artagents.executors.registry",
    "load_bundled_executors": "artagents.executors.registry",
    "load_curated_executors": "artagents.executors.registry",
    "load_default_registry": "artagents.executors.registry",
    "load_executor_manifest": "artagents.executors.schema",
    "load_executor_manifest_definitions": "artagents.executors.schema",
    "load_folder_executor": "artagents.executors.folder",
    "load_folder_executors": "artagents.executors.folder",
    "run_executor": "artagents.executors.runner",
    "validate_executor_definition": "artagents.executors.schema",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name])
    return getattr(module, name)
