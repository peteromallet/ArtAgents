"""Module loader and JSON compiler for the orchestrate DSL (Phase 4).

`resolve_orchestrator(qid)` imports `<packs_root>/<pack>/<name>.py` via
`importlib.util.spec_from_file_location` (without polluting sys.modules across
test fixtures) and returns the module-level ``_PlanBuilder``.

`compile_to_path(qid)` resolves, calls ``_PlanBuilder.to_dict()`` (which
round-trips through ``astrid.core.task.plan.load_plan``), and writes the
manifest to ``<pack-root>/build/<name>.json`` as deterministic JSON.

Inline expansion of nested string-form refs (``nested(plan="<pack>.<name>")``)
runs during ``to_dict()``: ``compile_to_path`` passes itself in as the
``_resolver`` and threads a ``_visiting`` set keyed on qualified id so a
self- or mutually-recursive reference raises ``OrchestrateDefinitionError``
instead of recursing forever (FLAG-005).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Optional

from astrid._paths import REPO_ROOT

from .dsl import OrchestrateDefinitionError, _PlanBuilder

DEFAULT_PACKS_ROOT = REPO_ROOT / "astrid" / "packs"


def _qualified_split(qualified_id: str) -> tuple[str, str]:
    if not isinstance(qualified_id, str) or not qualified_id:
        raise OrchestrateDefinitionError(
            "qualified id must be a non-empty string of the form '<pack>.<name>'"
        )
    if "." not in qualified_id:
        raise OrchestrateDefinitionError(
            f"qualified id {qualified_id!r} must be '<pack>.<name>'"
        )
    pack, _, name = qualified_id.partition(".")
    if not pack or not name or "." in name:
        raise OrchestrateDefinitionError(
            f"qualified id {qualified_id!r} must be exactly '<pack>.<name>' "
            "(no extra dots)"
        )
    return pack, name


def _load_module_isolated(module_path: Path, qualified_id: str):
    unique = f"_astrid_orchestrate_{qualified_id.replace('.', '_')}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, module_path)
    if spec is None or spec.loader is None:
        raise OrchestrateDefinitionError(
            f"could not load orchestrator module at {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(unique, None)
        raise OrchestrateDefinitionError(
            f"failed to import orchestrator module {module_path}: {exc}"
        ) from exc
    finally:
        sys.modules.pop(unique, None)
    return module


def _resolve_orchestrator_module_path(
    qualified_id: str,
    packs_root: Path,
) -> Path | None:
    """Find the ``<name>.py`` file for a DSL orchestrator.

    Tries the resolver-backed path first (using PackResolver to discover
    the pack and its declared orchestrator roots), then falls back to the
    legacy ``<packs_root>/<pack>/<name>.py`` convention.
    """
    pack, name = _qualified_split(qualified_id)

    # 1. Resolver-backed: use PackResolver to find the pack.
    try:
        from astrid.core.pack import PackResolver

        resolver = PackResolver(packs_root)
        try:
            pack_def = resolver.get_pack(pack)
        except KeyError:
            pass
        else:
            # Check each declared orchestrator root for <name>.py.
            for orch_root in resolver.iter_orchestrator_roots(pack_def):
                candidate = orch_root / f"{name}.py"
                if candidate.is_file():
                    return candidate
                # Also check a subdirectory matching the name (manifest-backed
                # orchestrator) — the DSL fixture might be at
                # <orch_root>/<name>/<name>.py or <orch_root>/<name>.py.
                sub_candidate = orch_root / name / f"{name}.py"
                if sub_candidate.is_file():
                    return sub_candidate
    except Exception:
        # Resolver failure should not prevent legacy fallback.
        pass

    # 2. Legacy fallback: <packs_root>/<pack>/<name>.py
    legacy = packs_root / pack / f"{name}.py"
    if legacy.is_file():
        return legacy

    return None


def resolve_orchestrator(
    qualified_id: str,
    *,
    packs_root: Optional[Path] = None,
    _visiting: Optional[set] = None,
) -> _PlanBuilder:
    pack, name = _qualified_split(qualified_id)
    root = Path(packs_root) if packs_root is not None else DEFAULT_PACKS_ROOT

    # Sprint 2 (T8): try resolver-backed component-root lookup first so
    # declared content roots drive discovery.  Falls back to the legacy
    # <pack_root>/<pack>/<name>.py convention for non-registry fixtures.
    module_path = _resolve_orchestrator_module_path(qualified_id, root)
    if module_path is None:
        raise OrchestrateDefinitionError(
            f"orchestrator {qualified_id!r}: module file not found "
            f"(checked resolver-backed and legacy paths under {root})"
        )
    module = _load_module_isolated(module_path, qualified_id)

    builders: list[_PlanBuilder] = [
        value
        for value in vars(module).values()
        if isinstance(value, _PlanBuilder)
    ]
    if not builders:
        raise OrchestrateDefinitionError(
            f"orchestrator {qualified_id!r}: module {module_path} defines no "
            "_PlanBuilder (use plan(...) or @orchestrator(...))"
        )
    matching = [b for b in builders if b.plan_id == qualified_id]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        raise OrchestrateDefinitionError(
            f"orchestrator {qualified_id!r}: module {module_path} defines "
            f"multiple plans with plan_id {qualified_id!r}"
        )
    if len(builders) == 1:
        return builders[0]
    ids = sorted({b.plan_id for b in builders})
    raise OrchestrateDefinitionError(
        f"orchestrator {qualified_id!r}: module {module_path} defines multiple "
        f"plans {ids}; declare exactly one with plan_id={qualified_id!r}"
    )


def _resolver_for(packs_root: Optional[Path]):
    def _resolve(qualified_id: str, *, _visiting: Optional[set] = None) -> _PlanBuilder:
        return resolve_orchestrator(
            qualified_id, packs_root=packs_root, _visiting=_visiting
        )

    return _resolve


def _resolve_build_path(
    qualified_id: str,
    packs_root: Path,
) -> Path | None:
    """Find the build output directory for a compiled orchestrator plan.

    Uses PackResolver to locate the pack, then returns
    ``<pack_root>/build/<name>.json``.  Falls back to *None* if the pack
    cannot be resolved, letting the caller use the legacy convention.
    """
    pack, name = _qualified_split(qualified_id)
    try:
        from astrid.core.pack import PackResolver

        resolver = PackResolver(packs_root)
        pack_def = resolver.get_pack(pack)
        return pack_def.root / "build" / f"{name}.json"
    except Exception:
        return None


def compile_to_path(
    qualified_id: str,
    *,
    dest: Optional[Path] = None,
    packs_root: Optional[Path] = None,
) -> Path:
    pack, name = _qualified_split(qualified_id)
    builder = resolve_orchestrator(qualified_id, packs_root=packs_root)
    payload = builder.to_dict(_resolver=_resolver_for(packs_root))
    root = Path(packs_root) if packs_root is not None else DEFAULT_PACKS_ROOT
    if dest is not None:
        out_path = Path(dest)
    else:
        # Sprint 2 (T8): try resolver-backed output path first.
        out_path = _resolve_build_path(qualified_id, root)
        if out_path is None:
            out_path = root / pack / "build" / f"{name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path
