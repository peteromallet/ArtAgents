"""Pack discovery and validation helpers."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PACK_MANIFEST_NAMES = ("pack.yaml", "pack.yml", "pack.json")
EXECUTOR_MANIFEST_NAMES = ("executor.yaml", "executor.yml", "executor.json")
ORCHESTRATOR_MANIFEST_NAMES = ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json")
ELEMENT_KINDS = ("effects", "animations", "transitions")
ElementKind = str
_PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Content root keys recognised in pack.yaml content:{} declarations.
_CONTENT_ROOT_KEYS = ("executors", "orchestrators", "elements", "schemas", "examples", "docs")


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
    # Declared content roots from pack.yaml content:{} — empty dict means undeclared.
    declared_content: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "metadata": dict(self.metadata),
            "declared_content": dict(self.declared_content),
        }


# ---------------------------------------------------------------------------
# PackResolver — read-only, deterministic, manifest-based
# ---------------------------------------------------------------------------


class PackResolver:
    """Read-only resolver that discovers packs and their declared content roots.

    Two discovery concepts are kept separate:

    * **Pack-root scan** — iterate direct children under each ``pack_roots``
      directory, checking for a pack manifest or a ``.no-pack`` marker.
    * **In-pack content scan** — for each discovered pack, resolve executor /
      orchestrator / element roots from the ``content:{}`` declaration in
      ``pack.yaml``.  When a pack does not declare content roots the resolver
      falls back to the legacy ``rglob``-based scan so existing shipped packs
      continue to work until their manifests are migrated (T2).

    The resolver is deterministic (sorted ordering), detects duplicate pack
    ids, and surfaces structured findings for likely-pack directories that are
    missing a manifest.
    """

    def __init__(self, *pack_roots: str | Path) -> None:
        self._pack_roots: tuple[Path, ...] = tuple(
            Path(r).expanduser().resolve() for r in pack_roots
        )
        self._packs: tuple[PackDefinition, ...] = ()
        self._findings: list[str] = []
        self._packs_by_id: dict[str, PackDefinition] = {}
        self._resolve()

    # -- public properties ---------------------------------------------------

    @property
    def packs(self) -> tuple[PackDefinition, ...]:
        """All discovered packs in deterministic (sorted-by-id) order."""
        return self._packs

    @property
    def findings(self) -> tuple[str, ...]:
        """Warnings / informational findings from the last resolution pass."""
        return tuple(self._findings)

    def get_pack(self, pack_id: str) -> PackDefinition:
        """Return the pack definition for *pack_id* or raise KeyError."""
        try:
            return self._packs_by_id[pack_id]
        except KeyError:
            raise KeyError(f"unknown pack id {pack_id!r}") from None

    # -- content-root helpers (per-pack) -------------------------------------

    def iter_executor_roots(self, pack: PackDefinition) -> tuple[Path, ...]:
        """Executor component roots for *pack*, declared or legacy-fallback."""
        return self._resolve_content_roots(
            pack, "executors", EXECUTOR_MANIFEST_NAMES
        )

    def iter_orchestrator_roots(self, pack: PackDefinition) -> tuple[Path, ...]:
        """Orchestrator component roots for *pack*, declared or legacy-fallback."""
        return self._resolve_content_roots(
            pack, "orchestrators", ORCHESTRATOR_MANIFEST_NAMES
        )

    def iter_element_roots(
        self, pack: PackDefinition, *, kind: str | None = None
    ) -> tuple[tuple[ElementKind, Path], ...]:
        """Element roots for *pack*.

        If the pack declares ``content.elements``, scan the declared elements
        directory using the legacy layout (``elements/<kind>/<id>/``).
        Otherwise fall back to the legacy behaviour.
        """
        declared = pack.declared_content.get("elements")
        if declared:
            elements_root = pack.root / declared
            return _scan_element_roots(elements_root, kind=kind)
        return _legacy_iter_element_roots(pack, kind=kind)

    # -- internal resolution -------------------------------------------------

    def _resolve(self) -> None:
        """Run the pack-root scan across every configured pack root.

        Each *pack_roots* entry can be either:

        * A directory that **contains** pack sub-directories (the legacy
          ``astrid/packs/`` layout — the default).
        * A directory that **is** a pack (has ``pack.yaml`` at its root).
          Used by ``--pack-root examples/packs/minimal``.
        """
        all_packs: list[PackDefinition] = []
        seen: dict[str, Path] = {}

        for root in self._pack_roots:
            if not root.is_dir():
                self._findings.append(f"pack root does not exist: {root}")
                continue

            # -- Case 1: the root itself is a pack (has a pack manifest) -----
            self_manifest = pack_manifest_path(root)
            if self_manifest is not None:
                pack = _load_pack_manifest_resolver(self_manifest)
                if pack.id in seen:
                    raise PackValidationError(
                        f"duplicate pack id {pack.id!r}: {seen[pack.id]} and {self_manifest}"
                    )
                seen[pack.id] = self_manifest
                all_packs.append(pack)
                self._warn_undeclared_content(pack)
                continue  # don't scan children — it's a leaf pack

            # -- Case 2: root is a container of pack sub-directories ----------
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name == "__pycache__":
                    continue
                # .no-pack marker — explicit opt-out
                if (child / ".no-pack").exists():
                    continue

                manifest_path = pack_manifest_path(child)
                if manifest_path is None:
                    if _looks_like_pack_dir(child):
                        self._findings.append(
                            f"likely pack directory without manifest: {child}"
                        )
                    continue

                pack = _load_pack_manifest_resolver(manifest_path)
                if pack.id in seen:
                    raise PackValidationError(
                        f"duplicate pack id {pack.id!r}: {seen[pack.id]} and {manifest_path}"
                    )
                seen[pack.id] = manifest_path
                all_packs.append(pack)
                self._warn_undeclared_content(pack)

        all_packs.sort(key=lambda p: p.id)
        self._packs = tuple(all_packs)
        self._packs_by_id = {p.id: p for p in all_packs}

    def _warn_undeclared_content(self, pack: PackDefinition) -> None:
        """Raise on packs missing declared content roots.

        Sprint 9 portfolio rationalization: every shipped pack must declare
        ``content.executors`` and ``content.orchestrators`` in ``pack.yaml``.
        The legacy ``rglob`` fallback was removed; undeclared roots are now a
        hard ``PackValidationError``.
        After Sprint 9 portfolio rationalization, undeclared packs become a
        hard error.
        """
        for content_key in ("executors", "orchestrators"):
            if content_key not in pack.declared_content:
                raise PackValidationError(
                    f"pack {pack.id!r}: content.{content_key} not declared "
                    f"in pack.yaml — every pack must declare its component "
                    f"roots under content:{{}} (e.g. {content_key}: {content_key})"
                )

    def _resolve_content_roots(
        self,
        pack: PackDefinition,
        content_key: str,
        manifest_names: tuple[str, ...],
    ) -> tuple[Path, ...]:
        """Return component roots for *content_key* (executors/orchestrators).

        If the pack declares a root via ``content.<key>``, scan only that
        directory for component manifests (non-recursively).  Otherwise fall
        back to the legacy ``rglob`` scan.
        """
        declared = pack.declared_content.get(content_key)
        if not declared:
            raise PackValidationError(
                f"pack {pack.id!r}: content.{content_key} not declared in "
                f"pack.yaml — declare content.{content_key} (e.g. "
                f"{content_key}: {content_key}) to enable component discovery"
            )
        declared_root = pack.root / declared
        if not declared_root.is_dir():
            return ()
        roots = {
            path.parent.resolve()
            for manifest_name in manifest_names
            for path in declared_root.rglob(manifest_name)
            if "__pycache__" not in path.parts
        }
        return tuple(sorted(roots))


# ---------------------------------------------------------------------------
# Public helpers — keep existing signatures for backward compatibility
# ---------------------------------------------------------------------------


def packs_root() -> Path:
    return Path(__file__).resolve().parents[1] / "packs"


def discover_packs(root: str | Path | None = None) -> tuple[PackDefinition, ...]:
    source_root = Path(root) if root is not None else packs_root()
    resolver = PackResolver(source_root)
    # Surface findings as warnings on stderr so builders see them.
    for finding in resolver.findings:
        print(f"WARNING: {finding}", file=sys.stderr)
    return resolver.packs


def load_pack_manifest(path: str | Path) -> PackDefinition:
    manifest_path = Path(path).expanduser().resolve()
    raw = _load_yaml_payload(manifest_path)
    data = _require_mapping(raw, "pack")
    pack_id = _require_string(data, "id", "pack.id")
    _validate_pack_id(pack_id, "pack.id")
    root = manifest_path.parent
    if root.name != pack_id:
        raise PackValidationError(
            f"pack id {pack_id!r} must match folder name {root.name!r}"
        )
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PackValidationError("pack.metadata must be an object")
    declared_content = _extract_declared_content(data)
    return PackDefinition(
        id=pack_id,
        name=_optional_string(data, "name", "pack.name", default=pack_id),
        version=_optional_string(data, "version", "pack.version", default="0.1.0"),
        root=root,
        manifest_path=manifest_path,
        metadata=dict(metadata),
        declared_content=declared_content,
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


def validate_content_id_in_pack(
    content_id: str, pack: PackDefinition, *, content_type: str
) -> None:
    owner = qualified_id_pack_id(content_id, path=f"{content_type}.id")
    if owner != pack.id:
        raise PackValidationError(
            f"{content_type} id {content_id!r} belongs to pack {owner!r} "
            f"but was found in pack {pack.id!r}"
        )


def validate_element_pack_id(
    pack_id: str | None, pack: PackDefinition, *, element_root: str | Path
) -> None:
    if not pack_id:
        raise PackValidationError(
            f"element {Path(element_root)} is missing metadata.pack_id"
        )
    if pack_id != pack.id:
        raise PackValidationError(
            f"element {Path(element_root)} declares pack_id {pack_id!r} "
            f"but was found in pack {pack.id!r}"
        )


def iter_executor_roots(pack: PackDefinition) -> tuple[Path, ...]:
    declared = pack.declared_content.get("executors")
    if not declared:
        raise PackValidationError(
            f"pack {pack.id!r}: content.executors not declared in pack.yaml "
            f"— every pack must declare its executor root (e.g. "
            f"executors: executors)"
        )
    declared_root = pack.root / declared
    if not declared_root.is_dir():
        return ()
    roots = {
        path.parent.resolve()
        for manifest_name in EXECUTOR_MANIFEST_NAMES
        for path in declared_root.rglob(manifest_name)
        if "__pycache__" not in path.parts
    }
    return tuple(sorted(roots))


def iter_orchestrator_roots(pack: PackDefinition) -> tuple[Path, ...]:
    declared = pack.declared_content.get("orchestrators")
    if not declared:
        raise PackValidationError(
            f"pack {pack.id!r}: content.orchestrators not declared in "
            f"pack.yaml — every pack must declare its orchestrator root "
            f"(e.g. orchestrators: orchestrators)"
        )
    declared_root = pack.root / declared
    if not declared_root.is_dir():
        return ()
    roots = {
        path.parent.resolve()
        for manifest_name in ORCHESTRATOR_MANIFEST_NAMES
        for path in declared_root.rglob(manifest_name)
        if "__pycache__" not in path.parts
    }
    return tuple(sorted(roots))


def iter_element_roots(
    pack: PackDefinition, *, kind: str | None = None
) -> tuple[tuple[ElementKind, Path], ...]:
    return _legacy_iter_element_roots(pack, kind=kind)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_pack_manifest_resolver(path: Path) -> PackDefinition:
    """Load a pack manifest using yaml.safe_load for nested content support.

    This is the resolver-internal path.  The public ``load_pack_manifest``
    also uses ``_load_yaml_payload`` so nested ``content:`` blocks parse
    correctly across all callers.
    """
    raw = _load_yaml_payload(path)
    data = _require_mapping(raw, "pack")
    pack_id = _require_string(data, "id", "pack.id")
    _validate_pack_id(pack_id, "pack.id")
    root = path.parent
    if root.name != pack_id:
        raise PackValidationError(
            f"pack id {pack_id!r} must match folder name {root.name!r}"
        )
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PackValidationError("pack.metadata must be an object")
    declared_content = _extract_declared_content(data)
    return PackDefinition(
        id=pack_id,
        name=_optional_string(data, "name", "pack.name", default=pack_id),
        version=_optional_string(data, "version", "pack.version", default="0.1.0"),
        root=root,
        manifest_path=path,
        metadata=dict(metadata),
        declared_content=declared_content,
    )


def _extract_declared_content(data: dict[str, Any]) -> dict[str, str]:
    """Extract declared content roots from a pack manifest dict.

    Returns a dict mapping content keys (executors, orchestrators, elements,
    etc.) to relative paths.  Returns an empty dict when content is not
    declared or is not a mapping.
    """
    content = data.get("content")
    if not isinstance(content, dict):
        return {}
    declared: dict[str, str] = {}
    for key in _CONTENT_ROOT_KEYS:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            declared[key] = value.strip()
    return declared


def _load_yaml_payload(path: Path) -> Any:
    """Load a YAML (or JSON) manifest using yaml.safe_load for nested content."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PackValidationError(f"pack manifest not found: {path}") from exc
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PackValidationError(
                f"invalid JSON pack manifest {path}: {exc.msg}"
            ) from exc
    # Use yaml.safe_load for full YAML support (nested mappings, lists, etc.).
    # PyYAML is a hard dependency (see requirements.txt), so we no longer fall
    # back to a flat parser — surface the ImportError instead.
    try:
        import yaml as _yaml

        data = _yaml.safe_load(text)
    except ImportError as exc:
        raise PackValidationError(
            f"pyyaml is required to parse pack manifest {path}"
        ) from exc
    except Exception as exc:
        raise PackValidationError(
            f"invalid YAML pack manifest {path}: {exc}"
        ) from exc
    if data is None:
        raise PackValidationError(f"empty pack manifest: {path}")
    return data


