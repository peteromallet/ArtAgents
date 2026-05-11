"""Timeline data models: Assembly, Manifest, Display, FinalOutput."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from astrid.core.project.paths import ProjectPathError
from astrid.core.project.jsonio import read_json, write_json_atomic

from .paths import validate_timeline_slug, validate_timeline_ulid

TIMELINE_SCHEMA_VERSION = 1


class TimelineValidationError(ValueError):
    """Raised when timeline state fails validation."""


def _validate_slug(value: str) -> str:
    try:
        return validate_timeline_slug(value)
    except ProjectPathError as exc:
        raise TimelineValidationError(str(exc)) from exc


def _validate_ulid(value: str) -> str:
    try:
        return validate_timeline_ulid(value)
    except ProjectPathError as exc:
        raise TimelineValidationError(str(exc)) from exc


@dataclass(frozen=True)
class Assembly:
    """Editable assembly (mirrors reigh-app's TimelineConfig)."""

    schema_version: int
    assembly: dict[str, Any]

    def to_json_obj(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "assembly": dict(self.assembly)}

    def write(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_json_obj())

    @classmethod
    def from_json(cls, path: str | Path) -> "Assembly":
        return cls.from_dict(read_json(path))

    @classmethod
    def from_dict(cls, raw: Any) -> "Assembly":
        if not isinstance(raw, dict):
            raise TimelineValidationError("assembly must be an object")
        version = raw.get("schema_version")
        if version != TIMELINE_SCHEMA_VERSION:
            raise TimelineValidationError(
                f"assembly.schema_version must be {TIMELINE_SCHEMA_VERSION}, got {version!r}"
            )
        assembly = raw.get("assembly")
        if not isinstance(assembly, dict):
            raise TimelineValidationError("assembly.assembly must be an object")
        return cls(schema_version=TIMELINE_SCHEMA_VERSION, assembly=dict(assembly))


@dataclass(frozen=True)
class FinalOutput:
    """A single finalized output record with integrity metadata."""

    ulid: str
    path: str
    kind: str
    size: int
    sha256: str
    check_status: str
    check_at: str
    recorded_at: str
    recorded_by: str
    from_run: str

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "ulid": self.ulid,
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
            "check_status": self.check_status,
            "check_at": self.check_at,
            "recorded_at": self.recorded_at,
            "recorded_by": self.recorded_by,
            "from_run": self.from_run,
        }

    def write(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_json_obj())

    @classmethod
    def from_json(cls, path: str | Path) -> "FinalOutput":
        return cls.from_dict(read_json(path))

    @classmethod
    def from_dict(cls, raw: Any) -> "FinalOutput":
        if not isinstance(raw, dict):
            raise TimelineValidationError("final_output must be an object")
        ulid = raw.get("ulid")
        if not isinstance(ulid, str):
            raise TimelineValidationError("final_output.ulid must be a string")
        _validate_ulid(ulid)
        path_str = raw.get("path")
        if not isinstance(path_str, str) or not path_str:
            raise TimelineValidationError("final_output.path must be a non-empty string")
        kind = raw.get("kind")
        if not isinstance(kind, str) or not kind:
            raise TimelineValidationError("final_output.kind must be a non-empty string")
        size = raw.get("size")
        if not isinstance(size, int) or isinstance(size, bool):
            raise TimelineValidationError("final_output.size must be an integer")
        sha256 = raw.get("sha256")
        if not isinstance(sha256, str) or not sha256:
            raise TimelineValidationError("final_output.sha256 must be a non-empty string")
        check_status = raw.get("check_status", "ok")
        if check_status not in ("ok", "missing", "mismatch"):
            raise TimelineValidationError(
                "final_output.check_status must be ok, missing, or mismatch"
            )
        check_at = raw.get("check_at")
        if not isinstance(check_at, str):
            raise TimelineValidationError("final_output.check_at must be a string")
        recorded_at = raw.get("recorded_at")
        if not isinstance(recorded_at, str):
            raise TimelineValidationError("final_output.recorded_at must be a string")
        recorded_by = raw.get("recorded_by")
        if not isinstance(recorded_by, str) or not recorded_by:
            raise TimelineValidationError("final_output.recorded_by must be a non-empty string")
        from_run = raw.get("from_run")
        if not isinstance(from_run, str):
            raise TimelineValidationError("final_output.from_run must be a string")
        if from_run:  # empty string is allowed (no run bound)
            _validate_ulid(from_run)
        return cls(
            ulid=ulid,
            path=path_str,
            kind=kind,
            size=size,
            sha256=sha256,
            check_status=check_status,
            check_at=check_at,
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            from_run=from_run,
        )


