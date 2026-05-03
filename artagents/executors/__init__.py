"""Executor content package with compatibility aliases for framework modules."""

from __future__ import annotations

import sys
from typing import Any

from artagents.core.executor import api, banodoco_catalog, cli, folder, install, registry, runner, schema

_ALIASES = {
    "api": api,
    "banodoco_catalog": banodoco_catalog,
    "cli": cli,
    "folder": folder,
    "install": install,
    "registry": registry,
    "runner": runner,
    "schema": schema,
}

for _name, _module in _ALIASES.items():
    sys.modules[f"{__name__}.{_name}"] = _module

_EXPORTS = {
    "BanodocoCatalogConfig": banodoco_catalog,
    "BanodocoCatalogError": banodoco_catalog,
    "CachePolicy": schema,
    "CommandSpec": schema,
    "ConditionResult": runner,
    "ConditionSpec": schema,
    "ExecutorDefinition": schema,
    "ExecutorInstallError": install,
    "ExecutorInstallPlan": install,
    "ExecutorInstallResult": install,
    "ExecutorOutput": schema,
    "ExecutorPort": schema,
    "ExecutorRegistry": registry,
    "ExecutorRegistryError": registry,
    "ExecutorRunRequest": runner,
    "ExecutorRunResult": runner,
    "ExecutorRunnerError": runner,
    "ExecutorSpec": api,
    "ExecutorValidationError": schema,
    "FolderExecutorError": folder,
    "GraphMetadata": schema,
    "IsolationMetadata": schema,
    "build_executor_command": runner,
    "build_executor_install_plan": install,
    "build_pipeline_context": runner,
    "check_executor_binaries": runner,
    "discover_folder_executor_roots": folder,
    "evaluate_conditions": runner,
    "executor": api,
    "executor_environment_path": install,
    "executor_python_path": install,
    "fetch_git_executor_manifest": install,
    "install_executor": install,
    "load_banodoco_catalog_executors": banodoco_catalog,
    "load_builtin_executors": registry,
    "load_bundled_executors": registry,
    "load_curated_executors": registry,
    "load_default_registry": registry,
    "load_executor_manifest": schema,
    "load_executor_manifest_definitions": schema,
    "load_folder_executor": folder,
    "load_folder_executors": folder,
    "run_executor": runner,
    "validate_executor_definition": schema,
}

__all__ = sorted([*_ALIASES, *_EXPORTS])


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_EXPORTS[name], name)
