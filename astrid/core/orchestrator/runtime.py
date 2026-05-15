"""Resolver-backed runtime resolution for manifest-backed orchestrators.

Maps a qualified orchestrator id through the registry → owning
PackResolver → component root → manifest-declared runtime file and
entrypoint, providing one canonical path for runtime import.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from astrid.core.pack import PackResolver, packs_root

from .registry import OrchestratorRegistry
from .schema import OrchestratorDefinition


class OrchestratorRuntimeResolutionError(RuntimeError):
    """Raised when an orchestrator runtime cannot be resolved."""


def resolve_orchestrator_runtime(
    orchestrator_id: str,
    *,
    registry: OrchestratorRegistry | None = None,
    extra_pack_roots: tuple[str, ...] = (),
) -> tuple[str, str]:
    """Resolve an orchestrator's runtime module path and entrypoint name.

    Resolution chain:
      1. ``orchestrator_id`` → registry lookup → :class:`OrchestratorDefinition`
      2. ``metadata.source_pack`` → owning pack via :class:`PackResolver`
      3. owning pack → component root (directory containing the manifest)
      4. component root + ``metadata.runtime_file`` → absolute runtime file path
      5. :func:`resolve_python_module_from_file` → importable dotted module name
      6. ``metadata.runtime_entrypoint`` (default ``"main"``) → entrypoint name

    Args:
        orchestrator_id: Qualified id, e.g. ``"builtin.hype"``.
        registry: Optional pre-built registry.  When *None* a default
            registry is constructed using *extra_pack_roots*.
        extra_pack_roots: Extra pack root directories forwarded to the
            registry and resolver.

    Returns:
        ``(module_path, entrypoint_name)`` where *module_path* is a dotted
        Python import path and *entrypoint_name* is a callable attribute name.

    Raises:
        OrchestratorRuntimeResolutionError: If any step of the resolution
            chain fails.
    """
    # 1. Resolve the orchestrator definition.
    if registry is None:
        from .registry import load_default_registry

        registry = load_default_registry(extra_pack_roots=extra_pack_roots)

    orchestrator = registry.get(orchestrator_id)

    # 2. Determine the owning pack.
    source_pack = orchestrator.metadata.get("source_pack")
    if not source_pack:
        raise OrchestratorRuntimeResolutionError(
            f"orchestrator {orchestrator_id!r} has no source_pack in metadata"
        )

    # 3. Build a resolver that includes the pack.
    resolver = PackResolver(packs_root(), *extra_pack_roots)
    pack = resolver.get_pack(source_pack)

    # 4. Find the component root for this orchestrator.
    component_root = _find_component_root(orchestrator, pack, resolver)

    # 5. Resolve the runtime file.
    runtime_file = orchestrator.metadata.get("runtime_file", "run.py")
    if not isinstance(runtime_file, str) or not runtime_file:
        raise OrchestratorRuntimeResolutionError(
            f"orchestrator {orchestrator_id!r} has no metadata.runtime_file"
        )
    runtime_path = (component_root / runtime_file).resolve()
    if not runtime_path.is_file():
        raise OrchestratorRuntimeResolutionError(
            f"runtime file not found for {orchestrator_id!r}: {runtime_path}"
        )

    # 6. Convert the file path to an importable Python module path.
    module_path = resolve_python_module_from_file(runtime_path)
    if module_path is None:
        raise OrchestratorRuntimeResolutionError(
            f"cannot resolve Python module path for {runtime_path}"
        )

    # 7. Determine the entrypoint name.
    entrypoint = orchestrator.metadata.get("runtime_entrypoint", "main")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise OrchestratorRuntimeResolutionError(
            f"orchestrator {orchestrator_id!r} has invalid metadata.runtime_entrypoint"
        )

    return module_path, entrypoint


def resolve_python_module_from_file(file_path: Path) -> str | None:
    """Convert a ``.py`` file path to a dotted Python module path.

    Returns *None* when the file cannot be mapped to the current
    ``sys.path``.  The longest-matching prefix wins (most specific).
    """
    resolved = file_path.resolve()

    # If the file is a .py, strip the extension for the module name.
    if resolved.suffix == ".py":
        module_stem = resolved.with_suffix("")
    else:
        module_stem = resolved

    # Find the longest sys.path prefix that contains this file.
    best: tuple[int, str] | None = None
    for path_entry in sys.path:
        pe = Path(path_entry).resolve()
        try:
            relative = module_stem.relative_to(pe)
        except ValueError:
            continue
        depth = len(pe.parts)
        if best is None or depth > best[0]:
            best = (depth, ".".join(relative.parts))

    if best is not None:
        return best[1]

    return None


def _find_component_root(
    orchestrator: OrchestratorDefinition,
    pack: Any,
    resolver: PackResolver,
) -> Path:
    """Find the filesystem directory that contains *orchestrator*'s manifest.

    Iterates through the pack's declared orchestrator roots and returns the
    first one whose subdirectory name matches the orchestrator's short name
    (the part after ``pack_id.``).
    """
    short_name = orchestrator.id.split(".", 1)[-1]

    # Check the orchestrator_root from metadata first (set by folder loader).
    orchestrator_root = orchestrator.metadata.get("orchestrator_root")
    if orchestrator_root:
        candidate = Path(orchestrator_root)
        if candidate.is_dir():
            return candidate

    # Fall back: scan declared orchestrator roots for a matching subdirectory.
    for root in resolver.iter_orchestrator_roots(pack):
        candidate = root / short_name
        if candidate.is_dir():
            return candidate
        # The root itself might be the component root.
        if root.name == short_name:
            return root

    raise OrchestratorRuntimeResolutionError(
        f"cannot find component root for orchestrator {orchestrator.id!r} in pack {pack.id!r}"
    )


__all__ = [
    "OrchestratorRuntimeResolutionError",
    "resolve_orchestrator_runtime",
    "resolve_python_module_from_file",
]
