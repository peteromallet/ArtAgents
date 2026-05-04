from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path

import pytest

from artagents import doctor, pipeline, setup_cli
from artagents.core.project import paths
from artagents.core.project.run import write_run_record
from artagents.core.project.source import add_source
from artagents.core.project.timeline import add_placement
from artagents.core.project.schema import source_ref
from artagents.core.project import cli as project_cli


def _capture(fn, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = fn(argv)
    return int(result), stdout.getvalue(), stderr.getvalue()


def test_projects_cli_create_show_source_place_materialize_and_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    media = tmp_path / "source.mp4"
    media.write_bytes(b"stub")
    out = tmp_path / "materialized"

    result, stdout, stderr = _capture(project_cli.main, ["create", "demo", "--name", "Demo"])
    assert result == 0, stderr
    assert "Project: demo" in stdout

    result, stdout, stderr = _capture(
        project_cli.main,
        ["source", "add", "--project", "demo", "intro", "--file", str(media), "--kind", "video", "--type", "video/mp4", "--duration", "12.5", "--json"],
    )
    assert result == 0, stderr
    assert json.loads(stdout)["source"]["asset"]["file"] == str(media.resolve())
    assert json.loads(stdout)["source"]["kind"] == "video"

    timeline_path = tmp_path / "projects" / "demo" / "timeline.json"
    before = hashlib.sha256(timeline_path.read_bytes()).hexdigest()
    result, stdout, stderr = _capture(
        project_cli.main,
        [
            "timeline",
            "place-source",
            "--project",
            "demo",
            "p1",
            "--source",
            "intro",
            "--track",
            "main",
            "--at",
            "1.25",
            "--from",
            "2",
            "--to",
            "6",
            "--params-json",
            '{"scale":1}',
            "--json",
        ],
    )
    assert result == 0, stderr
    assert json.loads(stdout)["placement"]["params"] == {"scale": 1}

    result, stdout, stderr = _capture(project_cli.main, ["materialize", "--project", "demo", "--out", str(out), "--json"])
    assert result == 0, stderr
    assert (out / "hype.timeline.json").is_file()
    assert (out / "hype.assets.json").is_file()
    assert json.loads((out / "hype.assets.json").read_text(encoding="utf-8"))["assets"]["source:intro"]["type"] == "video/mp4"

    result, stdout, stderr = _capture(project_cli.main, ["timeline", "remove", "--project", "demo", "p1", "--json"])
    assert result == 0, stderr
    assert json.loads(stdout)["timeline"]["placements"] == []
    assert hashlib.sha256(timeline_path.read_bytes()).hexdigest() == before

    result, stdout, stderr = _capture(project_cli.main, ["show", "--project", "demo"])
    assert result == 0, stderr
    assert "demo/" in stdout
    assert "sources/" in stdout


def test_projects_cli_place_run_and_actionable_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    media = tmp_path / "run.mp4"
    media.write_bytes(b"stub")

    assert project_cli.main(["create", "demo"]) == 0
    write_run_record("demo", run_id, tool_id="test.tool", kind="executor", status="success")
    run_root = tmp_path / "projects" / "demo" / "runs" / run_id
    (run_root / "timeline.json").write_text(
        json.dumps({"theme": "banodoco-default", "clips": [{"id": "clip-a", "track": "source", "at": 0, "clipType": "media", "asset": "main"}]}),
        encoding="utf-8",
    )
    (run_root / "assets.json").write_text(json.dumps({"assets": {"main": {"file": str(media.resolve()), "type": "video/mp4"}}}), encoding="utf-8")

    result, stdout, stderr = _capture(project_cli.main, ["timeline", "place-run", "--project", "demo", "p-run", "--run", run_id, "--clip", "clip-a", "--track", "main", "--at", "2", "--json"])
    assert result == 0, stderr
    assert json.loads(stdout)["placement"]["source"] == {"kind": "run", "run_id": run_id, "clip_id": "clip-a"}

    result, stdout, stderr = _capture(project_cli.main, ["timeline", "place-run", "--project", "demo", "p-bad", "--run", run_id, "--clip", "missing", "--track", "main", "--at", "0"])
    assert result == 2
    assert "Available clip ids: clip-a" in stderr
    assert "Next command:" in stderr


def test_setup_doctor_and_top_level_help_report_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))

    result, stdout, stderr = _capture(setup_cli.main, ["--json"])
    assert result == 0, stderr
    assert any(step["name"] == "projects root" and step["status"] == "planned" for step in json.loads(stdout)["steps"])
    assert not projects_root.exists()

    result, stdout, stderr = _capture(doctor.main, ["--json"])
    assert result == 0, stderr
    project_check = next(item for item in json.loads(stdout)["checks"] if item["name"] == "projects root")
    assert project_check["status"] == "warn"
    assert not projects_root.exists()

    result, stdout, stderr = _capture(setup_cli.main, ["--apply", "--json"])
    assert result == 0, stderr
    assert projects_root.is_dir()

    result, stdout, stderr = _capture(pipeline.main, ["--help"])
    assert result == 0, stderr
    assert "python3 -m artagents projects" in stdout


def test_project_cli_missing_resource_hints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    result, stdout, stderr = _capture(project_cli.main, ["show", "--project", "missing"])
    assert result == 2
    assert "projects create missing" in stderr

    assert project_cli.main(["create", "demo"]) == 0
    result, stdout, stderr = _capture(project_cli.main, ["timeline", "place-source", "--project", "demo", "p1", "--source", "missing", "--track", "main", "--at", "0"])
    assert result == 2
    assert "projects source add --project demo missing" in stderr

    with pytest.raises(SystemExit):
        project_cli.main(["source", "add", "--project", "demo", "bad-kind", "--url", "https://example.com/a.mp4", "--kind", "document"])

    result, stdout, stderr = _capture(project_cli.main, ["source", "add", "--project", "demo", "intro", "--url", "https://example.com/a.mp4", "--kind", "video"])
    assert result == 0, stderr
    result, stdout, stderr = _capture(project_cli.main, ["timeline", "place-source", "--project", "demo", "bad-at", "--source", "intro", "--track", "main", "--at", "-1"])
    assert result == 2
    assert "placement.at" in stderr


def test_materialize_cli_uses_project_timeline_not_output_timeline_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    media = tmp_path / "source.mp4"
    media.write_bytes(b"stub")
    project_cli.main(["create", "demo"])
    add_source("demo", "intro", asset={"file": str(media)})
    add_placement("demo", "p1", track="main", at=0, source=source_ref("intro"))

    out = tmp_path / "out"
    result, stdout, stderr = _capture(project_cli.main, ["materialize", "--project", "demo", "--out", str(out)])
    assert result == 0, stderr
    assert (out / "hype.timeline.json").exists()
    assert (tmp_path / "projects" / "demo" / "timeline.json").exists()
