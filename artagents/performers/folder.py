"""Folder-based performer discovery and metadata extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .schema import PerformerDefinition, PerformerValidationError, validate_performer_definition


_RESULT_PREFIX = "__ARTAGENTS_PERFORMER_METADATA__="


class FolderPerformerError(PerformerValidationError):
    """Raised when a folder performer cannot be discovered or extracted."""


def discover_folder_performer_roots(root: str | Path) -> tuple[Path, ...]:
    """Return folders under `root` that contain a `performer.py` file."""

    search_root = Path(root)
    if not search_root.is_dir():
        return ()
    roots = {path.parent.resolve() for path in search_root.rglob("performer.py") if _is_performer_file(path)}
    return tuple(sorted(roots))


def load_folder_performers(root: str | Path) -> tuple[PerformerDefinition, ...]:
    """Load every folder performer below `root` through the subprocess extractor."""

    performers: list[PerformerDefinition] = []
    for performer_root in discover_folder_performer_roots(root):
        performers.extend(_load_folder_performer_definitions(performer_root))
    return tuple(performers)


def load_folder_performer(performer_root: str | Path) -> PerformerDefinition:
    """Extract and validate a single folder performer without importing it here."""

    definitions = _load_folder_performer_definitions(performer_root)
    if len(definitions) != 1:
        root = Path(performer_root).expanduser().resolve()
        raise FolderPerformerError(f"folder performer must define exactly one performer for load_folder_performer(): {root}")
    return definitions[0]


def _load_folder_performer_definitions(performer_root: str | Path) -> tuple[PerformerDefinition, ...]:
    """Extract and validate every performer definition from one folder performer package."""

    root = Path(performer_root).expanduser().resolve()
    performer_path = root / "performer.py"
    if not performer_path.is_file():
        raise FolderPerformerError(f"folder performer is missing performer.py: {root}")

    env = dict(os.environ)
    parent_paths = [str(Path.cwd()) if path == "" else path for path in sys.path]
    env["PYTHONPATH"] = os.pathsep.join(parent_paths + [env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-c", _EXTRACT_SCRIPT, str(performer_path)],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise FolderPerformerError(f"failed to extract folder performer metadata from {performer_path}{suffix}")

    payload = _extract_payload(completed.stdout, performer_path)
    try:
        raw_definitions = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FolderPerformerError(f"folder performer extractor emitted invalid JSON for {performer_path}: {exc.msg}") from exc

    if not isinstance(raw_definitions, list):
        raise FolderPerformerError(f"folder performer extractor emitted non-list metadata for {performer_path}")

    definitions: list[PerformerDefinition] = []
    try:
        for raw_definition in raw_definitions:
            definition = validate_performer_definition(raw_definition)
            definitions.append(_attach_folder_metadata(definition, root, performer_path))
    except PerformerValidationError as exc:
        raise FolderPerformerError(f"{performer_path}: {exc}") from exc

    if not definitions:
        raise FolderPerformerError(f"folder performer extractor emitted no metadata for {performer_path}")
    return tuple(definitions)


def _is_performer_file(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts


def _extract_payload(stdout: str, performer_path: Path) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            return line[len(_RESULT_PREFIX) :]
    raise FolderPerformerError(f"folder performer extractor did not emit metadata for {performer_path}")


def _attach_folder_metadata(performer: PerformerDefinition, root: Path, performer_path: Path) -> PerformerDefinition:
    metadata = dict(performer.metadata)
    metadata.update(
        {
            "source": "folder",
            "performer_root": str(root),
            "performer_file": str(performer_path),
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
    return validate_performer_definition(replace(performer, metadata=metadata))


_EXTRACT_SCRIPT = r"""
import json
import runpy
import sys
import traceback

from artagents.performers.api import PerformerSpec
from artagents.performers.schema import PerformerDefinition, validate_performer_definition

PREFIX = "__ARTAGENTS_PERFORMER_METADATA__="


def normalize(raw):
    if isinstance(raw, PerformerSpec):
        return raw.to_definition()
    if isinstance(raw, PerformerDefinition):
        return validate_performer_definition(raw)
    if isinstance(raw, dict):
        return validate_performer_definition(raw)
    to_definition = getattr(raw, "to_definition", None)
    if callable(to_definition):
        return validate_performer_definition(to_definition())
    raise TypeError("top-level performer or PERFORMER must be PerformerSpec, PerformerDefinition, dict, or expose to_definition()")


def normalize_many(raw_performers):
    if not isinstance(raw_performers, (list, tuple)):
        raise TypeError("top-level PERFORMERS must be a list or tuple of performer metadata")
    return [normalize(raw_performer) for raw_performer in raw_performers]


def decorated_definitions(namespace):
    definitions = []
    for name in sorted(namespace):
        value = namespace[name]
        if name.startswith("__"):
            continue
        raw_performer = getattr(value, "PERFORMER", None) or getattr(value, "performer", None)
        if raw_performer is not None:
            definitions.append(normalize(raw_performer))
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
    namespace = runpy.run_path(sys.argv[1], run_name="__artagents_folder_performer__")
    if "PERFORMERS" in namespace:
        definitions = normalize_many(namespace["PERFORMERS"])
    elif "PERFORMER" in namespace:
        definitions = [normalize(namespace["PERFORMER"])]
    elif "performer" in namespace and (definition := normalize_optional(namespace["performer"])) is not None:
        definitions = [definition]
    else:
        definitions = decorated_definitions(namespace)
        if not definitions:
            raise ValueError("folder performer must define top-level performer or PERFORMER, PERFORMERS, or decorated callables")
    package_id = namespace.get("PACKAGE_ID")
    print(PREFIX + json.dumps([definition_payload(definition, package_id) for definition in definitions], sort_keys=True))
except Exception:
    traceback.print_exc(file=sys.stderr)
    raise SystemExit(1)
"""


__all__ = [
    "FolderPerformerError",
    "discover_folder_performer_roots",
    "load_folder_performer",
    "load_folder_performers",
]
