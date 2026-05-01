from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artagents import pipeline  # noqa: E402
from artagents.performers import cli as performers_cli  # noqa: E402


def test_performers_list_includes_upload_youtube(capsys):
    assert performers_cli.main(["list"]) == 0

    output = capsys.readouterr().out
    assert "builtin.render" in output
    assert "external.moirae" in output
    assert "upload.youtube" in output
    assert "Upload to YouTube" in output


def test_performers_list_json_uses_performer_key(capsys):
    assert performers_cli.main(["list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    ids = {performer["id"] for performer in payload["performers"]}
    assert "nodes" not in payload
    assert {"builtin.render", "external.moirae", "upload.youtube"}.issubset(ids)


def test_performers_inspect_upload_youtube_json(capsys):
    assert performers_cli.main(["inspect", "upload.youtube", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "upload.youtube"
    assert payload["name"] == "Upload to YouTube"
    assert payload["metadata"]["backend"] == "banodoco-social"


def test_performers_run_upload_youtube_dry_run(capsys):
    assert (
        performers_cli.main(
            [
                "run",
                "upload.youtube",
                "--dry-run",
                "--video-url",
                "https://cdn.example.com/render.mp4",
                "--title",
                "Rendered talk",
                "--description",
                "A rendered talk video.",
                "--tag",
                "talk",
                "--privacy-status",
                "unlisted",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["would_run"] == "upload.youtube"
    assert payload["inputs"]["video_url"] == "https://cdn.example.com/render.mp4"
    assert payload["inputs"]["tags"] == ["talk"]


def test_performers_run_builtin_dry_run_uses_existing_executable_unit(capsys):
    assert (
        performers_cli.main(
            [
                "run",
                "builtin.render",
                "--out",
                "runs/example",
                "--brief",
                "brief.txt",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "render_remotion.py" in output
    assert '"performer_id":"builtin.render"' in output


def test_pipeline_performers_dispatch_reaches_cli(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 23

    monkeypatch.setattr(performers_cli, "main", fake_main)

    result = pipeline.main(["performers", "list", "--json"])

    assert result == 23
    assert captured["argv"] == ["list", "--json"]


def test_pipeline_upload_youtube_alias(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 19

    monkeypatch.setitem(sys.modules, "publish_youtube", type("Stub", (), {"main": staticmethod(fake_main)}))

    result = pipeline.main(["upload-youtube", "--video-url", "https://cdn.example.com/render.mp4"])

    assert result == 19
    assert captured["argv"] == ["--video-url", "https://cdn.example.com/render.mp4"]
