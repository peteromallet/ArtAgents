"""Shared social publishing wrapper for ArtAgents."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Iterable


def _load_shared_youtube_publisher():
    try:
        from banodoco_social.models import PublishError
        from banodoco_social.youtube import publish_youtube_video

        return PublishError, publish_youtube_video
    except ModuleNotFoundError as exc:
        if exc.name != "banodoco_social":
            raise

    shared_repo = (
        Path(__file__).resolve().parents[3]
        / "banodoco-workspace"
        / "banodoco-social"
    )
    if shared_repo.exists():
        shared_repo_str = str(shared_repo)
        if shared_repo_str not in sys.path:
            sys.path.insert(0, shared_repo_str)
        try:
            from banodoco_social.models import PublishError
            from banodoco_social.youtube import publish_youtube_video

            return PublishError, publish_youtube_video
        except ModuleNotFoundError as exc:
            if exc.name != "banodoco_social":
                raise

    raise ImportError(
        "banodoco_social is not importable. Install banodoco-workspace/"
        "banodoco-social or run from the local workspace that contains it."
    )


PublishError, _shared_publish_youtube_video = _load_shared_youtube_publisher()


def publish_youtube_video(
    *,
    video_url: str,
    title: str,
    description: str,
    tags: Iterable[str] | str | None = None,
    privacy_status: str = "private",
    playlist_id: str | None = None,
    made_for_kids: bool = False,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    result = _shared_publish_youtube_video(
        video_url=video_url,
        title=title,
        description=description,
        tags=tags,
        privacy_status=privacy_status,
        playlist_id=playlist_id,
        made_for_kids=made_for_kids,
        webhook_url=webhook_url,
    )
    if hasattr(result, "as_dict"):
        return result.as_dict()
    return result


__all__ = ["PublishError", "publish_youtube_video"]
