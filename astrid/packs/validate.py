"""Static pack validation module.

Uses yaml.safe_load for author-facing YAML, validates each manifest against its
JSON Schema (v1), rejects unknown schema_version values, and normalizes errors
into file-specific builder-facing messages.

Validation is static: checks declared content roots, docs, STAGE.md,
runtime entrypoint files, and component manifests exist on disk without
importing run.py.
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from pathlib import Path
from typing import Any, Optional

import jsonschema
import yaml
from referencing import Registry, Resource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known schema versions and their schema files
# ---------------------------------------------------------------------------

_SCHEMAS_ROOT = Path(__file__).resolve().parent / "schemas"

KNOWN_SCHEMA_VERSIONS: dict[int, dict[str, Path]] = {
    1: {
        "pack": _SCHEMAS_ROOT / "v1" / "pack.json",
        "executor": _SCHEMAS_ROOT / "v1" / "executor.json",
        "orchestrator": _SCHEMAS_ROOT / "v1" / "orchestrator.json",
        "element": _SCHEMAS_ROOT / "v1" / "element.json",
    }
}

KNOWN_VERSIONS_STR = ", ".join(str(v) for v in sorted(KNOWN_SCHEMA_VERSIONS))


def _check_schema_version(version_value: Any, manifest_relpath: str) -> int:
    """Validate that schema_version is a known integer."""
    if not isinstance(version_value, int) and not (
        isinstance(version_value, float) and version_value == int(version_value)
    ):
        raise ValidationError(
            f"{manifest_relpath}: schema_version must be an integer, got "
            f"{type(version_value).__name__}"
        )
    version = int(version_value)
    if version not in KNOWN_SCHEMA_VERSIONS:
        raise ValidationError(
            f"{manifest_relpath}: unknown schema_version {version} "
            f"(known: {KNOWN_VERSIONS_STR})"
        )
    return version


def _normalize_jsonschema_error(
    error: jsonschema.ValidationError,
    manifest_relpath: str,
    raw_data: dict[str, Any],
) -> str:
    """Convert a jsonschema ValidationError into a file-specific message."""
    # Build the field path from the error's absolute path
    path_parts: list[str] = list(error.absolute_path)
    field = ".".join(str(p) for p in path_parts) if path_parts else "<root>"

    prefix = f"{manifest_relpath}"

    # Special-case schema_version since we handle it separately upstream,
    # but jsonschema may still report it for missing/wrong-type.
    if path_parts == ["schema_version"]:
        if "schema_version" not in raw_data:
            return f"{prefix}: missing required field schema_version"
        return f"{prefix}: schema_version must be 1 (known: {KNOWN_VERSIONS_STR})"

    message = error.message
    # Clean up verbose jsonschema messages
    if message and len(message) > 200:
        message = message[:200] + "..."

    if error.validator == "required":
        # error.validator_value is the full required array from the schema.
        # error.message names the actually missing property.
        # Extract the missing field name from the message.
        msg = error.message
        # Typical message: "'name' is a required property"
        m = _re.match(r"'([^']+)' is a required property", msg)
        if m:
            missing_field = m.group(1)
            if field == "<root>":
                return f"{prefix}: missing required field {missing_field}"
            return f"{prefix}: missing required field {field}.{missing_field}"
        # Fallback
        return f"{prefix}: missing required field(s) — {msg}"

    if error.validator == "additionalProperties":
        offending = error.message
        return f"{prefix}: unknown field(s) in {field}"

    if error.validator == "enum":
        allowed = error.validator_value
        actual = raw_data
        for p in path_parts:
            if isinstance(actual, dict):
                actual = actual.get(p)
            else:
                break
        return f"{prefix}: {field} must be one of {allowed}, got {actual!r}"

    if error.validator == "type":
        expected = error.validator_value
        actual_val = raw_data
        for p in path_parts:
            if isinstance(actual_val, dict):
                actual_val = actual_val.get(p)
            else:
                break
        actual_type = type(actual_val).__name__
        expected_str = expected if isinstance(expected, str) else ", ".join(expected)
        return f"{prefix}: {field} must be {expected_str}, got {actual_type}"

    if error.validator == "pattern":
        actual_val = raw_data
        for p in path_parts:
            if isinstance(actual_val, dict):
                actual_val = actual_val.get(p)
            else:
                break
        return f"{prefix}: {field} value {actual_val!r} does not match required pattern"

    return f"{prefix}: {field} — {message}"


class ValidationError(ValueError):
    """Raised when pack validation fails."""


class PackValidator:
    """Validates an external pack directory statically."""

    def __init__(self, pack_root: Path):
        self.pack_root = pack_root.resolve()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._pack_data: Optional[dict[str, Any]] = None

    def validate(self) -> list[str]:
        """Run all validations. Returns list of error strings (empty = valid)."""
        self.errors = []
        self.warnings = []

        # Check .no-pack marker — explicit opt-out, skip silently
        if (self.pack_root / ".no-pack").exists():
            return self.errors

        pack_yaml = self.pack_root / "pack.yaml"
        if not pack_yaml.is_file():
            self.errors.append(f"{self._rel(pack_yaml)}: pack.yaml not found")
            return self.errors

        # Parse pack.yaml
        pack_data = self._load_yaml(pack_yaml)
        if pack_data is None:
            return self.errors  # parse error already recorded
        self._pack_data = pack_data

        # Check schema_version and validate against JSON Schema
        version = self._validate_manifest(
            pack_data, "pack", self._rel(pack_yaml)
        )
        if version is None:
            return self.errors  # schema_version error already recorded

        # Validate content roots exist
        content = pack_data.get("content", {})
        if isinstance(content, dict):
            self._validate_content_roots(content)

        # Validate docs exist
        docs = pack_data.get("docs", {})
        if isinstance(docs, dict):
            self._validate_docs(docs)

        # Check for AGENTS.md and README.md at pack root
        for doc_name in ("AGENTS.md", "README.md"):
            doc_path = self.pack_root / doc_name
            if not doc_path.is_file():
                self.warnings.append(
                    f"{self._rel(doc_path)}: recommended file not found"
                )

        # Validate component manifests and detect stray manifests
        self._validate_components(content)
        self._check_stray_manifests(content)

        return self.errors

    def _load_yaml(self, path: Path) -> Optional[dict[str, Any]]:
        """Load a YAML file with safe_load. Returns None on error."""
        rel = self._rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            self.errors.append(f"{rel}: cannot read file — {e}")
            return None

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            # Produce a clean error message
            msg = str(e)
            if hasattr(e, "problem_mark") and e.problem_mark:
                mark = e.problem_mark
                msg = f"{msg} (line {mark.line + 1}, column {mark.column + 1})"
            self.errors.append(f"{rel}: invalid YAML — {msg}")
            return None

        if data is None:
            self.errors.append(f"{rel}: empty YAML document")
            return None
        if not isinstance(data, dict):
            self.errors.append(f"{rel}: expected a YAML mapping, got {type(data).__name__}")
            return None

        return data

    def _validate_manifest(
        self,
        data: dict[str, Any],
        manifest_kind: str,
        relpath: str,
    ) -> Optional[int]:
        """Validate a manifest dict against its JSON Schema.

        Returns the schema_version on success, None on failure.
        """
        # Check schema_version first
        if "schema_version" not in data:
            self.errors.append(f"{relpath}: missing required field schema_version")
            return None

        try:
            version = _check_schema_version(data["schema_version"], relpath)
        except ValidationError as e:
            self.errors.append(str(e))
            return None

        # Load and validate against JSON Schema
        schema_path = KNOWN_SCHEMA_VERSIONS[version].get(manifest_kind)
        if schema_path is None:
            self.errors.append(
                f"{relpath}: no schema for {manifest_kind} in version {version}"
            )
            return None

        try:
            schema, registry = self._load_schema(schema_path, manifest_kind, version)
        except Exception as e:
            self.errors.append(
                f"{relpath}: cannot load schema {schema_path} — {e}"
            )
            return None

        validator = jsonschema.Draft7Validator(schema, registry=registry)
        raw_errors = list(validator.iter_errors(data))

        if raw_errors:
            # Take the first few errors to avoid overwhelming output
            for err in raw_errors[:5]:
                self.errors.append(
                    _normalize_jsonschema_error(err, relpath, data)
                )
            if len(raw_errors) > 5:
                self.errors.append(
                    f"{relpath}: ... and {len(raw_errors) - 5} more validation errors"
                )
            return None

        return version

    def _load_schema(
        self, schema_path: Path, manifest_kind: str, version: int
    ) -> tuple[dict[str, Any], Registry]:
        """Load a JSON Schema file and build a referencing.Registry.

        Returns (schema_dict, registry) for use with jsonschema validators.
        Cached per (manifest_kind, version).
        """
        schema_key = (manifest_kind, version)
        if not hasattr(self, "_schema_cache"):
            self._schema_cache: dict[tuple, tuple[dict[str, Any], Registry]] = {}
        if schema_key in self._schema_cache:
            return self._schema_cache[schema_key]

        # Load the _defs.json first
        defs_path = schema_path.parent / "_defs.json"
        registry = Registry()
        if defs_path.is_file():
            with open(defs_path, "r", encoding="utf-8") as f:
                defs_schema = json_loads(f.read())
            registry = registry.with_resource(
                "_defs.json", Resource.from_contents(defs_schema)
            )

        # Load the schema
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json_loads(f.read())

        # Also register the schema itself if it has an $id
        schema_id = schema.get("$id")
        if schema_id:
            registry = registry.with_resource(
                schema_id, Resource.from_contents(schema)
            )

        self._schema_cache[schema_key] = (schema, registry)

        return schema, registry

    def _validate_content_roots(self, content: dict[str, Any]) -> None:
        """Verify that declared content root directories exist."""
        for key in ("executors", "orchestrators", "elements", "schemas", "examples"):
            if key not in content:
                continue
            root_rel = content[key]
            if not isinstance(root_rel, str) or not root_rel.strip():
                continue
            root_path = self.pack_root / root_rel
            if not root_path.is_dir():
                self.warnings.append(
                    f"{self._rel(root_path)}/: declared content root does not exist"
                )

    def _validate_docs(self, docs: dict[str, Any]) -> None:
        """Verify that declared doc files exist."""
        for doc_key, doc_rel in docs.items():
            if not isinstance(doc_rel, str) or not doc_rel.strip():
                continue
            doc_path = self.pack_root / doc_rel
            if not doc_path.is_file():
                self.warnings.append(
                    f"{self._rel(doc_path)}: declared docs file not found"
                )

    def _validate_components(self, content: dict[str, Any]) -> None:
        """Validate all component manifests declared via content roots."""
        if self._pack_data is None:
            return

        # Executors
        exec_root_rel = content.get("executors", "executors")
        if isinstance(exec_root_rel, str) and exec_root_rel.strip():
            exec_root = self.pack_root / exec_root_rel
            if exec_root.is_dir():
                self._validate_component_dir(exec_root, "executor")

        # Orchestrators
        orch_root_rel = content.get("orchestrators", "orchestrators")
        if isinstance(orch_root_rel, str) and orch_root_rel.strip():
            orch_root = self.pack_root / orch_root_rel
            if orch_root.is_dir():
                self._validate_component_dir(orch_root, "orchestrator")

        # Elements
        elem_root_rel = content.get("elements", "elements")
        if isinstance(elem_root_rel, str) and elem_root_rel.strip():
            elem_root = self.pack_root / elem_root_rel
            if elem_root.is_dir():
                self._validate_element_dir(elem_root)

    def _validate_component_dir(
        self, root_dir: Path, manifest_kind: str
    ) -> None:
        """Validate all component directories under a content root."""
        manifest_name = f"{manifest_kind}.yaml"
        for comp_dir in sorted(root_dir.iterdir()):
            if not comp_dir.is_dir() or comp_dir.name.startswith("."):
                continue
            if comp_dir.name == "__pycache__":
                continue

            manifest_path = comp_dir / manifest_name
            if not manifest_path.is_file():
                self.errors.append(
                    f"{self._rel(manifest_path)}: {manifest_kind} manifest not found"
                )
                continue

            data = self._load_yaml(manifest_path)
            if data is None:
                continue

            rel = self._rel(manifest_path)
            version = self._validate_manifest(data, manifest_kind, rel)
            if version is None:
                continue

            # Check runtime entrypoint exists
            runtime = data.get("runtime", {})
            if isinstance(runtime, dict):
                entrypoint = runtime.get("entrypoint")
                if isinstance(entrypoint, str) and entrypoint.strip():
                    ep_path = comp_dir / entrypoint
                    if not ep_path.is_file():
                        self.errors.append(
                            f"{self._rel(ep_path)}: runtime entrypoint file not found"
                        )
                    # IMPORTANT: Do NOT import or execute the file.
                    # We only check its existence.

            # Check STAGE.md
            docs = data.get("docs", {})
            if isinstance(docs, dict):
                stage = docs.get("stage", "STAGE.md")
            else:
                stage = "STAGE.md"
            stage_path = comp_dir / stage
            if not stage_path.is_file():
                self.warnings.append(
                    f"{self._rel(stage_path)}: STAGE.md not found"
                )

    def _validate_element_dir(self, root_dir: Path) -> None:
        """Validate element directories under the elements content root."""
        # Elements are organized as elements/<kind>/<element_name>/
        for kind_dir in sorted(root_dir.iterdir()):
            if not kind_dir.is_dir() or kind_dir.name.startswith("."):
                continue
            if kind_dir.name == "__pycache__":
                continue

            for elem_dir in sorted(kind_dir.iterdir()):
                if not elem_dir.is_dir() or elem_dir.name.startswith("."):
                    continue
                if elem_dir.name == "__pycache__":
                    continue

                manifest_path = elem_dir / "element.yaml"
                if not manifest_path.is_file():
                    self.errors.append(
                        f"{self._rel(manifest_path)}: element manifest not found"
                    )
                    continue

                data = self._load_yaml(manifest_path)
                if data is None:
                    continue

                rel = self._rel(manifest_path)
                self._validate_manifest(data, "element", rel)

    def _check_stray_manifests(self, content: dict[str, Any]) -> None:
        """Detect manifests outside declared content roots and report as stray."""
        # Build a set of declared root directories (resolved absolute paths)
        declared_roots: set[Path] = set()
        _CONTENT_KEYS = ("executors", "orchestrators", "elements")
        for key in _CONTENT_KEYS:
            root_rel = content.get(key)
            if isinstance(root_rel, str) and root_rel.strip():
                declared_roots.add((self.pack_root / root_rel).resolve())

        # Scan the pack root for component manifests (executor.yaml/orchestrator.yaml/element.yaml)
        # but only one level deep — we're looking for manifests accidentally placed
        # in directories that are NOT under declared content roots.
        _MANIFEST_NAMES = (
            "executor.yaml", "executor.yml", "executor.json",
            "orchestrator.yaml", "orchestrator.yml", "orchestrator.json",
            "element.yaml", "element.yml", "element.json",
        )
        # Also check for executor.py / orchestrator.py at pack root level
        try:
            for child in sorted(self.pack_root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if child.name == "__pycache__":
                    continue
                # Skip the declared content root directories themselves
                if child.resolve() in declared_roots:
                    continue
                # Check if any child of this directory is within a declared root
                child_is_under_declared = any(
                    child.resolve() == dr or str(child.resolve()).startswith(str(dr) + "/")
                    for dr in declared_roots
                )
                if child_is_under_declared:
                    continue
                # Check for stray manifests
                for mf_name in _MANIFEST_NAMES:
                    if (child / mf_name).is_file():
                        self.warnings.append(
                            f"{self._rel(child / mf_name)}: stray manifest outside declared content roots"
                        )
                        break  # one warning per directory
                # Check for legacy .py files
                for py_name in ("executor.py", "orchestrator.py"):
                    if (child / py_name).is_file():
                        self.warnings.append(
                            f"{self._rel(child / py_name)}: stray runtime file outside declared content roots"
                        )
                        break
        except OSError:
            pass

    def _rel(self, path: Path) -> str:
        """Return a path relative to the pack root for error messages."""
        try:
            return str(path.relative_to(self.pack_root))
        except ValueError:
            return str(path)


def validate_pack(pack_root: str | Path) -> tuple[list[str], list[str]]:
    """Validate an external pack directory.

    Args:
        pack_root: Path to the pack root directory.

    Returns:
        A tuple of (errors, warnings). Empty errors list means valid.
    """
    validator = PackValidator(Path(pack_root))
    errors = validator.validate()
    return errors, validator.warnings


def json_loads(text: str) -> Any:
    """Load JSON, wrapping decode errors for consistent messaging."""
    return _json.loads(text)


__all__ = [
    "PackValidator",
    "ValidationError",
    "validate_pack",
]
