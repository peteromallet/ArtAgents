"""Sprint 5b: export verb tests (T9 / T13).

Tests timeline export and project export tarball creation, including
--include-aborted toggling and MANIFEST.txt correctness.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from astrid.core.task.events import ZERO_HASH, _event_hash


# ── Shared helpers ──────────────────────────────────────────────────────


def _build_chain(raw: list[dict]) -> list[dict]:
    chain: list[dict] = []
    prev = ZERO_HASH
    for r in raw:
        ev = dict(r)
        ev["hash"] = _event_hash(prev, ev)
        chain.append(ev)
        prev = ev["hash"]
    return chain


def _write_events(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True, separators=(",", ":")) + "\n")


# Valid ULID-format run IDs
R1 = "01JQZ1AAAAAA00000000000000"
R2 = "01JQZ2AAAAAA00000000000000"


# ── Build a 2-run timeline fixture ──────────────────────────────────────


@pytest.fixture
def timeline_fixture(tmp_projects_root: Path) -> dict:
    """Create a project with a timeline, two runs (1 completed, 1 aborted)."""
    from astrid.core.project.project import create_project
    from astrid.core.project.paths import project_dir
    from astrid.core.task.active_run import write_active_run
    from astrid.core.task.plan import compute_plan_hash
    from astrid.core.timeline import crud

    slug = "export-proj"
    create_project(slug, root=tmp_projects_root)
    proj_root = project_dir(slug, root=tmp_projects_root)

    # Timeline
    result = crud.create_timeline(slug, "main-line", name="Main Line")
    timeline_ulid = result["ulid"]
    timeline_dir = proj_root / "timelines" / timeline_ulid

    # Plan
    plan_payload = {
        "plan_id": "p-export",
        "version": 2,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo done",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    plan_path = proj_root / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")
    plan_hash = compute_plan_hash(plan_path)

    runs_dir = proj_root / "runs"

    # ── Run 1: completed ────────────────────────────────────────────────
    run1_root = runs_dir / R1
    run1_root.mkdir(parents=True, exist_ok=True)

    events1 = _build_chain([
        {"kind": "run_started", "run_id": R1, "plan_hash": plan_hash, "ts": "2026-01-01T00:00:00Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T00:00:01Z",
         "cost": {"amount": 0.12, "currency": "USD", "source": "claude"}},
        {"kind": "run_completed", "ts": "2026-01-01T00:00:02Z"},
    ])
    _write_events(run1_root / "events.jsonl", events1)
    (run1_root / "run.json").write_text(json.dumps({
        "run_id": R1, "plan_hash": plan_hash, "consumes": ["source.mp4"],
    }), encoding="utf-8")
    produces1 = run1_root / "produces"
    produces1.mkdir(exist_ok=True)
    (produces1 / "output.mp4").write_bytes(b"fake video content")
    (produces1 / "metadata.json").write_text('{"ok": true}')

    # ── Run 2: aborted ──────────────────────────────────────────────────
    run2_root = runs_dir / R2
    run2_root.mkdir(parents=True, exist_ok=True)

    events2 = _build_chain([
        {"kind": "run_started", "run_id": R2, "plan_hash": plan_hash, "ts": "2026-01-01T01:00:00Z"},
        {"kind": "run_aborted", "ts": "2026-01-01T01:00:01Z"},
    ])
    _write_events(run2_root / "events.jsonl", events2)
    (run2_root / "run.json").write_text(json.dumps({
        "run_id": R2, "plan_hash": plan_hash,
    }), encoding="utf-8")
    produces2 = run2_root / "produces"
    produces2.mkdir(exist_ok=True)
    (produces2 / "partial.txt").write_text("incomplete")

    write_active_run(slug, run_id=R1, plan_hash=plan_hash, root=tmp_projects_root)

    # Write manifest.json with both runs contributing
    manifest_path = timeline_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "contributing_runs": [R1, R2],
        "final_outputs": [],
        "tombstoned_at": None,
    }), encoding="utf-8")

    return {
        "slug": slug,
        "proj_root": proj_root,
        "timeline_ulid": timeline_ulid,
        "timeline_dir": timeline_dir,
        "run1_id": R1,
        "run2_id": R2,
        "runs_dir": runs_dir,
        "plan_hash": plan_hash,
    }


# ── Timeline export ─────────────────────────────────────────────────────


def test_timeline_export_excludes_aborted_by_default(
    tmp_projects_root: Path, timeline_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aborted runs should be excluded from the export bundle by default."""
    from astrid.core.timeline import cli as tm_cli
    from unittest.mock import MagicMock
    import argparse

    mock_session = MagicMock()
    mock_session.project = timeline_fixture["slug"]
    monkeypatch.setattr(tm_cli, "resolve_current_session", lambda: mock_session)

    out_path = tmp_projects_root / "bundle.tar.gz"
    args = argparse.Namespace(
        slug="main-line",
        out=str(out_path),
        include_aborted=False,
    )

    rc = tm_cli.cmd_export(args)
    assert rc == 0

    assert out_path.is_file()
    with tarfile.open(out_path, "r:gz") as tf:
        names = sorted(tf.getnames())
        assert "assembly.json" in names
        assert "manifest.json" in names
        assert "display.json" in names
        assert f"runs/{timeline_fixture['run1_id']}/events.jsonl" in names
        assert f"runs/{timeline_fixture['run1_id']}/plan.json" in names
        assert f"runs/{timeline_fixture['run1_id']}/run.json" in names
        assert f"runs/{timeline_fixture['run1_id']}/produces/output.mp4" in names
        # Aborted run excluded
        run2_in_names = any(timeline_fixture['run2_id'] in n for n in names)
        assert not run2_in_names, f"Aborted run {timeline_fixture['run2_id']} found in export"
        assert "MANIFEST.txt" in names

        # Verify MANIFEST.txt entries
        manifest_data = tf.extractfile("MANIFEST.txt").read().decode("utf-8")
        for line in manifest_data.strip().split("\n"):
            sha, rel = line.split("  ", 1)
            member = tf.getmember(rel)
            content = tf.extractfile(member).read()
            assert sha == hashlib.sha256(content).hexdigest()


