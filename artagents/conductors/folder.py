"""Folder-based conductor discovery and metadata extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .schema import ConductorDefinition, ConductorValidationError, validate_conductor_definition


_RESULT_PREFIX = "__ARTAGENTS_CONDUCTOR_METADATA__="


class FolderConductorError(ConductorValidationError):
    """Raised when a folder conductor cannot be discovered or extracted."""


def discover_folder_conductor_roots(root: str | Path) -> tuple[Path, ...]:
    """Return folders under `root` that contain a `conductor.py` file."""

    search_root = Path(root)
    if not search_root.is_dir():
        return ()
    roots = {path.parent.resolve() for path in search_root.rglob("conductor.py") if _is_conductor_file(path)}
    return tuple(sorted(roots))


def load_folder_conductors(root: str | Path) -> tuple[ConductorDefinition, ...]:
    """Load every folder conductor below `root` through the subprocess extractor."""

    conductors: list[ConductorDefinition] = []
    for conductor_root in discover_folder_conductor_roots(root):
        conductors.extend(_load_folder_conductor_definitions(conductor_root))
    return tuple(conductors)


def load_folder_conductor(conductor_root: str | Path) -> ConductorDefinition:
    """Extract and validate a single folder conductor without importing it here."""

    definitions = _load_folder_conductor_definitions(conductor_root)
    if len(definitions) != 1:
        root = Path(conductor_root).expanduser().resolve()
        raise FolderConductorError(f"folder conductor must define exactly one conductor for load_folder_conductor(): {root}")
    return definitions[0]


def _load_folder_conductor_definitions(conductor_root: str | Path) -> tuple[ConductorDefinition, ...]:
    root = Path(conductor_root).expanduser().resolve()
    conductor_path = root / "conductor.py"
    if not conductor_path.is_file():
        raise FolderConductorError(f"folder conductor is missing conductor.py: {root}")

    env = dict(os.environ)
    parent_paths = [str(Path.cwd()) if path == "" else path for path in sys.path]
    env["PYTHONPATH"] = os.pathsep.join(parent_paths + [env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-c", _EXTRACT_SCRIPT, str(conductor_path)],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise FolderConductorError(f"failed to extract folder conductor metadata from {conductor_path}{suffix}")

    payload = _extract_payload(completed.stdout, conductor_path)
    try:
        raw_definitions = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FolderConductorError(f"folder conductor extractor emitted invalid JSON for {conductor_path}: {exc.msg}") from exc

    if not isinstance(raw_definitions, list):
        raise FolderConductorError(f"folder conductor extractor emitted non-list metadata for {conductor_path}")

    definitions: list[ConductorDefinition] = []
    try:
        for raw_definition in raw_definitions:
            definition = validate_conductor_definition(raw_definition)
            definitions.append(_attach_folder_metadata(definition, root, conductor_path))
    except ConductorValidationError as exc:
        raise FolderConductorError(f"{conductor_path}: {exc}") from exc

    if not definitions:
        raise FolderConductorError(f"folder conductor extractor emitted no metadata for {conductor_path}")
    return tuple(definitions)


def _is_conductor_file(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts


def _extract_payload(stdout: str, conductor_path: Path) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            return line[len(_RESULT_PREFIX) :]
    raise FolderConductorError(f"folder conductor extractor did not emit metadata for {conductor_path}")


def _attach_folder_metadata(conductor: ConductorDefinition, root: Path, conductor_path: Path) -> ConductorDefinition:
    metadata = dict(conductor.metadata)
    metadata.update(
        {
            "source": "folder",
            "conductor_root": str(root),
            "conductor_file": str(conductor_path),
            "folder_id": root.name,
        }
    )
    for filename, key in (
        ("requirements.txt", "requirements_file"),
        ("pyproject.toml", "pyproject_file"),
        ("SKILL.md", "skill_file"),
    ):
        candidate = root / filename
        if candidate.is_file():
            metadata[key] = str(candidate)
    return validate_conductor_definition(replace(conductor, metadata=metadata))


_EXTRACT_SCRIPT = r"""
import json
import runpy
import sys
import traceback

from artagents.conductors.api import ConductorSpec
from artagents.conductors.schema import ConductorDefinition, validate_conductor_definition

PREFIX = "__ARTAGENTS_CONDUCTOR_METADATA__="


def normalize(raw):
    if isinstance(raw, ConductorSpec):
        return raw.to_definition()
    if isinstance(raw, ConductorDefinition):
        return validate_conductor_definition(raw)
    if isinstance(raw, dict):
        return validate_conductor_definition(raw)
    to_definition = getattr(raw, "to_definition", None)
    if callable(to_definition):
        return validate_conductor_definition(to_definition())
    raise TypeError("top-level conductor or CONDUCTOR must be ConductorSpec, ConductorDefinition, dict, or expose to_definition()")


def normalize_many(raw_conductors):
    if not isinstance(raw_conductors, (list, tuple)):
        raise TypeError("top-level CONDUCTORS must be a list or tuple of conductor metadata")
    return [normalize(raw_conductor) for raw_conductor in raw_conductors]


def decorated_definitions(namespace):
    definitions = []
    for name in sorted(namespace):
        value = namespace[name]
        if name.startswith("__"):
            continue
        raw_conductor = getattr(value, "CONDUCTOR", None) or getattr(value, "conductor", None)
        if raw_conductor is not None:
            definitions.append(normalize(raw_conductor))
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
    namespace = runpy.run_path(sys.argv[1], run_name="__artagents_folder_conductor__")
    if "CONDUCTORS" in namespace:
        definitions = normalize_many(namespace["CONDUCTORS"])
    elif "CONDUCTOR" in namespace:
        definitions = [normalize(namespace["CONDUCTOR"])]
    elif "conductor" in namespace and (definition := normalize_optional(namespace["conductor"])) is not None:
        definitions = [definition]
    else:
        definitions = decorated_definitions(namespace)
        if not definitions:
            raise ValueError("folder conductor must define top-level conductor or CONDUCTOR, CONDUCTORS, or decorated callables")
    package_id = namespace.get("PACKAGE_ID")
    print(PREFIX + json.dumps([definition_payload(definition, package_id) for definition in definitions], sort_keys=True))
except Exception:
    traceback.print_exc(file=sys.stderr)
    raise SystemExit(1)
"""


__all__ = [
    "FolderConductorError",
    "discover_folder_conductor_roots",
    "load_folder_conductor",
    "load_folder_conductors",
]
