"""Integration tests proving the converted seinfeld pack uses the same
resolver, validation, inspect, and runtime code as external packs.

These tests are the Sprint 8 acceptance check: a real built-in pack must
flow through the external pack contract end-to-end.
"""

from __future__ import annotations

from pathlib import Path

from astrid.core.executor.registry import load_default_registry
from astrid.core.orchestrator.registry import (
    load_default_registry as load_default_orchestrator_registry,
)
from astrid.packs.validate import validate_pack


SEINFELD_ROOT = Path("astrid/packs/seinfeld")

EXPECTED_EXECUTORS = {
    "seinfeld.lora_register",
    "seinfeld.repo_setup",
    "seinfeld.aitoolkit_stage",
    "seinfeld.aitoolkit_train",
    "seinfeld.lora_eval_grid",
}

EXPECTED_ORCHESTRATORS = {
    "seinfeld.lora_train",
    "seinfeld.dataset_build",
}


def test_validate_zero_errors() -> None:
    errors, _warnings = validate_pack(SEINFELD_ROOT)
    assert errors == [], f"validate_pack reported errors: {errors}"


def test_no_stray_manifest_warnings() -> None:
    _errors, warnings = validate_pack(SEINFELD_ROOT)
    stray = [w for w in warnings if "stray manifest" in w]
    assert stray == [], f"unexpected stray manifest warnings: {stray}"


def test_executors_list_includes_seinfeld() -> None:
    registry = load_default_registry()
    ids = {executor.id for executor in registry.list()}
    missing = EXPECTED_EXECUTORS - ids
    assert not missing, f"executor registry missing seinfeld ids: {sorted(missing)}"


def test_orchestrators_list_includes_seinfeld() -> None:
    registry = load_default_orchestrator_registry()
    ids = {orchestrator.id for orchestrator in registry.list()}
    missing = EXPECTED_ORCHESTRATORS - ids
    assert not missing, f"orchestrator registry missing seinfeld ids: {sorted(missing)}"


def test_flat_layout_warning_NOT_emitted() -> None:
    _errors, warnings = validate_pack(SEINFELD_ROOT)
    flat = [w for w in warnings if "flat layout" in w]
    assert flat == [], f"restructured seinfeld unexpectedly emitted flat-layout warning(s): {flat}"
