"""Schema dataclasses for render/custom elements."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ELEMENT_KINDS = ("effects", "animations", "transitions")
ElementKind = Literal["effects", "animations", "transitions"]
REQUIRED_ELEMENT_FILES = ("component.tsx", "schema.json", "defaults.json", "meta.json")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ElementValidationError(ValueError):
    """Raised when an element definition is invalid."""


@dataclass(frozen=True)
class ElementDependencies:
    js_packages: tuple[str, ...] = ()
    python_requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class ElementDefinition:
    id: str
    kind: ElementKind
    root: Path
    source: str
    editable: bool
    priority: int
    component: Path
    schema: dict[str, Any]
    defaults: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    dependencies: ElementDependencies = field(default_factory=ElementDependencies)

    @property
    def fork_target(self) -> Path:
        return Path(".artagents") / "elements" / "overrides" / self.kind / self.id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root"] = str(self.root)
        data["component"] = str(self.component)
        data["fork_target"] = str(self.fork_target)
        return data

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def load_element_definition(
    root: str | Path,
    *,
    kind: str,
    source: str,
    editable: bool,
    priority: int,
) -> ElementDefinition:
    element_root = Path(root)
    element_id = element_root.name
    try:
        schema = _read_object(element_root / "schema.json")
        defaults = _read_object(element_root / "defaults.json")
        metadata = _read_object(element_root / "meta.json")
    except FileNotFoundError as exc:
        raise ElementValidationError(f"missing required element file: {exc.filename}") from exc
    dependencies = _parse_dependencies(metadata.get("dependencies", {}), path=f"{element_root}/meta.json.dependencies")
    definition = ElementDefinition(
        id=str(metadata.get("id") or element_id),
        kind=_validate_kind(kind),
        root=element_root.resolve(),
        source=source,
        editable=editable,
        priority=priority,
        component=(element_root / "component.tsx").resolve(),
        schema=schema,
        defaults=defaults,
        metadata=dict(metadata),
        dependencies=dependencies,
    )
    return validate_element_definition(definition)


def validate_element_definition(raw: ElementDefinition | dict[str, Any]) -> ElementDefinition:
    if isinstance(raw, ElementDefinition):
        definition = raw
    else:
        definition = _parse_definition(raw)
    _validate_id(definition.id, "element.id")
    _validate_kind(definition.kind)
    if not definition.root.is_dir():
        raise ElementValidationError(f"element root is not a directory: {definition.root}")
    for filename in REQUIRED_ELEMENT_FILES:
        if not (definition.root / filename).is_file():
            raise ElementValidationError(f"element {definition.id!r} missing {filename}")
    if definition.metadata.get("id") not in (None, definition.id):
        raise ElementValidationError(f"element {definition.id!r} meta.json id does not match")
    if not isinstance(definition.schema, dict):
        raise ElementValidationError("element.schema must be an object")
    if not isinstance(definition.defaults, dict):
        raise ElementValidationError("element.defaults must be an object")
    if not isinstance(definition.metadata, dict):
        raise ElementValidationError("element.metadata must be an object")
    return definition


def _parse_definition(raw: dict[str, Any]) -> ElementDefinition:
    return ElementDefinition(
        id=str(raw["id"]),
        kind=_validate_kind(str(raw["kind"])),
        root=Path(raw["root"]),
        source=str(raw["source"]),
        editable=bool(raw["editable"]),
        priority=int(raw["priority"]),
        component=Path(raw["component"]),
        schema=dict(raw.get("schema", {})),
        defaults=dict(raw.get("defaults", {})),
        metadata=dict(raw.get("metadata", {})),
        dependencies=_parse_dependencies(raw.get("dependencies", {}), path="element.dependencies"),
    )


def _read_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ElementValidationError(f"{path} must contain a JSON object")
    return data


def _parse_dependencies(raw: Any, *, path: str) -> ElementDependencies:
    if raw is None:
        return ElementDependencies()
    if not isinstance(raw, dict):
        raise ElementValidationError(f"{path} must be an object")
    return ElementDependencies(
        js_packages=tuple(_string_list(raw.get("js_packages", ()), path=f"{path}.js_packages")),
        python_requirements=tuple(_string_list(raw.get("python_requirements", ()), path=f"{path}.python_requirements")),
    )


def _string_list(raw: Any, *, path: str) -> list[str]:
    if raw in (None, ()):
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise ElementValidationError(f"{path} must be a list of non-empty strings")
    return list(raw)


def _validate_kind(kind: str) -> ElementKind:
    if kind not in ELEMENT_KINDS:
        raise ElementValidationError(f"element.kind must be one of {list(ELEMENT_KINDS)}")
    return kind  # type: ignore[return-value]


def _validate_id(value: str, path: str) -> None:
    if not _ID_RE.match(value) or "/" in value or "\\" in value or value in {".", ".."}:
        raise ElementValidationError(f"{path} must be a safe non-empty identifier")