def _content_roots(
    root: Path, manifest_names: tuple[str, ...], *, excluded_parts: set[str]
) -> tuple[Path, ...]:
    roots = {
        path.parent.resolve()
        for manifest_name in manifest_names
        for path in root.rglob(manifest_name)
        if "__pycache__" not in path.parts
        and excluded_parts.isdisjoint(path.relative_to(root).parts)
    }
    return tuple(sorted(roots))


def _scan_element_roots(
    elements_root: Path, *, kind: str | None = None
) -> tuple[tuple[ElementKind, Path], ...]:
    """Scan a declared elements directory for element roots.

    Expected layout: ``<elements_root>/<kind>/<element_id>/element.yaml``
    """
    kinds: Iterable[str] = ELEMENT_KINDS if kind is None else (kind,)
    roots: list[tuple[ElementKind, Path]] = []
    for element_kind in kinds:
        if element_kind not in ELEMENT_KINDS:
            raise PackValidationError(
                f"element kind must be one of {list(ELEMENT_KINDS)}"
            )
        kind_root = elements_root / element_kind
        if not kind_root.is_dir():
            continue
        roots.extend(
            (element_kind, child)
            for child in sorted(kind_root.iterdir())
            if child.is_dir()
        )
    return tuple(roots)


def _legacy_iter_element_roots(
    pack: PackDefinition, *, kind: str | None = None
) -> tuple[tuple[ElementKind, Path], ...]:
    """Legacy element root scan: pack.root / elements / <kind> / <id>."""
    kinds: Iterable[str] = ELEMENT_KINDS if kind is None else (kind,)
    roots: list[tuple[ElementKind, Path]] = []
    for element_kind in kinds:
        if element_kind not in ELEMENT_KINDS:
            raise PackValidationError(
                f"element kind must be one of {list(ELEMENT_KINDS)}"
            )
        kind_root = pack.root / "elements" / element_kind
        if not kind_root.is_dir():
            continue
        roots.extend(
            (element_kind, child)
            for child in sorted(kind_root.iterdir())
            if child.is_dir()
        )
    return tuple(roots)


def _looks_like_pack_dir(path: Path) -> bool:
    """Return True if *path* looks like it might be a pack directory.

    Heuristic: contains at least one subdirectory that holds an
    executor/orchestrator manifest, or an ``elements/`` directory.
    """
    # Quick check for elements dir
    if (path / "elements").is_dir():
        return True
    # Check a few subdirs for component manifests
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == "__pycache__":
            continue
        # Check for executor/orchestrator manifest
        for mf_name in EXECUTOR_MANIFEST_NAMES + ORCHESTRATOR_MANIFEST_NAMES:
            if (child / mf_name).is_file():
                return True
        # Check deeper (one more level for nested component dirs)
        try:
            for grandchild in child.iterdir():
                if grandchild.is_dir() and not grandchild.name.startswith("."):
                    for mf_name in EXECUTOR_MANIFEST_NAMES + ORCHESTRATOR_MANIFEST_NAMES:
                        if (grandchild / mf_name).is_file():
                            return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------------------
# Manifest payload loaders
# ---------------------------------------------------------------------------


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


def _optional_string(
    data: dict[str, Any], key: str, path: str, *, default: str
) -> str:
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
    "PackResolver",
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
