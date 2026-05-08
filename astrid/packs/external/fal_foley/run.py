#!/usr/bin/env python3
"""Score one video clip with Foley audio via fal.ai hunyuan-video-foley."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from astrid.packs.builtin.logo_ideas.run import (
    FAL_QUEUE_URL,
    _http_get_bytes,
    _http_post_json,
    poll_fal_result,
)
from astrid.packs.builtin.vary_grid.run import _load_env_var


FAL_MODEL_ID = "fal-ai/hunyuan-video-foley"


def _data_uri_for_video(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    mime = {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "m4v": "video/x-m4v",
        "gif": "image/gif",
    }.get(suffix, "video/mp4")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _submit(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    url = f"{FAL_QUEUE_URL}/{FAL_MODEL_ID}"
    headers = {"authorization": f"Key {api_key}"}
    return _http_post_json(url, headers, payload, timeout=180)


def _save_audio(result: dict[str, Any], dest: Path) -> dict[str, Any]:
    # Hunyuan-Foley returns { "audio": { "url": ..., "content_type": ..., "file_name": ... } }
    # or possibly a "video" key with embedded audio. Probe both.
    audio = result.get("audio") or result.get("output_audio")
    if not audio and isinstance(result.get("video"), dict):
        audio = result["video"]
    if not audio or not audio.get("url"):
        raise SystemExit(f"fal foley result had no audio url: {str(result)[:400]}")
    url = audio["url"]
    raw = _http_get_bytes(url, timeout=300)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return {
        "path": str(dest),
        "source_url": url,
        "content_type": audio.get("content_type"),
        "file_name": audio.get("file_name"),
        "bytes": len(raw),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Score one video clip with fal hunyuan-video-foley.")
    p.add_argument("--clip", type=Path, required=True, help="Input video clip.")
    p.add_argument("--prompt", required=True, help="Text description of the Foley to generate.")
    p.add_argument("--out", type=Path, required=True, help="Output audio file path.")
    p.add_argument("--env-file", type=Path, help="Env file holding FAL_KEY.")
    p.add_argument("--max-wait-sec", type=int, default=600, help="Max seconds to wait for the fal job.")
    p.add_argument("--dry-run", action="store_true", help="Print planned request, skip the API call.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    clip = args.clip.expanduser().resolve()
    if not clip.is_file():
        print(f"Error: clip not found: {clip}", file=sys.stderr)
        return 1
    out = args.out.expanduser().resolve()

    payload_preview = {
        "model_id": FAL_MODEL_ID,
        "clip": str(clip),
        "prompt": args.prompt,
        "out": str(out),
    }

    if args.dry_run:
        print(json.dumps(payload_preview, indent=2))
        return 0

    api_key = _load_env_var("FAL_KEY", args.env_file)
    payload = {
        "video_url": _data_uri_for_video(clip),
        "text_prompt": args.prompt,
    }
    submission = _submit(payload, api_key)
    result = poll_fal_result(submission, api_key, max_wait_sec=args.max_wait_sec)
    saved = _save_audio(result, out)

    sidecar = out.with_suffix(out.suffix + ".fal.json")
    sidecar.write_text(json.dumps({
        **payload_preview,
        "request_id": submission.get("request_id"),
        "saved": saved,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote_audio={saved['path']}")
    print(f"wrote_sidecar={sidecar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