@dataclass(frozen=True)
class Manifest:
    """Contributing runs, final outputs, and tombstone marker."""

    schema_version: int
    contributing_runs: list[str]
    final_outputs: list[FinalOutput]
    tombstoned_at: str | None

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contributing_runs": list(self.contributing_runs),
            "final_outputs": [fo.to_json_obj() for fo in self.final_outputs],
            "tombstoned_at": self.tombstoned_at,
        }

    def write(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_json_obj())

    @classmethod
    def from_json(cls, path: str | Path) -> "Manifest":
        return cls.from_dict(read_json(path))

    @classmethod
    def from_dict(cls, raw: Any) -> "Manifest":
        if not isinstance(raw, dict):
            raise TimelineValidationError("manifest must be an object")
        version = raw.get("schema_version")
        if version != TIMELINE_SCHEMA_VERSION:
            raise TimelineValidationError(
                f"manifest.schema_version must be {TIMELINE_SCHEMA_VERSION}, got {version!r}"
            )
        contributing_runs = raw.get("contributing_runs", [])
        if not isinstance(contributing_runs, list):
            raise TimelineValidationError("manifest.contributing_runs must be a list")
        for item in contributing_runs:
            if not isinstance(item, str):
                raise TimelineValidationError("manifest.contributing_runs items must be strings")
            _validate_ulid(item)
        raw_outputs = raw.get("final_outputs", [])
        if not isinstance(raw_outputs, list):
            raise TimelineValidationError("manifest.final_outputs must be a list")
        final_outputs = [FinalOutput.from_dict(fo) for fo in raw_outputs]
        tombstoned_at = raw.get("tombstoned_at")
        if tombstoned_at is not None and not isinstance(tombstoned_at, str):
            raise TimelineValidationError("manifest.tombstoned_at must be a string or null")
        return cls(
            schema_version=TIMELINE_SCHEMA_VERSION,
            contributing_runs=list(contributing_runs),
            final_outputs=final_outputs,
            tombstoned_at=tombstoned_at,
        )


@dataclass(frozen=True)
class Display:
    """Human-facing identity: slug, name, and default flag."""

    schema_version: int
    slug: str
    name: str
    is_default: bool

    def to_json_obj(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "slug": self.slug,
            "name": self.name,
            "is_default": self.is_default,
        }

    def write(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_json_obj())

    @classmethod
    def from_json(cls, path: str | Path) -> "Display":
        return cls.from_dict(read_json(path))

    @classmethod
    def from_dict(cls, raw: Any) -> "Display":
        if not isinstance(raw, dict):
            raise TimelineValidationError("display must be an object")
        version = raw.get("schema_version")
        if version != TIMELINE_SCHEMA_VERSION:
            raise TimelineValidationError(
                f"display.schema_version must be {TIMELINE_SCHEMA_VERSION}, got {version!r}"
            )
        slug = raw.get("slug")
        if not isinstance(slug, str):
            raise TimelineValidationError("display.slug must be a string")
        _validate_slug(slug)
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise TimelineValidationError("display.name must be a non-empty string")
        is_default = raw.get("is_default", False)
        if not isinstance(is_default, bool):
            raise TimelineValidationError("display.is_default must be a boolean")
        return cls(
            schema_version=TIMELINE_SCHEMA_VERSION,
            slug=slug,
            name=name,
            is_default=is_default,
        )