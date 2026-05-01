"""Banodoco website catalog client for opt-in external conductors."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from artagents.performers.banodoco_catalog import (
    BanodocoCatalogConfig,
    BanodocoCatalogError,
    _catalog_entries,
    _fetch_catalog_payload,
    _optional_string,
    _ref_value,
    _require_mapping,
    _require_string,
)
from artagents.performers.install import GitConductorSource, fetch_git_conductor_manifest

from .schema import ConductorDefinition, validate_conductor_definition


def load_banodoco_catalog_conductors(config: BanodocoCatalogConfig) -> tuple[ConductorDefinition, ...]:
    if not config.enabled:
        return ()
    if not config.catalog_url:
        raise BanodocoCatalogError("ARTAGENTS_BANODOCO_CATALOG_URL is required when Banodoco conductors are enabled")

    payload = _fetch_catalog_payload(config)
    conductors: list[ConductorDefinition] = []
    for row in _catalog_entries(payload, key="conductors", label="conductor"):
        catalog = _require_mapping(row.get("catalog", {}), "conductor.catalog")
        is_default = bool(catalog.get("default"))
        is_mandatory = bool(catalog.get("mandatory"))
        if (is_mandatory and config.include_mandatory) or (is_default and config.include_defaults):
            conductors.append(_load_catalog_conductor(row, config))
    return tuple(conductors)


def _load_catalog_conductor(row: dict[str, Any], config: BanodocoCatalogConfig) -> ConductorDefinition:
    expected_id = _require_string(row.get("expected_manifest_id"), "conductor.expected_manifest_id")
    targets = row.get("install_targets", [])
    if not isinstance(targets, list) or not targets:
        raise BanodocoCatalogError(f"Banodoco conductor {expected_id!r} has no install targets")

    target = _require_mapping(targets[0], "conductor.install_targets[0]")
    source_type = _require_string(target.get("source_type"), "install_target.source_type")
    if source_type != "git":
        raise BanodocoCatalogError(f"Banodoco conductor {expected_id!r} install target must be git for ArtAgents v1")

    target_expected_id = target.get("expected_conductor_id", target.get("expected_node_id"))
    manifest = fetch_git_conductor_manifest(
        GitConductorSource(
            repo_url=_require_string(target.get("repo_url"), "install_target.repo_url"),
            manifest_path=_require_string(target.get("manifest_path"), "install_target.manifest_path"),
            expected_conductor_id=_require_string(target_expected_id, "install_target.expected_conductor_id"),
            commit_sha=_optional_string(_ref_value(target, "commit_sha"), "install_target.ref.commit_sha"),
            tag=_optional_string(_ref_value(target, "tag"), "install_target.ref.tag"),
            branch=_optional_string(_ref_value(target, "branch"), "install_target.ref.branch"),
            source_ref=_optional_string(_ref_value(target, "source_ref"), "install_target.ref.source_ref"),
            install_subdir=_optional_string(target.get("install_subdir"), "install_target.install_subdir"),
        ),
        cache_dir=config.cache_dir,
        refresh=config.refresh,
    )
    conductor = validate_conductor_definition(manifest)
    if conductor.id != expected_id:
        raise BanodocoCatalogError(
            f"Banodoco catalog identity mismatch: expected {expected_id!r}, fetched manifest {conductor.id!r}"
        )
    metadata = dict(conductor.metadata)
    metadata.update({"source": "banodoco_catalog", "banodoco_catalog_id": row.get("id"), "banodoco_slug": row.get("slug")})
    return validate_conductor_definition(replace(conductor, metadata=metadata))


__all__ = [
    "BanodocoCatalogConfig",
    "BanodocoCatalogError",
    "GitConductorSource",
    "fetch_git_conductor_manifest",
    "load_banodoco_catalog_conductors",
]
