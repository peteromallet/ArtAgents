from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artagents import pipeline
from artagents.packs.upload.youtube.src import social_publish  # noqa: E402
from artagents.packs.upload.youtube import run as publish_youtube  # noqa: E402


def test_publish_youtube_video_forwards_metadata(monkeypatch):
    captured = {}

    class Result:
        def as_dict(self):
            return {"provider_ref": "abc123"}

    def fake_shared_publish(**kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(
        social_publish,
        "_shared_publish_youtube_video",
        fake_shared_publish,
    )

    result = social_publish.publish_youtube_video(
        video_url="https://cdn.example.com/render.mp4",
        title="Rendered talk",
        description="A rendered talk video.",
        tags=["talk", "ai"],
        privacy_status="unlisted",
        playlist_id="playlist-123",
        made_for_kids=True,
        webhook_url="https://hooks.zapier.test/youtube",
    )

    assert result == {"provider_ref": "abc123"}
    assert captured == {
        "video_url": "https://cdn.example.com/render.mp4",
        "title": "Rendered talk",
        "description": "A rendered talk video.",
        "tags": ["talk", "ai"],
        "privacy_status": "unlisted",
        "playlist_id": "playlist-123",
        "made_for_kids": True,
        "webhook_url": "https://hooks.zapier.test/youtube",
    }


def test_publish_youtube_video_propagates_local_path_failure():
    with pytest.raises(social_publish.PublishError, match="upload or stage"):
        social_publish.publish_youtube_video(
            video_url="./render.mp4",
            title="Rendered talk",
            description="A rendered talk video.",
            webhook_url="https://hooks.zapier.test/youtube",
        )


def test_pipeline_publish_youtube_dispatch_reaches_wrapper(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 17

    monkeypatch.setattr(publish_youtube, "main", fake_main)

    result = pipeline.main(
        [
            "publish-youtube",
            "--video-url",
            "https://cdn.example.com/render.mp4",
            "--title",
            "Rendered talk",
            "--description",
            "A rendered talk video.",
        ]
    )

    assert result == 17
    assert captured["argv"] == [
        "--video-url",
        "https://cdn.example.com/render.mp4",
        "--title",
        "Rendered talk",
        "--description",
        "A rendered talk video.",
    ]
