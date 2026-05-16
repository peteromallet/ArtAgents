from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from astrid.packs.builtin.executors.understand import run as understand
from astrid.packs.builtin.executors.video_understand.run import main


def _write_test_video(path: Path, *, duration: float = 1.2) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for video understanding tests")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x90:rate=10:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def test_video_understand_extracts_window_dry_run(capsys, tmp_path):
    video = tmp_path / "source.mp4"
    _write_test_video(video)

    code = main(
        [
            "--video",
            str(video),
            "--at",
            "0.6",
            "--window-sec",
            "0.6",
            "--out-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "gemini"
    assert payload["models"] == ["gemini-2.5-flash"]
    assert payload["source_kind"] == "video"
    assert len(payload["windows"]) == 1
    assert Path(payload["windows"][0]["path"]).is_file()


def test_video_understand_best_mode_dry_run(capsys, tmp_path):
    video = tmp_path / "source.mp4"
    _write_test_video(video)

    code = main(["--video", str(video), "--mode", "best", "--out-dir", str(tmp_path / "out"), "--dry-run"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["models"] == ["gemini-2.5-pro"]


def test_understand_dispatches_video(monkeypatch):
    captured = {}

    def fake_video_main(argv):
        captured["argv"] = argv
        return 17

    monkeypatch.setitem(understand.ALIASES, "video", fake_video_main)

    assert understand.main(["--mode", "video", "--video", "source.mp4", "--dry-run"]) == 17
    assert captured["argv"] == ["--video", "source.mp4", "--dry-run"]
