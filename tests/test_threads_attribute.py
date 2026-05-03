from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from artagents.threads.attribute import attribute_run, enforce_lifecycle
from artagents.threads.ids import generate_run_id, generate_thread_id
from artagents.threads.index import ThreadIndexStore
from artagents.threads.schema import make_thread_record


NOW = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)


def test_attribute_explicit_thread_creates_and_records_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    run_id = generate_run_id()

    decision = attribute_run(
        repo_root=repo,
        request=SimpleNamespace(thread=thread_id, inputs={}),
        run_id=run_id,
        out_path=repo / "runs" / "explicit",
        label_seed="test.writer",
        now=NOW,
    )

    assert decision.thread_id == thread_id
    assert decision.source == "explicit"
    assert decision.created is True
    assert decision.run_number == 1
    index = ThreadIndexStore(repo).read()
    assert index["active_thread_id"] == thread_id
    assert index["threads"][thread_id]["run_ids"] == [run_id]


def test_attribute_infers_lineage_from_runs_input_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    parent_thread = generate_thread_id()
    source = repo / "runs" / "source"
    source.mkdir(parents=True)
    (source / "asset.png").write_text("asset", encoding="utf-8")
    (source / "run.json").write_text(
        json.dumps({"schema_version": 1, "run_id": generate_run_id(), "thread_id": parent_thread}),
        encoding="utf-8",
    )
    ThreadIndexStore(repo).write(
        {"schema_version": 1, "active_thread_id": None, "threads": {parent_thread: make_thread_record(thread_id=parent_thread, label="Parent")}}
    )

    decision = attribute_run(
        repo_root=repo,
        request=SimpleNamespace(thread=None, inputs={"image": source / "asset.png"}),
        run_id=generate_run_id(),
        out_path=repo / "runs" / "child",
        label_seed="child",
        now=NOW,
    )

    assert decision.thread_id == parent_thread
    assert decision.source == "lineage"


def test_attribute_uses_active_open_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    active = generate_thread_id()
    ThreadIndexStore(repo).write(
        {"schema_version": 1, "active_thread_id": active, "threads": {active: make_thread_record(thread_id=active, label="Active")}}
    )

    decision = attribute_run(
        repo_root=repo,
        request=SimpleNamespace(thread=None, inputs={}),
        run_id=generate_run_id(),
        out_path=repo / "runs" / "active",
        label_seed="active",
        now=NOW,
    )

    assert decision.thread_id == active
    assert decision.source == "active"


def test_attribute_reopens_recent_archived_active_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    active = generate_thread_id()
    archived_at = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    thread = make_thread_record(thread_id=active, label="Recent", status="archived", archived_at=archived_at, updated_at=archived_at)
    ThreadIndexStore(repo).write({"schema_version": 1, "active_thread_id": active, "threads": {active: thread}})

    decision = attribute_run(
        repo_root=repo,
        request=SimpleNamespace(thread=None, inputs={}),
        run_id=generate_run_id(),
        out_path=repo / "runs" / "recent",
        label_seed="recent",
        now=NOW,
    )

    assert decision.thread_id == active
    assert decision.source == "reopened_active"
    assert decision.reopened is True
    assert decision.notice
    updated = ThreadIndexStore(repo).read()["threads"][active]
    assert updated["status"] == "open"
    assert updated["archived_at"] is None


def test_lifecycle_archives_stale_open_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    stale = generate_thread_id()
    old = (NOW - timedelta(days=9)).isoformat().replace("+00:00", "Z")
    thread = make_thread_record(thread_id=stale, label="Stale", created_at=old, updated_at=old)
    ThreadIndexStore(repo).write({"schema_version": 1, "active_thread_id": stale, "threads": {stale: thread}})

    index = enforce_lifecycle(repo, now=NOW)

    assert index["threads"][stale]["status"] == "archived"
    assert index["threads"][stale]["archived_at"] == NOW.isoformat().replace("+00:00", "Z")


def test_attribute_falls_back_to_new_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)

    decision = attribute_run(
        repo_root=repo,
        request=SimpleNamespace(thread=None, inputs={}),
        run_id=generate_run_id(),
        out_path=repo / "runs" / "new",
        label_seed="new",
        now=NOW,
    )

    assert decision.source == "new"
    assert decision.created is True


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    return repo
