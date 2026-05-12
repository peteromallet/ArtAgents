"""Verify the legacy v1 plan reader path is removed (Sprint 5b T4/T12).

The conftest.py auto-migration shim intercepts ``_validate_plan`` in test
contexts and silently rewrites v1→v2.  These tests verify:
- ``_read_legacy_plan_payload`` is removed from plan.py
- v1 plans can still be migrated via the migrate_plans.py script
- Non-v2 versions are rejected with a message pointing at migrate_plans.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from astrid.core.task.plan import TaskPlanError, _validate_plan


# ── _read_legacy_plan_payload removed ────────────────────────────────────

def test_read_legacy_plan_payload_not_importable() -> None:
    """``_read_legacy_plan_payload`` was deleted from plan.py in Sprint 5b."""
    with pytest.raises(ImportError, match="_read_legacy_plan_payload"):
        from astrid.core.task.plan import _read_legacy_plan_payload  # noqa: F811


# ── v1 plans still migratable via script ────────────────────────────────

def test_migrate_plans_script_still_works(tmp_path: Path) -> None:
    """The migration script can still read and migrate v1 plans."""
    repo_root = Path(__file__).resolve().parents[2]
    mig_path = repo_root / "scripts" / "migrations" / "sprint-3" / "migrate_plans.py"
    spec = importlib.util.spec_from_file_location(
        "_test_migrate_plans", mig_path
    )
    mig = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mig
    spec.loader.exec_module(mig)

    # Write a v1 plan
    v1 = {
        "plan_id": "legacy",
        "version": 1,
        "steps": [
            {"id": "s1", "kind": "code", "command": "echo hi"},
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(v1), encoding="utf-8")

    # Migration script's own reader works
    payload = mig._read_legacy_plan_payload(plan_path)
    assert payload["version"] == 1

    # _migrate_step converts v1 step to v2 shape (adds adapter/version/assignee)
    migrated = mig._migrate_step(v1["steps"][0])
    assert migrated.get("adapter") is not None
    assert migrated.get("version") is not None


# ── Non-v2 versions rejected with migrate_plans.py reference ────────────

def test_non_v2_version_rejected_with_migration_hint() -> None:
    """A plan with version != 2 raises TaskPlanError pointing at the migration
    script.  (v1 is auto-migrated by conftest shim in test context, so we
    test with version=3.)"""
    v3_payload = {
        "plan_id": "future",
        "version": 3,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo future",
            },
        ],
    }

    with pytest.raises(TaskPlanError, match="migrate_plans.py"):
        _validate_plan(v3_payload)


# ── v2 payload passes cleanly ──────────────────────────────────────────

def test_v2_plan_passes_validation() -> None:
    """v2 payload passes through ``_validate_plan``."""
    v2_payload = {
        "plan_id": "p1",
        "version": 2,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo ok",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    plan = _validate_plan(v2_payload)
    assert plan.plan_id == "p1"
    assert plan.version == 2
    assert len(plan.steps) == 1