"""Private social publishing wrapper for the upload.youtube executor."""

from __future__ import annotations

import sys
from typing import Any, Iterable

from artagents._paths import WORKSPACE_ROOT


class PublishError(RuntimeError):
    """Raised when a YouTube publish request cannot be submitted."""


def _load_shared_youtube_publisher():
    try:
        from banodoco_social.models import PublishError as SharedPublishError
        from banodoco_social.youtube import publish_youtube_video

        return SharedPublishError, publish_youtube_video
    except ModuleNotFoundError as exc:
        if exc.name != "banodoco_social":
            raise

    shared_repo = WORKSPACE_ROOT / "banodoco-workspace" / "banodoco-social"
    if shared_repo.exists():
        shared_repo_str = str(shared_repo)
        if shared_repo_str not in sys.path:
            sys.path.insert(0, shared_repo_str)
        try:
            from banodoco_social.models import PublishError as SharedPublishError
            from banodoco_social.youtube import publish_youtube_video

            return SharedPublishError, publish_youtube_video
        except ModuleNotFoundError as exc:
            if exc.name != "banodoco_social":
                raise

    raise ImportError(
        "banodoco_social is not importable. Install banodoco-workspace/"
        "banodoco-social or run from the local workspace that contains it."
    )


def _shared_publish_youtube_video(**kwargs):
    _, publish_youtube_video = _load_shared_youtube_publisher()
    return publish_youtube_video(**kwargs)


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
    if not video_url.startswith(("http://", "https://")):
        raise PublishError("video_url must be a reachable http(s) URL; upload or stage local files before publishing")
    try:
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
    except Exception as exc:
        if isinstance(exc, PublishError):
            raise
        raise PublishError(str(exc)) from exc
    if hasattr(result, "as_dict"):
        return result.as_dict()
    return result


__all__ = ["PublishError", "publish_youtube_video"]
