"""Pack discovery and validation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PACK_MANIFEST_NAMES = ("pack.yaml", "pack.yml", "pack.json")
EXECUTOR_MANIFEST_NAMES = ("executor.yaml", "executor.yml", "executor.json")
ORCHESTRATOR_MANIFEST_NAMES = ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json")
ELEMENT_KINDS = ("effects", "animations", "transitions")
ElementKind = str
_PACK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class PackValidationError(ValueError):
    """Raised when pack layout or metadata is invalid."""


@dataclass(frozen=True)
class PackDefinition:
    id: str
    name: str
    version: str
    root: Path
    manifest_path: Path
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "metadata": dict(self.metadata),
        }


def packs_root() -> Path:
    return Path(__file__).resolve().parents[1] / "packs"


def discover_packs(root: str | Path | None = None) -> tuple[PackDefinition, ...]:
    source_root = Path(root) if root is not None else packs_root()
    if not source_root.is_dir():
        return ()
    packs: list[PackDefinition] = []
    seen: dict[str, Path] = {}
    for child in sorted(source_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith(".") or child.name == "__pycache__":
            continue
        manifest_path = pack_manifest_path(child)
        if manifest_path is None:
            continue
        pack = load_pack_manifest(manifest_path)
        if pack.id in seen:
            raise PackValidationError(f"duplicate pack id {pack.id!r}: {seen[pack.id]} and {manifest_path}")
        seen[pack.id] = manifest_path
        packs.append(pack)
    return tuple(packs)


def load_pack_manifest(path: str | Path) -> PackDefinition:
    manifest_path = Path(path).expanduser().resolve()
    raw = _load_manifest_payload(manifest_path)
    data = _require_mapping(raw, "pack")
    pack_id = _require_string(data, "id", "pack.id")
    _validate_pack_id(pack_id, "pack.id")
    root = manifest_path.parent
    if root.name != pack_id:
        raise PackValidationError(f"pack id {pack_id!r} must match folder name {root.name!r}")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PackValidationError("pack.metadata must be an object")
    return PackDefinition(
        id=pack_id,
        name=_optional_string(data, "name", "pack.name", default=pack_id),
        version=_optional_string(data, "version", "pack.version", default="0.1.0"),
        root=root,
        manifest_path=manifest_path,
        metadata=dict(metadata),
    )


def pack_manifest_path(root: str | Path) -> Path | None:
    pack_root = Path(root)
    for name in PACK_MANIFEST_NAMES:
        candidate = pack_root / name
        if candidate.is_file():
            return candidate
    return None


def qualified_id_pack_id(value: str, *, path: str = "id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackValidationError(f"{path} must be a non-empty qualified id")
    parts = value.split(".")
    if len(parts) < 2 or any(not part for part in parts):
        raise PackValidationError(f"{path} must be qualified as <pack>.<name>")
    _validate_pack_id(parts[0], f"{path} pack segment")
    return parts[0]


def validate_content_id_in_pack(content_id: str, pack: PackDefinition, *, content_type: str) -> None:
    owner = qualified_id_pack_id(content_id, path=f"{content_type}.id")
    if owner != pack.id:
        raise PackValidationError(
            f"{content_type} id {content_id!r} belongs to pack {owner!r} but was found in pack {pack.id!r}"
        )


def validate_element_pack_id(pack_id: str | None, pack: PackDefinition, *, element_root: str | Path) -> None:
    if not pack_id:
        raise PackValidationError(f"element {Path(element_root)} is missing metadata.pack_id")
    if pack_id != pack.id:
        raise PackValidationError(
            f"element {Path(element_root)} declares pack_id {pack_id!r} but was found in pack {pack.id!r}"
        )


def iter_executor_roots(pack: PackDefinition) -> tuple[Path, ...]:
    return _content_roots(pack.root, EXECUTOR_MANIFEST_NAMES, excluded_parts={"elements"})


def iter_orchestrator_roots(pack: PackDefinition) -> tuple[Path, ...]:
    return _content_roots(pack.root, ORCHESTRATOR_MANIFEST_NAMES, excluded_parts={"elements"})


def iter_element_roots(pack: PackDefinition, *, kind: str | None = None) -> tuple[tuple[ElementKind, Path], ...]:
    kinds: Iterable[str] = ELEMENT_KINDS if kind is None else (kind,)
    roots: list[tuple[ElementKind, Path]] = []
    for element_kind in kinds:
        if element_kind not in ELEMENT_KINDS:
            raise PackValidationError(f"element kind must be one of {list(ELEMENT_KINDS)}")
        kind_root = pack.root / "elements" / element_kind
        if not kind_root.is_dir():
            continue
        roots.extend((element_kind, child) for child in sorted(kind_root.iterdir()) if child.is_dir())
    return tuple(roots)


def _content_roots(root: Path, manifest_names: tuple[str, ...], *, excluded_parts: set[str]) -> tuple[Path, ...]:
    roots = {
        path.parent.resolve()
        for manifest_name in manifest_names
        for path in root.rglob(manifest_name)
        if "__pycache__" not in path.parts and excluded_parts.isdisjoint(path.relative_to(root).parts)
    }
    return tuple(sorted(roots))


def _load_manifest_payload(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PackValidationError(f"pack manifest not found: {path}") from exc
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PackValidationError(f"invalid JSON pack manifest {path}: {exc.msg}") from exc
    return _parse_flat_yaml(text, path=path)


def _parse_flat_yaml(text: str, *, path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line[: len(raw_line) - len(raw_line.lstrip())].strip():
            raise PackValidationError(f"{path}: invalid indentation at line {line_number}")
        if ":" not in stripped:
            raise PackValidationError(f"{path}: expected key: value at line {line_number}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = _strip_comment(value.strip())
        if not key:
            raise PackValidationError(f"{path}: empty key at line {line_number}")
        if value in {"", "{}"}:
            data[key] = {}
        else:
            data[key] = _unquote(value)
    if not data:
        raise PackValidationError(f"{path}: empty pack manifest")
    return data


def _strip_comment(value: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(value):
        if char in {"'", '"'} and (index == 0 or value[index - 1] != "\\"):
            in_quote = None if in_quote == char else char if in_quote is None else in_quote
        if char == "#" and in_quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PackValidationError(f"{path} must be an object")
    return raw


def _require_string(data: dict[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise PackValidationError(f"missing required field {path}")
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise PackValidationError(f"{path} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], key: str, path: str, *, default: str) -> str:
    if key not in data or data[key] == "":
        return default
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise PackValidationError(f"{path} must be a non-empty string")
    return value


def _validate_pack_id(value: str, path: str) -> None:
    if not _PACK_ID_RE.match(value) or value in {".", ".."}:
        raise PackValidationError(f"{path} must be a safe pack identifier")


__all__ = [
    "PackDefinition",
    "PackValidationError",
    "discover_packs",
    "iter_element_roots",
    "iter_executor_roots",
    "iter_orchestrator_roots",
    "load_pack_manifest",
    "pack_manifest_path",
    "packs_root",
    "qualified_id_pack_id",
    "validate_content_id_in_pack",
    "validate_element_pack_id",
]
