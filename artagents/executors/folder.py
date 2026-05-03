"""Folder-based executor discovery and metadata extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .schema import (
    ExecutorDefinition,
    ExecutorValidationError,
    load_executor_manifest_definitions,
    validate_executor_definition,
)


_RESULT_PREFIX = "__ARTAGENTS_EXECUTOR_METADATA__="


class FolderExecutorError(ExecutorValidationError):
    """Raised when a folder executor cannot be discovered or extracted."""


_MANIFEST_FILENAMES = ("executor.yaml", "executor.yml", "executor.json")


def discover_folder_executor_roots(root: str | Path) -> tuple[Path, ...]:
    """Return folders under `root` that contain an executor manifest or executor.py."""

    search_root = Path(root)
    if not search_root.is_dir():
        return ()
    roots = {
        path.parent.resolve()
        for path in search_root.rglob("*")
        if _is_executor_folder_file(path)
    }
    return tuple(sorted(roots))


def load_folder_executors(root: str | Path) -> tuple[ExecutorDefinition, ...]:
    """Load every folder executor below `root` through the subprocess extractor."""

    executors: list[ExecutorDefinition] = []
    for executor_root in discover_folder_executor_roots(root):
        executors.extend(_load_folder_executor_definitions(executor_root))
    return tuple(executors)


def load_folder_executor(executor_root: str | Path) -> ExecutorDefinition:
    """Extract and validate a single folder executor without importing it here."""

    definitions = _load_folder_executor_definitions(executor_root)
    if len(definitions) != 1:
        root = Path(executor_root).expanduser().resolve()
        raise FolderExecutorError(f"folder executor must define exactly one executor for load_folder_executor(): {root}")
    return definitions[0]


def _load_folder_executor_definitions(executor_root: str | Path) -> tuple[ExecutorDefinition, ...]:
    """Extract and validate every executor definition from one folder executor package."""

    root = Path(executor_root).expanduser().resolve()
    manifest_path = _executor_manifest_path(root)
    if manifest_path is not None:
        definitions: list[ExecutorDefinition] = []
        try:
            for definition in load_executor_manifest_definitions(manifest_path):
                definitions.append(_attach_folder_metadata(definition, root, manifest_path))
        except ExecutorValidationError as exc:
            raise FolderExecutorError(f"{manifest_path}: {exc}") from exc
        if not definitions:
            raise FolderExecutorError(f"folder executor manifest emitted no metadata for {manifest_path}")
        return tuple(definitions)

    executor_path = root / "executor.py"
    if not executor_path.is_file():
        raise FolderExecutorError(f"folder executor is missing executor.yaml or executor.py: {root}")

    env = dict(os.environ)
    parent_paths = [str(Path.cwd()) if path == "" else path for path in sys.path]
    env["PYTHONPATH"] = os.pathsep.join(parent_paths + [env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-c", _EXTRACT_SCRIPT, str(executor_path)],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise FolderExecutorError(f"failed to extract folder executor metadata from {executor_path}{suffix}")

    payload = _extract_payload(completed.stdout, executor_path)
    try:
        raw_definitions = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FolderExecutorError(f"folder executor extractor emitted invalid JSON for {executor_path}: {exc.msg}") from exc

    if not isinstance(raw_definitions, list):
        raise FolderExecutorError(f"folder executor extractor emitted non-list metadata for {executor_path}")

    definitions: list[ExecutorDefinition] = []
    try:
        for raw_definition in raw_definitions:
            definition = validate_executor_definition(raw_definition)
            definitions.append(_attach_folder_metadata(definition, root, executor_path))
    except ExecutorValidationError as exc:
        raise FolderExecutorError(f"{executor_path}: {exc}") from exc

    if not definitions:
        raise FolderExecutorError(f"folder executor extractor emitted no metadata for {executor_path}")
    return tuple(definitions)


def _is_executor_folder_file(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts and (path.name in _MANIFEST_FILENAMES or path.name == "executor.py")


def _executor_manifest_path(root: Path) -> Path | None:
    for filename in _MANIFEST_FILENAMES:
        candidate = root / filename
        if candidate.is_file():
            return candidate
    return None


def _extract_payload(stdout: str, executor_path: Path) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            return line[len(_RESULT_PREFIX) :]
    raise FolderExecutorError(f"folder executor extractor did not emit metadata for {executor_path}")


def _attach_folder_metadata(executor: ExecutorDefinition, root: Path, source_path: Path) -> ExecutorDefinition:
    metadata = dict(executor.metadata)
    metadata.update(
        {
            "source": "folder",
            "executor_root": str(root),
            "folder_id": root.name,
        }
    )
    if source_path.name in _MANIFEST_FILENAMES:
        metadata["manifest_file"] = str(source_path)
    else:
        metadata["executor_file"] = str(source_path)
    for filename, key in (
        ("requirements.txt", "requirements_file"),
        ("pyproject.toml", "pyproject_file"),
        ("STAGE.md", "stage_file"),
    ):
        candidate = root / filename
        if candidate.is_file():
            metadata[key] = str(candidate)
    for dirname, dir_key, files_key in (
        ("assets", "assets_dir", "asset_files"),
        ("guides", "guides_dir", "guide_files"),
    ):
        candidate_dir = root / dirname
        if candidate_dir.is_dir():
            metadata[dir_key] = str(candidate_dir)
            metadata[files_key] = [
                str(path)
                for path in sorted(candidate_dir.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            ]
    return validate_executor_definition(replace(executor, metadata=metadata))


_EXTRACT_SCRIPT = r"""
import json
import runpy
import sys
import traceback

