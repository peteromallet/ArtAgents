from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid import pipeline
from astrid.threads import cli
from astrid.threads.ids import generate_run_id, generate_thread_id
from astrid.threads.index import ThreadIndexStore
from astrid.threads.record import build_run_record, finalize_run_record, write_run_record


def test_thread_cli_lifecycle_show_no_content_and_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Threads internal-library lifecycle exercised through astrid.threads.cli.

    Sprint 1 / T12 retired the user-facing ``astrid thread`` CLI verb from
    ``astrid.pipeline``. The internal library (DEC-001) is retained; this
    test now exercises only the library-level CLI, not the pipeline route.
    """

    repo = _repo(tmp_path, monkeypatch)

    assert cli.main(["new", "Launch"]) == 0
    new_output = capsys.readouterr().out
    thread_id = new_output.split()[0]

    # The pipeline-level `astrid thread list` verb was removed in T8/T12.
    # The library-level equivalent still works.
    assert cli.main(["list"]) == 0
    list_output = capsys.readouterr().out
    assert thread_id in list_output
    assert "Launch" in list_output

    run_id = _write_run(repo, thread_id)
    assert cli.main(["show", "@active", "--no-content", "--json"]) == 0
    show_output = capsys.readouterr().out
    payload = json.loads(show_output)
    assert payload["thread"]["thread_id"] == thread_id
    assert payload["runs"][0]["run_id"] == run_id
    assert "secret brief body" not in show_output

    assert cli.main(["archive", "@active"]) == 0
    assert "archived" in capsys.readouterr().out
    assert cli.main(["reopen", thread_id]) == 0
    assert "reopened" in capsys.readouterr().out


def test_pipeline_thread_dispatch_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user-facing `astrid thread ...` verb is no longer dispatched."""

    monkeypatch.delenv("ASTRID_SESSION_ID", raising=False)
    # Without a session, the gate rejects with the standard hint; with a
    # session bound the dispatcher would fall through to the default brief
    # orchestrator (no `thread` branch exists anymore).
    assert pipeline.main(["thread", "list"]) == 2


def test_backfill_records_existing_runs_without_moving_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    out = repo / "runs" / "existing"
    _write_run(repo, thread_id, out=out)
    original = out / "artifact.txt"
    original.write_text("keep me here", encoding="utf-8")

    assert cli.main(["backfill"]) == 0

    assert original.is_file()
    assert "backfilled run_records=1" in capsys.readouterr().out
    index = json.loads((repo / ".astrid" / "threads.json").read_text(encoding="utf-8"))
    assert thread_id in index["threads"]


def test_thread_help_has_no_deferred_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for forbidden in ("split", "merge", "attach", "detach", " gc"):
        assert forbidden not in output


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    return repo


def _write_run(repo: Path, thread_id: str, *, out: Path | None = None) -> str:
    out = out or repo / "runs" / "one"
    brief = out / "brief.copy.txt"
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text("secret brief body", encoding="utf-8")
    run_id = generate_run_id()
    record = build_run_record(
        run_id=run_id,
        thread_id=thread_id,
        kind="executor",
        executor_id="test.writer",
        out_path=out,
        repo_root=repo,
    )
    record = finalize_run_record(record, repo_root=repo, out_path=out, returncode=0)
    write_run_record(record, out / "run.json")
    store = ThreadIndexStore(repo)

    def mutate(index: dict) -> None:
        if thread_id in index.get("threads", {}):
            index["threads"][thread_id].setdefault("run_ids", []).append(run_id)

    if (repo / ".astrid" / "threads.json").exists():
        store.update(mutate)
    return run_id
