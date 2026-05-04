"""Element registry and source precedence."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable

from artagents._paths import REPO_ROOT
from artagents.core.pack import discover_packs, iter_element_roots, validate_element_pack_id

from .schema import ELEMENT_KINDS, ElementDefinition, ElementKind, ElementValidationError, load_element_definition


class ElementRegistryError(ElementValidationError):
    """Raised when element registry state is inconsistent."""


@dataclass(frozen=True)
class ElementSource:
    name: str
    root: Path
    priority: int
    editable: bool


@dataclass(frozen=True)
class ElementConflict:
    kind: ElementKind
    id: str
    winner: ElementDefinition
    shadowed: tuple[ElementDefinition, ...]


class ElementRegistry:
    """Resolved element registry keyed by kind and element id."""

    def __init__(self, elements: Iterable[ElementDefinition] = ()) -> None:
        self._all: dict[tuple[str, str], list[ElementDefinition]] = {}
        for element in elements:
            self.register(element)

    def register(self, element: ElementDefinition) -> ElementDefinition:
        key = (element.kind, element.id)
        self._all.setdefault(key, []).append(element)
        self._all[key].sort(key=lambda item: (item.priority, item.source, str(item.root)))
        return element

    def get(self, kind: str, element_id: str) -> ElementDefinition:
        key = (kind, element_id)
        try:
            return self._all[key][0]
        except KeyError as exc:
            raise KeyError(f"unknown {kind} element {element_id!r}") from exc

    def list(self, kind: str | None = None) -> tuple[ElementDefinition, ...]:
        if kind is not None and kind not in ELEMENT_KINDS:
            raise ElementRegistryError(f"kind must be one of {list(ELEMENT_KINDS)}")
        winners = [definitions[0] for (item_kind, _), definitions in self._all.items() if kind is None or item_kind == kind]
        return tuple(sorted(winners, key=lambda item: (item.kind, item.id)))

    def conflicts(self) -> tuple[ElementConflict, ...]:
        conflicts: list[ElementConflict] = []
        for (kind, element_id), definitions in self._all.items():
            if len(definitions) > 1:
                conflicts.append(
                    ElementConflict(
                        kind=kind,  # type: ignore[arg-type]
                        id=element_id,
                        winner=definitions[0],
                        shadowed=tuple(definitions[1:]),
                    )
                )
        return tuple(sorted(conflicts, key=lambda item: (item.kind, item.id)))

    def as_mapping(self) -> MappingProxyType[tuple[str, str], ElementDefinition]:
        return MappingProxyType({key: definitions[0] for key, definitions in self._all.items()})

    def fork_target(self, kind: str, element_id: str, *, project_root: str | Path = REPO_ROOT) -> Path:
        element = self.get(kind, element_id)
        return Path(project_root) / element.fork_target

    def fork(self, kind: str, element_id: str, *, project_root: str | Path = REPO_ROOT, overwrite: bool = False) -> Path:
        element = self.get(kind, element_id)
        target = self.fork_target(kind, element_id, project_root=project_root)
        if target.exists() and not overwrite:
            raise ElementRegistryError(f"element override already exists: {target}")
        ensure_local_pack(project_root=project_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(element.root, target)
        _rewrite_pack_id(target, "local")
        return target


def load_default_registry(
    *,
    active_theme: str | Path | None = None,
    project_root: str | Path = REPO_ROOT,
    include_missing_roots: bool = False,
) -> ElementRegistry:
    registry = ElementRegistry()
    for element in load_pack_elements():
        registry.register(element)
    for source in default_sources(active_theme=active_theme, project_root=project_root):
        if not source.root.exists():
            if include_missing_roots:
                source.root.mkdir(parents=True, exist_ok=True)
            else:
                continue
        for element in load_source_elements(source):
            registry.register(element)
    return registry


def default_sources(*, active_theme: str | Path | None = None, project_root: str | Path = REPO_ROOT) -> tuple[ElementSource, ...]:
    theme_dir = _resolve_theme_dir(active_theme)
    sources: list[ElementSource] = []
    if theme_dir is not None:
        sources.extend(
            [
                ElementSource("active_theme", theme_dir / "elements", 0, True),
                ElementSource("active_theme", theme_dir, 0, True),
            ]
        )
    return tuple(sources)


def load_pack_elements() -> tuple[ElementDefinition, ...]:
    elements: list[ElementDefinition] = []
    for pack in discover_packs():
        priority = 10 if pack.id == "local" else 30
        for kind, root in iter_element_roots(pack):
            element = load_element_definition(
                root,
                kind=kind,
                source=f"pack:{pack.id}",
                editable=pack.id == "local",
                priority=priority,
            )
            validate_element_pack_id(element.metadata.get("pack_id"), pack, element_root=root)
            elements.append(element)
    return tuple(elements)


def ensure_local_pack(*, project_root: str | Path = REPO_ROOT) -> Path:
    pack_root = Path(project_root) / "artagents" / "packs" / "local"
    pack_root.mkdir(parents=True, exist_ok=True)
    manifest = pack_root / "pack.yaml"
    if not manifest.exists():
        manifest.write_text("id: local\nname: Local Scratch Pack\nversion: 0.1.0\n", encoding="utf-8")
    return pack_root


def _rewrite_pack_id(element_root: Path, new_pack_id: str) -> None:
    from .schema import ELEMENT_MANIFEST_NAMES

    for name in ELEMENT_MANIFEST_NAMES:
        manifest = element_root / name
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["pack_id"] = new_pack_id
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return


def load_source_elements(source: ElementSource) -> tuple[ElementDefinition, ...]:
    from .schema import ELEMENT_MANIFEST_NAMES

    elements: list[ElementDefinition] = []
    for kind in ELEMENT_KINDS:
        kind_root = source.root / kind
        if not kind_root.is_dir():
            continue
        for child in sorted(kind_root.iterdir(), key=lambda path: path.name):
            if not child.is_dir():
                continue
            if not any((child / name).is_file() for name in ELEMENT_MANIFEST_NAMES):
                continue
            try:
                elements.append(
                    load_element_definition(
                        child,
                        kind=kind,
                        source=source.name,
                        editable=source.editable,
                        priority=source.priority,
                    )
                )
            except ElementValidationError as exc:
                print(f"WARN skipping {child}: {exc}", file=sys.stderr)
    return tuple(elements)


def _resolve_theme_dir(theme: str | Path | None) -> Path | None:
    raw = os.environ.get("HYPE_ACTIVE_THEME") if theme is None else theme
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.name == "theme.json":
        return candidate.parent.resolve()
    if candidate.exists():
        return (candidate if candidate.is_dir() else candidate.parent).resolve()
    return (REPO_ROOT.parent / "themes" / str(raw)).resolve()