from artagents.executors.api import ExecutorSpec
from artagents.executors.schema import ExecutorDefinition, validate_executor_definition

PREFIX = "__ARTAGENTS_EXECUTOR_METADATA__="


def normalize(raw):
    if isinstance(raw, ExecutorSpec):
        return raw.to_definition()
    if isinstance(raw, ExecutorDefinition):
        return validate_executor_definition(raw)
    if isinstance(raw, dict):
        return validate_executor_definition(raw)
    to_definition = getattr(raw, "to_definition", None)
    if callable(to_definition):
        return validate_executor_definition(to_definition())
    raise TypeError("top-level executor or EXECUTOR must be ExecutorSpec, ExecutorDefinition, dict, or expose to_definition()")


def normalize_many(raw_executors):
    if not isinstance(raw_executors, (list, tuple)):
        raise TypeError("top-level EXECUTORS must be a list or tuple of executor metadata")
    return [normalize(raw_executor) for raw_executor in raw_executors]


def decorated_definitions(namespace):
    definitions = []
    for name in sorted(namespace):
        value = namespace[name]
        if name.startswith("__"):
            continue
        raw_executor = getattr(value, "EXECUTOR", None) or getattr(value, "executor", None)
        if raw_executor is not None:
            definitions.append(normalize(raw_executor))
    return definitions


def normalize_optional(raw):
    try:
        return normalize(raw)
    except TypeError:
        return None


def compact(value):
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if item is not None and item != ""}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def definition_payload(definition, package_id):
    payload = definition.to_dict()
    if package_id is not None:
        if not isinstance(package_id, str) or not package_id:
            raise TypeError("top-level PACKAGE_ID must be a non-empty string")
        metadata = dict(payload.get("metadata") or {})
        metadata["package_id"] = package_id
        payload["metadata"] = metadata
    return compact(payload)


try:
    namespace = runpy.run_path(sys.argv[1], run_name="__artagents_folder_executor__")
    if "EXECUTORS" in namespace:
        definitions = normalize_many(namespace["EXECUTORS"])
    elif "EXECUTOR" in namespace:
        definitions = [normalize(namespace["EXECUTOR"])]
    elif "executor" in namespace and (definition := normalize_optional(namespace["executor"])) is not None:
        definitions = [definition]
    else:
        definitions = decorated_definitions(namespace)
        if not definitions:
            raise ValueError("folder executor must define top-level executor or EXECUTOR, EXECUTORS, or decorated callables")
    package_id = namespace.get("PACKAGE_ID")
    print(PREFIX + json.dumps([definition_payload(definition, package_id) for definition in definitions], sort_keys=True))
except Exception:
    traceback.print_exc(file=sys.stderr)
    raise SystemExit(1)
"""


__all__ = [
    "FolderExecutorError",
    "discover_folder_executor_roots",
    "load_folder_executor",
    "load_folder_executors",
]
