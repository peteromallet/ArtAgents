"""CLI for publishing rendered videos to YouTube through banodoco-social."""

from __future__ import annotations

import argparse
import json
import sys

from astrid.packs.upload.youtube.src.social_publish import PublishError, publish_youtube_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish-youtube",
        description="Publish a reachable http(s) video URL to YouTube via Zapier.",
    )
    parser.add_argument(
        "--video-url",
        "--video",
        dest="video_url",
        required=True,
        help="Reachable http(s) video URL for the rendered talk video.",
    )
    parser.add_argument("--title", required=True, help="YouTube video title.")
    parser.add_argument(
        "--description",
        required=True,
        help="YouTube video description.",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="YouTube tag. May be repeated.",
    )
    parser.add_argument(
        "--tags",
        action="append",
        default=[],
        help="Comma-separated YouTube tags.",
    )
    parser.add_argument(
        "--privacy-status",
        default="private",
        help="YouTube privacy status: private, unlisted, or public.",
    )
    parser.add_argument("--playlist-id", help="Optional YouTube playlist ID.")
    parser.add_argument(
        "--made-for-kids",
        action="store_true",
        help="Mark the video as made for kids.",
    )
    parser.add_argument(
        "--webhook-url",
        help="Optional Zapier webhook override. Defaults to ZAPIER_YOUTUBE_URL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = publish_youtube_video(
            video_url=args.video_url,
            title=args.title,
            description=args.description,
            tags=[*args.tag, *args.tags],
            privacy_status=args.privacy_status,
            playlist_id=args.playlist_id,
            made_for_kids=args.made_for_kids,
            webhook_url=args.webhook_url,
        )
    except PublishError as exc:
        print(f"publish-youtube: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
