"""Folder-based orchestrator discovery and metadata extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .schema import (
    OrchestratorDefinition,
    OrchestratorValidationError,
    load_orchestrator_manifest,
    validate_orchestrator_definition,
)


_RESULT_PREFIX = "__ARTAGENTS_ORCHESTRATOR_METADATA__="
_MANIFEST_NAMES = ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json")


class FolderOrchestratorError(OrchestratorValidationError):
    """Raised when a folder orchestrator cannot be discovered or extracted."""


def discover_folder_orchestrator_roots(root: str | Path) -> tuple[Path, ...]:
    """Return folders under `root` that contain orchestrator metadata."""

    search_root = Path(root)
    if not search_root.is_dir():
        return ()
    roots = {path.parent.resolve() for path in search_root.rglob("orchestrator.py") if _is_orchestrator_file(path)}
    for manifest_name in _MANIFEST_NAMES:
        roots.update(path.parent.resolve() for path in search_root.rglob(manifest_name) if _is_orchestrator_file(path))
    return tuple(sorted(roots))


def load_folder_orchestrators(root: str | Path) -> tuple[OrchestratorDefinition, ...]:
    """Load every folder orchestrator below `root` through the subprocess extractor."""

    orchestrators: list[OrchestratorDefinition] = []
    for orchestrator_root in discover_folder_orchestrator_roots(root):
        orchestrators.extend(_load_folder_orchestrator_definitions(orchestrator_root))
    return tuple(orchestrators)


def load_folder_orchestrator(orchestrator_root: str | Path) -> OrchestratorDefinition:
    """Extract and validate a single folder orchestrator without importing it here."""

    definitions = _load_folder_orchestrator_definitions(orchestrator_root)
    if len(definitions) != 1:
        root = Path(orchestrator_root).expanduser().resolve()
        raise FolderOrchestratorError(f"folder orchestrator must define exactly one orchestrator for load_folder_orchestrator(): {root}")
    return definitions[0]


def _load_folder_orchestrator_definitions(orchestrator_root: str | Path) -> tuple[OrchestratorDefinition, ...]:
    root = Path(orchestrator_root).expanduser().resolve()
    manifest_path = _manifest_path(root)
    if manifest_path is not None:
        try:
            definition = load_orchestrator_manifest(manifest_path)
        except OrchestratorValidationError as exc:
            raise FolderOrchestratorError(f"{manifest_path}: {exc}") from exc
        return (_attach_folder_metadata(definition, root, manifest_path),)

    orchestrator_path = root / "orchestrator.py"
    if not orchestrator_path.is_file():
        raise FolderOrchestratorError(f"folder orchestrator is missing orchestrator.py or orchestrator manifest: {root}")

    env = dict(os.environ)
    parent_paths = [str(Path.cwd()) if path == "" else path for path in sys.path]
    env["PYTHONPATH"] = os.pathsep.join(parent_paths + [env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-c", _EXTRACT_SCRIPT, str(orchestrator_path)],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise FolderOrchestratorError(f"failed to extract folder orchestrator metadata from {orchestrator_path}{suffix}")

    payload = _extract_payload(completed.stdout, orchestrator_path)
    try:
        raw_definitions = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FolderOrchestratorError(f"folder orchestrator extractor emitted invalid JSON for {orchestrator_path}: {exc.msg}") from exc

    if not isinstance(raw_definitions, list):
        raise FolderOrchestratorError(f"folder orchestrator extractor emitted non-list metadata for {orchestrator_path}")

    definitions: list[OrchestratorDefinition] = []
    try:
        for raw_definition in raw_definitions:
            definition = validate_orchestrator_definition(raw_definition)
            definitions.append(_attach_folder_metadata(definition, root, orchestrator_path))
    except OrchestratorValidationError as exc:
        raise FolderOrchestratorError(f"{orchestrator_path}: {exc}") from exc

    if not definitions:
        raise FolderOrchestratorError(f"folder orchestrator extractor emitted no metadata for {orchestrator_path}")
    return tuple(definitions)


def _is_orchestrator_file(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts


def _extract_payload(stdout: str, orchestrator_path: Path) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            return line[len(_RESULT_PREFIX) :]
    raise FolderOrchestratorError(f"folder orchestrator extractor did not emit metadata for {orchestrator_path}")


def _manifest_path(root: Path) -> Path | None:
    for manifest_name in _MANIFEST_NAMES:
        candidate = root / manifest_name
        if candidate.is_file():
            return candidate
    return None


def _attach_folder_metadata(orchestrator: OrchestratorDefinition, root: Path, metadata_path: Path) -> OrchestratorDefinition:
    metadata = dict(orchestrator.metadata)
    metadata.update(
        {
            "source": "folder",
            "orchestrator_root": str(root),
            "folder_id": root.name,
        }
    )
    if metadata_path.name in _MANIFEST_NAMES:
        metadata["manifest_file"] = str(metadata_path)
    else:
        metadata["orchestrator_file"] = str(metadata_path)
    for filename, key in (
        ("requirements.txt", "requirements_file"),
        ("pyproject.toml", "pyproject_file"),
        ("SKILL.md", "skill_file"),
    ):
        candidate = root / filename
        if candidate.is_file():
            metadata[key] = str(candidate)
    return validate_orchestrator_definition(replace(orchestrator, metadata=metadata))


_EXTRACT_SCRIPT = r"""
import json
import runpy
import sys
import traceback

