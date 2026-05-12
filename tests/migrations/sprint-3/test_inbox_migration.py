"""Tests for inbox migration — legacy entries → schema_version:2 (Sprint 3 T23)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Locate the migration script and load it as a module.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MIGRATE_INBOX_PATH = _REPO_ROOT / "scripts" / "migrations" / "sprint-3" / "migrate_inbox.py"
_spec = importlib.util.spec_from_file_location("migrate_inbox", _MIGRATE_INBOX_PATH)
_migrate_inbox_mod = importlib.util.module_from_spec(_spec)
sys.modules["migrate_inbox"] = _migrate_inbox_mod
_spec.loader.exec_module(_migrate_inbox_mod)

REJECTED_DIR_NAME = _migrate_inbox_mod.REJECTED_DIR_NAME
_effective_plan = _migrate_inbox_mod._effective_plan
_migrate_entry = _migrate_inbox_mod._migrate_entry
_resolve_step_id = _migrate_inbox_mod._resolve_step_id
migrate_inbox_main = _migrate_inbox_mod.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_dir(tmp_path: Path, slug: str = "demo", run_id: str = "run-1") -> Path:
    run_dir = tmp_path / slug / "runs" / run_id
    run_dir.mkdir(parents=True)
    return run_dir


def _write_v2_plan(run_dir: Path, steps: list[dict], plan_id: str = "test") -> Path:
    """Write a Sprint 3 v2 plan.json."""
    plan_path = run_dir / "plan.json"
    payload = {"plan_id": plan_id, "version": 2, "steps": steps}
    plan_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return plan_path


def _write_inbox_entry(
    run_dir: Path,
    filename: str = "entry.json",
    **fields: object,
) -> Path:
    inbox_dir = run_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    entry_path = inbox_dir / filename
    entry_path.write_text(json.dumps(dict(fields)), encoding="utf-8")
    return entry_path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _resolve_step_id
# ---------------------------------------------------------------------------


def test_resolve_single_match_at_root(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    plan = _effective_plan(run_dir)
    count, paths = _resolve_step_id(plan, "s1")
    assert count == 1
    assert paths == [("s1",)]


def test_resolve_single_match_nested(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{
        "id": "parent",
        "adapter": "local",
        "version": 1,
        "children": [{"id": "child", "adapter": "local", "command": "echo", "version": 1}],
    }])
    plan = _effective_plan(run_dir)
    count, paths = _resolve_step_id(plan, "child")
    assert count == 1
    assert paths == [("parent", "child")]


def test_resolve_zero_matches(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    plan = _effective_plan(run_dir)
    count, paths = _resolve_step_id(plan, "nonexistent")
    assert count == 0
    assert paths == []


def test_resolve_cross_frame_ambiguity(tmp_path: Path) -> None:
    """Same step_id at two different depths → ambiguous."""
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [
        {"id": "dup", "adapter": "local", "command": "echo root", "version": 1},
        {
            "id": "parent",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "dup", "adapter": "local", "command": "echo nested", "version": 1}],
        },
    ])
    plan = _effective_plan(run_dir)
    count, paths = _resolve_step_id(plan, "dup")
    assert count == 2
    assert ("dup",) in paths
    assert ("parent", "dup") in paths


def test_resolve_sibling_ambiguity(tmp_path: Path) -> None:
    """Same step_id as siblings in two different groups."""
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [
        {
            "id": "g1",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "same", "adapter": "local", "command": "echo a", "version": 1}],
        },
        {
            "id": "g2",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "same", "adapter": "local", "command": "echo b", "version": 1}],
        },
    ])
    plan = _effective_plan(run_dir)
    count, paths = _resolve_step_id(plan, "same")
    assert count == 2
    assert ("g1", "same") in paths
    assert ("g2", "same") in paths


# ---------------------------------------------------------------------------
# _migrate_entry + cross-frame ambiguity
# ---------------------------------------------------------------------------


def test_single_match_rewrites_to_schema_version_2(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "e1.json", step_id="s1", payload={"x": 1})

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "rewritten" in reason
    assert "/".join(["s1"]) in reason

    new_payload = _read_json(entry_path)
    assert new_payload["schema_version"] == 2
    assert new_payload["plan_step_path"] == ["s1"]
    assert new_payload["step_version"] == 1
    assert new_payload["submitted_by_kind"] == "agent"


def test_zero_matches_rejected_to_dot_rejected(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "bad.json", step_id="nonexistent-id")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "step_id_not_found" in reason
    assert "nonexistent-id" in reason

    # Original file should have been moved to .rejected/.
    assert not entry_path.exists()


def test_cross_frame_ambiguity_rejected_with_correct_reason(tmp_path: Path) -> None:
    """Same step_id at depths 1 and 2 → .rejected/ with reason step_id_ambiguous_at_2_paths."""
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [
        {"id": "dup-id", "adapter": "local", "command": "echo root", "version": 1},
        {
            "id": "parent",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "dup-id", "adapter": "local", "command": "echo nested", "version": 1}],
        },
    ])
    entry_path = _write_inbox_entry(run_dir, "ambiguous.json", step_id="dup-id")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "step_id_ambiguous_at_2_paths" in reason
    assert "dup-id" in reason
    assert "parent/dup-id" in reason

    assert not entry_path.exists()
    assert rejected_dir.is_dir()
    # At least one file should be in .rejected/.
    rejected_files = list(rejected_dir.iterdir())
    assert len(rejected_files) >= 1


def test_already_schema_version_2_is_noop(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(
        run_dir, "already.json",
        schema_version=2,
        plan_step_path=["s1"],
        step_version=1,
        step_id="s1",
        submitted_by_kind="agent",
    )

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is False
    assert "already schema_version:2" in reason
    # File should still exist.
    assert entry_path.exists()


def test_missing_step_id_rejected(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "no-stepid.json", payload={"data": "value"})
    # No step_id field at all.

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "missing or empty step_id" in reason
    assert not entry_path.exists()


def test_unreadable_json_rejected(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = run_dir / "inbox" / "bad.json"
    run_dir / "inbox"
    (run_dir / "inbox").mkdir(parents=True, exist_ok=True)
    entry_path.write_text("not valid json{{{", encoding="utf-8")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "unreadable" in reason
    assert not entry_path.exists()


def test_non_dict_payload_rejected(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "list.json")
    # Write a list instead of an object.
    entry_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "not a JSON object" in reason
    assert not entry_path.exists()


def test_plan_step_path_is_list_of_strings(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [
        {
            "id": "parent",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "deep", "adapter": "local", "command": "echo", "version": 1}],
        },
    ])
    entry_path = _write_inbox_entry(run_dir, "deep.json", step_id="deep")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    new_payload = _read_json(entry_path)
    assert new_payload["plan_step_path"] == ["parent", "deep"]
    assert new_payload["schema_version"] == 2


def test_empty_step_id_rejected(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "empty.json", step_id="")

    plan = _effective_plan(run_dir)
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    acted, reason = _migrate_entry(entry_path, rejected_dir, plan)

    assert acted is True
    assert "missing or empty step_id" in reason


# ---------------------------------------------------------------------------
# main: --dry-run / --apply
# ---------------------------------------------------------------------------


def test_main_dry_run_previews_without_modifying(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    entry_path = _write_inbox_entry(run_dir, "e1.json", step_id="s1", data="old")
    original_bytes = entry_path.read_bytes()

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", str(tmp_path), "--dry-run"],
    )
    assert migrate_inbox_main() == 0
    # File should be unchanged in dry-run.
    assert entry_path.read_bytes() == original_bytes


def test_main_apply_commits_rewrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    _write_inbox_entry(run_dir, "e1.json", step_id="s1", data="old")

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_inbox_main() == 0

    new_payload = _read_json(run_dir / "inbox" / "e1.json")
    assert new_payload["schema_version"] == 2


def test_main_idempotent_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [{"id": "s1", "adapter": "local", "command": "echo", "version": 1}])
    _write_inbox_entry(run_dir, "e1.json", step_id="s1")

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_inbox_main() == 0

    after_first = (run_dir / "inbox" / "e1.json").read_bytes()

    assert migrate_inbox_main() == 0
    assert (run_dir / "inbox" / "e1.json").read_bytes() == after_first


def test_main_empty_workspace_exits_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "empty"
    projects_root.mkdir(parents=True)
    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", str(projects_root)],
    )
    assert migrate_inbox_main() == 0


def test_main_missing_root_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", "/nonexistent/inbox/root123"],
    )
    assert migrate_inbox_main() == 0


def test_apply_with_ambiguity_moves_to_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = _make_run_dir(tmp_path)
    _write_v2_plan(run_dir, [
        {"id": "dup", "adapter": "local", "command": "echo root", "version": 1},
        {
            "id": "parent",
            "adapter": "local",
            "version": 1,
            "children": [{"id": "dup", "adapter": "local", "command": "echo nested", "version": 1}],
        },
    ])
    _write_inbox_entry(run_dir, "amb.json", step_id="dup")

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_inbox.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_inbox_main() == 0

    # Original file should be gone.
    assert not (run_dir / "inbox" / "amb.json").exists()
    # .rejected/ should contain something.
    rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
    assert rejected_dir.is_dir()
    assert len(list(rejected_dir.iterdir())) >= 1