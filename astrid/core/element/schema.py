"""Schema dataclasses for render/custom elements."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ELEMENT_KINDS = ("effects", "animations", "transitions")
ElementKind = Literal["effects", "animations", "transitions"]
REQUIRED_ELEMENT_FILES = ("component.tsx", "element.yaml")
ELEMENT_MANIFEST_NAMES = ("element.yaml", "element.yml", "element.json")
_KIND_SINGULAR_TO_PLURAL = {"effect": "effects", "animation": "animations", "transition": "transitions"}
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
    description: str = ""
    short_description: str = ""
    keywords: tuple[str, ...] = ()

    @property
    def fork_target(self) -> Path:
        return Path("astrid") / "packs" / "local" / "elements" / self.kind / self.id

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
    folder_kind = _normalize_kind(kind)
    manifest_path = _element_manifest_path(element_root)
    if manifest_path is None:
        raise ElementValidationError(f"missing element manifest in {element_root}")
    payload = _read_manifest(manifest_path)
    element_id = str(payload.get("id") or element_root.name)
    declared_kind = payload.get("kind")
    if declared_kind is not None:
        normalized = _normalize_kind(str(declared_kind))
        if normalized != folder_kind:
            raise ElementValidationError(
                f"element {element_id!r} declared kind {declared_kind!r} does not match folder kind {folder_kind!r}"
            )
    metadata_section = payload.get("metadata", {})
    if not isinstance(metadata_section, dict):
        raise ElementValidationError(f"{manifest_path}: metadata must be an object")
    metadata = dict(metadata_section)
    metadata.setdefault("id", element_id)
    pack_id = payload.get("pack_id")
    if pack_id is not None:
        metadata["pack_id"] = pack_id
    schema_section = payload.get("schema", {})
    defaults_section = payload.get("defaults", {})
    if not isinstance(schema_section, dict):
        raise ElementValidationError(f"{manifest_path}: schema must be an object")
    if not isinstance(defaults_section, dict):
        raise ElementValidationError(f"{manifest_path}: defaults must be an object")
    dependencies = _parse_dependencies(payload.get("dependencies", {}), path=f"{manifest_path}.dependencies")
    component = (element_root / "component.tsx").resolve()
    if not component.is_file():
        raise ElementValidationError(f"element {element_id!r} missing component.tsx")
    description = _optional_capability_string(payload, "description", manifest_path)
    short_description = _optional_capability_string(payload, "short_description", manifest_path)
    keywords = _optional_capability_string_list(payload, "keywords", manifest_path)
    definition = ElementDefinition(
        id=element_id,
        kind=folder_kind,
        root=element_root.resolve(),
        source=source,
        editable=editable,
        priority=priority,
        component=component,
        schema=dict(schema_section),
        defaults=dict(defaults_section),
        metadata=metadata,
        dependencies=dependencies,
        description=description,
        short_description=short_description,
        keywords=keywords,
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
    if not (definition.root / "component.tsx").is_file():
        raise ElementValidationError(f"element {definition.id!r} missing component.tsx")
    if _element_manifest_path(definition.root) is None:
        raise ElementValidationError(f"element {definition.id!r} missing element.yaml")
    if definition.metadata.get("id") not in (None, definition.id):
        raise ElementValidationError(f"element {definition.id!r} metadata.id does not match")
    if not isinstance(definition.schema, dict):
        raise ElementValidationError("element.schema must be an object")
    if not isinstance(definition.defaults, dict):
        raise ElementValidationError("element.defaults must be an object")
    if not isinstance(definition.metadata, dict):
        raise ElementValidationError("element.metadata must be an object")
    _validate_capability_text(
        definition.description,
        definition.short_description,
        definition.keywords,
        manifest_id=f"{definition.kind}/{definition.id}",
    )
    return definition


def _parse_definition(raw: dict[str, Any]) -> ElementDefinition:
    return ElementDefinition(
        id=str(raw["id"]),
        kind=_validate_kind(_normalize_kind(str(raw["kind"]))),
        root=Path(raw["root"]),
        source=str(raw["source"]),
        editable=bool(raw["editable"]),
        priority=int(raw["priority"]),
        component=Path(raw["component"]),
        schema=dict(raw.get("schema", {})),
        defaults=dict(raw.get("defaults", {})),
        metadata=dict(raw.get("metadata", {})),
        dependencies=_parse_dependencies(raw.get("dependencies", {}), path="element.dependencies"),
        description=str(raw.get("description", "") or ""),
        short_description=str(raw.get("short_description", "") or ""),
        keywords=tuple(raw.get("keywords", ()) or ()),
    )


def _element_manifest_path(root: Path) -> Path | None:
    for name in ELEMENT_MANIFEST_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _read_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ElementValidationError(f"{path}: invalid manifest JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ElementValidationError(f"{path} must contain an object")
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


def _normalize_kind(kind: str) -> ElementKind:
    if kind in ELEMENT_KINDS:
        return kind  # type: ignore[return-value]
    plural = _KIND_SINGULAR_TO_PLURAL.get(kind)
    if plural is not None:
        return plural  # type: ignore[return-value]
    raise ElementValidationError(f"element.kind must be one of {list(ELEMENT_KINDS)} (or singular variants)")


def _validate_kind(kind: str) -> ElementKind:
    if kind not in ELEMENT_KINDS:
        raise ElementValidationError(f"element.kind must be one of {list(ELEMENT_KINDS)}")
    return kind  # type: ignore[return-value]


SHORT_DESCRIPTION_MAX_LEN = 120
DESCRIPTION_MAX_LEN = 500
KEYWORD_MAX_LEN = 32
KEYWORDS_MAX_COUNT = 12


def _optional_capability_string(payload: dict[str, Any], key: str, manifest_path: Path) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ElementValidationError(f"{manifest_path}: {key} must be a string")
    return value


def _optional_capability_string_list(
    payload: dict[str, Any], key: str, manifest_path: Path
) -> tuple[str, ...]:
    raw = payload.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ElementValidationError(f"{manifest_path}: {key} must be a list of strings")
    return tuple(raw)


def _validate_capability_text(
    description: str,
    short_description: str,
    keywords: tuple[str, ...],
    *,
    manifest_id: str,
) -> None:
    if len(description) > DESCRIPTION_MAX_LEN:
        raise ElementValidationError(
            f"{manifest_id}: description is {len(description)} chars; max is {DESCRIPTION_MAX_LEN}"
        )
    if len(short_description) > SHORT_DESCRIPTION_MAX_LEN:
        raise ElementValidationError(
            f"{manifest_id}: short_description is {len(short_description)} chars; max is {SHORT_DESCRIPTION_MAX_LEN}"
        )
    if len(keywords) > KEYWORDS_MAX_COUNT:
        raise ElementValidationError(
            f"{manifest_id}: keywords has {len(keywords)} entries; max is {KEYWORDS_MAX_COUNT}"
        )
    seen: set[str] = set()
    for index, keyword in enumerate(keywords):
        if len(keyword) > KEYWORD_MAX_LEN:
            raise ElementValidationError(
                f"{manifest_id}: keywords[{index}] is {len(keyword)} chars; max is {KEYWORD_MAX_LEN}"
            )
        if any(ch.isspace() for ch in keyword):
            raise ElementValidationError(
                f"{manifest_id}: keywords[{index}] {keyword!r} must not contain whitespace"
            )
        if keyword.lower() != keyword:
            raise ElementValidationError(
                f"{manifest_id}: keywords[{index}] {keyword!r} must be lowercase"
            )
        if keyword in seen:
            raise ElementValidationError(
                f"{manifest_id}: keywords[{index}] {keyword!r} is a duplicate"
            )
        seen.add(keyword)


def _validate_id(value: str, path: str) -> None:
    if not _ID_RE.match(value) or "/" in value or "\\" in value or value in {".", ".."}:
        raise ElementValidationError(f"{path} must be a safe non-empty identifier")