from artagents.orchestrators.api import OrchestratorSpec
from artagents.orchestrators.schema import OrchestratorDefinition, validate_orchestrator_definition

PREFIX = "__ARTAGENTS_ORCHESTRATOR_METADATA__="


def normalize(raw):
    if isinstance(raw, OrchestratorSpec):
        return raw.to_definition()
    if isinstance(raw, OrchestratorDefinition):
        return validate_orchestrator_definition(raw)
    if isinstance(raw, dict):
        return validate_orchestrator_definition(raw)
    to_definition = getattr(raw, "to_definition", None)
    if callable(to_definition):
        return validate_orchestrator_definition(to_definition())
    raise TypeError("top-level orchestrator or ORCHESTRATOR must be OrchestratorSpec, OrchestratorDefinition, dict, or expose to_definition()")


def normalize_many(raw_orchestrators):
    if not isinstance(raw_orchestrators, (list, tuple)):
        raise TypeError("top-level ORCHESTRATORS must be a list or tuple of orchestrator metadata")
    return [normalize(raw_orchestrator) for raw_orchestrator in raw_orchestrators]


def decorated_definitions(namespace):
    definitions = []
    for name in sorted(namespace):
        value = namespace[name]
        if name.startswith("__"):
            continue
        raw_orchestrator = getattr(value, "ORCHESTRATOR", None) or getattr(value, "orchestrator", None)
        if raw_orchestrator is not None:
            definitions.append(normalize(raw_orchestrator))
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
    namespace = runpy.run_path(sys.argv[1], run_name="__artagents_folder_orchestrator__")
    if "ORCHESTRATORS" in namespace:
        definitions = normalize_many(namespace["ORCHESTRATORS"])
    elif "ORCHESTRATOR" in namespace:
        definitions = [normalize(namespace["ORCHESTRATOR"])]
    elif "orchestrator" in namespace and (definition := normalize_optional(namespace["orchestrator"])) is not None:
        definitions = [definition]
    else:
        definitions = decorated_definitions(namespace)
        if not definitions:
            raise ValueError("folder orchestrator must define top-level orchestrator or ORCHESTRATOR, ORCHESTRATORS, or decorated callables")
    package_id = namespace.get("PACKAGE_ID")
    print(PREFIX + json.dumps([definition_payload(definition, package_id) for definition in definitions], sort_keys=True))
except Exception:
    traceback.print_exc(file=sys.stderr)
    raise SystemExit(1)
"""


__all__ = [
    "FolderOrchestratorError",
    "discover_folder_orchestrator_roots",
    "load_folder_orchestrator",
    "load_folder_orchestrators",
]
