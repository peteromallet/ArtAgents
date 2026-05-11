"""Sprint 1 / T11: WriterContext auto-rebind end-to-end.

Scenario: Tab A is attached but has ``run_id=None`` (no run started yet).
Tab B (different session) starts a run via the lease-first ordering
(``write_lease_init`` + ``write_current_run``). Tab A's next mutating
verb opens a WriterContext, which on entry reads ``current_run.json``,
discovers ``run_id`` has moved on, calls ``dataclasses.replace`` on the
session, and REWRITES the on-disk session file with the new run_id.

This test reaches into WriterContext directly so it exercises the rebind
without the full ``astrid start`` lifecycle (T9 has its own coverage of
that path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.current_run import write_current_run
from astrid.core.session import paths as session_paths
from astrid.core.session.lease import write_lease_init
from astrid.core.session.model import Session
from astrid.core.session.writer import WriterContext


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def test_writer_context_auto_rebinds_session_run_id_on_entry(env: dict[str, Path]) -> None:
    # Tab A's session is attached but has run_id=None.
    sess_a = Session(
        id="S-A",
        project="demo",
        timeline=None,
        run_id=None,
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    sessions_dir = env["home"] / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sess_a.to_json(sessions_dir / "S-A.json")

    # Tab B mints a new run for the same project (lease-first ordering).
    pdir = env["projects"] / "demo"
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": "demo",
                "schema_version": 1,
                "slug": "demo",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    run_dir = pdir / "runs" / "01RUNNEW"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id=sess_a.id, plan_hash="")
    write_current_run("demo", "01RUNNEW")

    # Tab A's next verb opens WriterContext. __enter__ should auto-rebind
    # to "01RUNNEW" and rewrite the on-disk session file.
    pre = json.loads((sessions_dir / "S-A.json").read_text())
    assert pre["run_id"] is None

    with WriterContext(sess_a) as ctx:
        assert ctx.session.run_id == "01RUNNEW"
        assert ctx.run_dir == run_dir
        # The append works because lease.attached_session_id was seeded
        # with sess_a.id.
        ctx.append({"kind": "rebound", "i": 1})

    # Side effect: the on-disk session file now reflects the new run_id.
    post = json.loads((sessions_dir / "S-A.json").read_text())
    assert post["run_id"] == "01RUNNEW"
    assert post["last_used_at"] != pre["last_used_at"]
