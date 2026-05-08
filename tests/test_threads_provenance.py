from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.audit import AuditContext
from astrid.threads.ids import generate_run_id, generate_thread_id
from astrid.threads.index import ThreadIndexStore
from astrid.threads.record import build_run_record, finalize_run_record, write_run_record
from astrid.threads.schema import make_thread_record


def test_provenance_bridges_audit_ledger_and_hash_ancestry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    _set_thread(repo, thread_id, "Campaign")
    parent_run_id = generate_run_id()
    parent_out = repo / "runs" / "parent"
    parent_asset = parent_out / "asset.txt"
    parent_asset.parent.mkdir(parents=True)
    parent_asset.write_text("shared artifact", encoding="utf-8")
    parent_record = finalize_run_record(
        build_run_record(run_id=parent_run_id, thread_id=thread_id, kind="executor", out_path=parent_out, repo_root=repo),
        repo_root=repo,
        out_path=parent_out,
        returncode=0,
    )
    write_run_record(parent_record, parent_out / "run.json")

    child_out = repo / "runs" / "child"
    child_out.mkdir(parents=True)
    audit = AuditContext.for_run(child_out)
    source_id = audit.register_asset(kind="source", path=parent_asset, label="Source")
    output_id = audit.register_asset(kind="text", path=parent_asset, label="Output", parents=[source_id])
    audit.register_node(stage="child", parents=[source_id], outputs=[output_id])

    child_record = finalize_run_record(
        build_run_record(
            run_id=generate_run_id(),
            thread_id=thread_id,
            kind="executor",
            out_path=child_out,
            repo_root=repo,
            inputs={"source": parent_asset},
            parent_run_ids=[{"run_id": parent_run_id, "kind": "chosen", "group": "grp1"}],
        ),
        repo_root=repo,
        out_path=child_out,
        returncode=0,
    )

    provenance = child_record["provenance"]
    assert provenance["schema_version"] == 1
    assert provenance["thread_id"] == thread_id
    assert provenance["thread_label"] == "Campaign"
    assert provenance["parent_run_ids"] == [{"group": "grp1", "kind": "chosen", "run_id": parent_run_id}]
    assert {"run_id": parent_run_id, "kind": "chosen", "group": "grp1"} in provenance["contributing_runs"]
    assert any(item["kind"] == "artifact_hash" and item["run_id"] == parent_run_id for item in provenance["contributing_runs"])
    assert source_id in provenance["audit"]["asset_ids"]
    assert source_id in provenance["audit"]["parent_asset_ids"]
    assert output_id in provenance["audit"]["asset_ids"]


def test_hype_metadata_gets_denormalized_pipeline_provenance_and_survives_index_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    _set_thread(repo, thread_id, "Campaign")
    out = repo / "runs" / "hype"
    out.mkdir(parents=True)
    (out / "hype.metadata.json").write_text(json.dumps({"pipeline": {"steps_run": ["cut"]}, "clips": {}, "sources": {}}), encoding="utf-8")

    record = finalize_run_record(
        build_run_record(run_id=generate_run_id(), thread_id=thread_id, kind="executor", executor_id="builtin.cut", out_path=out, repo_root=repo),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )
    write_run_record(record, out / "run.json")
    (repo / ".astrid" / "threads.json").unlink()

    metadata = json.loads((out / "hype.metadata.json").read_text(encoding="utf-8"))
    provenance = metadata["pipeline"]["provenance"]
    assert provenance["thread_id"] == thread_id
    assert provenance["thread_label"] == "Campaign"
    assert provenance["run_id"] == record["run_id"]
    assert provenance["agent_version"]
    assert provenance["starred"] is False
    assert "chosen_from_groups" not in json.dumps(metadata)


def test_private_brief_keeps_hash_and_suppresses_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    _set_thread(repo, thread_id, "Campaign")
    out = repo / "runs" / "private"
    private = out / "private"
    private.mkdir(parents=True)
    brief = private / "brief.txt"
    brief.write_text("private brief plaintext", encoding="utf-8")

    record = finalize_run_record(
        build_run_record(
            run_id=generate_run_id(),
            thread_id=thread_id,
            kind="executor",
            out_path=out,
            repo_root=repo,
            brief=brief,
        ),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )

    encoded = json.dumps(record)
    assert record["brief_content_sha256"]
    assert not (out / "brief.copy.txt").exists()
    assert "private brief plaintext" not in encoded
    brief_artifact = next(item for item in record["input_artifacts"] if item["kind"] == "brief")
    assert brief_artifact["private"] is True
    assert "path" not in brief_artifact
    assert brief_artifact["label"] == "brief.txt"


def test_provenance_excludes_def_trimmed_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    _set_thread(repo, thread_id, "Campaign")
    out = repo / "runs" / "trimmed"
    record = finalize_run_record(
        build_run_record(run_id=generate_run_id(), thread_id=thread_id, kind="executor", out_path=out, repo_root=repo),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )

    encoded = json.dumps(record)
    for forbidden in ("host_id", "preview_modes", "chosen_from_groups", "cost_usd", "latency_ms"):
        assert forbidden not in encoded


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    thread_id = generate_thread_id()
    # The tests overwrite this id when needed; keeping one thread here ensures
    # helper code always has a valid index to read.
    ThreadIndexStore(repo).write(
        {"schema_version": 1, "active_thread_id": thread_id, "threads": {thread_id: make_thread_record(thread_id=thread_id, label="Unused")}}
    )
    return repo


def _set_thread(repo: Path, thread_id: str, label: str) -> None:
    ThreadIndexStore(repo).write(
        {"schema_version": 1, "active_thread_id": thread_id, "threads": {thread_id: make_thread_record(thread_id=thread_id, label=label)}}
    )