def test_timeline_export_includes_aborted_with_flag(
    tmp_projects_root: Path, timeline_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--include-aborted``, aborted runs ARE bundled."""
    from astrid.core.timeline import cli as tm_cli
    from unittest.mock import MagicMock
    import argparse

    mock_session = MagicMock()
    mock_session.project = timeline_fixture["slug"]
    monkeypatch.setattr(tm_cli, "resolve_current_session", lambda: mock_session)

    out_path = tmp_projects_root / "bundle-with-aborted.tar.gz"
    args = argparse.Namespace(
        slug="main-line",
        out=str(out_path),
        include_aborted=True,
    )

    rc = tm_cli.cmd_export(args)
    assert rc == 0

    with tarfile.open(out_path, "r:gz") as tf:
        names = sorted(tf.getnames())
        assert f"runs/{timeline_fixture['run1_id']}/events.jsonl" in names
        assert f"runs/{timeline_fixture['run2_id']}/events.jsonl" in names


# ── Project export ──────────────────────────────────────────────────────


def test_project_export_includes_all_timelines(
    tmp_projects_root: Path, timeline_fixture: dict
) -> None:
    """Project export bundles all timelines and their contributing runs."""
    from astrid.core.project.cli import _cmd_project_export
    import argparse

    out_path = tmp_projects_root / "project-bundle.tar.gz"
    args = argparse.Namespace(
        project=timeline_fixture["slug"],
        out=str(out_path),
        include_aborted=False,
    )

    rc = _cmd_project_export(args)
    assert rc == 0

    with tarfile.open(out_path, "r:gz") as tf:
        names = sorted(tf.getnames())
        ulid = timeline_fixture["timeline_ulid"]
        assert f"timelines/{ulid}/assembly.json" in names
        assert f"timelines/{ulid}/manifest.json" in names
        assert f"timelines/{ulid}/display.json" in names
        assert f"runs/{timeline_fixture['run1_id']}/events.jsonl" in names
        assert "MANIFEST.txt" in names