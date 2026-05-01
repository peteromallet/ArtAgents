#!/usr/bin/env python3
"""Query OpenAI vision models against one image or a numbered frame sheet."""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from artagents.generate_image import load_api_key


API_URL = "https://api.openai.com/v1/responses"
MODEL_PRESETS = {
    "fast": "gpt-4o-mini",
    "best": "gpt-5.4",
}
DEFAULT_MODE = "fast"
DEFAULT_MAX_IMAGES = 20


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _parse_timestamp(value: str) -> float:
    raw = value.strip()
    if not raw:
        _die("empty timestamp")
    if ":" not in raw:
        return float(raw)
    parts = [float(part) for part in raw.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    _die(f"invalid timestamp: {value}")
    return 0.0


def _format_time(seconds: float) -> str:
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parse_times(values: list[str]) -> list[float]:
    times: list[float] = []
    for value in values:
        for part in value.split(","):
            if part.strip():
                times.append(_parse_timestamp(part))
    return times


def _extract_video_frames(video: Path, times: list[float], out_dir: Path, force: bool) -> list[tuple[Path, str]]:
    if not video.is_file():
        _die(f"video not found: {video}")
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, str]] = []
    for index, seconds in enumerate(times, start=1):
        path = frames_dir / f"frame_{index:03d}_{int(seconds * 1000):09d}ms.jpg"
        if path.exists() and not force:
            frames.append((path, _format_time(seconds)))
            continue
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(path),
        ]
        subprocess.run(command, check=True)
        frames.append((path, _format_time(seconds)))
    return frames


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    fitted = image.convert("RGB").copy()
    fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (12, 12, 14))
    x = (width - fitted.width) // 2
    y = (height - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def _build_contact_sheet(
    frames: list[tuple[Path, str]],
    *,
    out_path: Path,
    cols: int,
    tile_width: int,
    label_prefix: str,
) -> Path:
    if not frames:
        _die("no images or frames provided")
    cols = max(1, min(cols, len(frames)))
    rows = math.ceil(len(frames) / cols)
    first = Image.open(frames[0][0])
    ratio = first.height / first.width
    tile_height = max(120, int(tile_width * ratio))
    label_height = max(42, int(tile_width * 0.09))
    sheet = Image.new("RGB", (cols * tile_width, rows * (tile_height + label_height)), (10, 10, 12))
    font = _load_font(max(18, int(tile_width * 0.052)))

    for index, (path, label) in enumerate(frames, start=1):
        col = (index - 1) % cols
        row = (index - 1) // cols
        x = col * tile_width
        y = row * (tile_height + label_height)
        with Image.open(path) as image:
            sheet.paste(_fit_image(image, tile_width, tile_height), (x, y))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((x, y, x + tile_width, y + label_height), fill=(0, 0, 0))
        text = f"{label_prefix} {index}"
        if label:
            text = f"{text}  {label}"
        draw.text((x + 14, y + 9), text, fill=(255, 255, 255), font=font)
        draw.rectangle((x, y, x + tile_width - 1, y + tile_height + label_height - 1), outline=(70, 70, 74), width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)
    return out_path


def _parse_aspect(value: str) -> tuple[int, int, str]:
    raw = value.strip().lower()
    if ":" in raw:
        left, right = raw.split(":", 1)
    elif "/" in raw:
        left, right = raw.split("/", 1)
    else:
        _die(f"invalid crop aspect {value!r}; use WIDTH:HEIGHT, for example 9:16")
    width = int(left)
    height = int(right)
    if width <= 0 or height <= 0:
        _die(f"invalid crop aspect {value!r}")
    return width, height, f"{width}:{height}"


def _parse_csv(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def _default_crop_positions(aspect_width: int, aspect_height: int) -> list[str]:
    if aspect_width < aspect_height:
        return ["left", "center", "right"]
    if aspect_width > aspect_height:
        return ["top", "center", "bottom"]
    return ["center"]


def _crop_box(width: int, height: int, aspect_width: int, aspect_height: int, position: str) -> tuple[int, int, int, int]:
    target_ratio = aspect_width / aspect_height
    source_ratio = width / height
    if source_ratio > target_ratio:
        crop_h = height
        crop_w = int(round(height * target_ratio))
        if position in {"left", "top-left", "bottom-left"}:
            x = 0
        elif position in {"right", "top-right", "bottom-right"}:
            x = width - crop_w
        else:
            x = (width - crop_w) // 2
        y = 0
    else:
        crop_w = width
        crop_h = int(round(width / target_ratio))
        if position in {"top", "top-left", "top-right"}:
            y = 0
        elif position in {"bottom", "bottom-left", "bottom-right"}:
            y = height - crop_h
        else:
            y = (height - crop_h) // 2
        x = 0
    return x, y, x + crop_w, y + crop_h


def _build_crop_variants(
    source: tuple[Path, str],
    *,
    aspects: list[str],
    positions: list[str],
    out_dir: Path,
    force: bool,
) -> list[tuple[Path, str]]:
    image_path, source_label = source
    crop_dir = out_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    variants: list[tuple[Path, str]] = []
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
        for aspect_value in aspects:
            aspect_width, aspect_height, aspect_label = _parse_aspect(aspect_value)
            selected_positions = positions or _default_crop_positions(aspect_width, aspect_height)
            for position in selected_positions:
                normalized_position = position.lower()
                box = _crop_box(image.width, image.height, aspect_width, aspect_height, normalized_position)
                out_path = crop_dir / f"{image_path.stem}_{aspect_label.replace(':', 'x')}_{normalized_position}.jpg"
                if force or not out_path.exists():
                    image.crop(box).save(out_path, quality=94)
                label = f"{aspect_label} {normalized_position}"
                if source_label:
                    label = f"{label} {source_label}"
                variants.append((out_path, label))
    return variants


def _encode_image(path: Path) -> tuple[str, str]:
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return media_type, data


def _response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _call_responses_api(
    *,
    api_key: str,
    model: str,
    query: str,
    image_path: Path,
    detail: str,
    max_output_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    media_type, data = _encode_image(image_path)
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": query},
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{data}",
                        "detail": detail,
                    },
                ],
            }
        ],
        "max_output_tokens": max_output_tokens,
    }
    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc


def _collect_inputs(args: argparse.Namespace) -> tuple[list[tuple[Path, str]], Path]:
    out_dir = args.out_dir.expanduser()
    frames: list[tuple[Path, str]] = []
    for path in args.image or []:
        image = path.expanduser()
        if not image.is_file():
            _die(f"image not found: {image}")
        frames.append((image, ""))
    if args.video:
        times = _parse_times(args.at or [])
        if not times:
            _die("provide --at timestamps when using --video. To find candidate timestamps first, run boundary_candidates.py with transcript/scenes/holding-screen refs.")
        frames.extend(_extract_video_frames(args.video.expanduser(), times, out_dir, args.force))
    if len(frames) > args.max_images:
        _die(f"too many images/frames: {len(frames)} > {args.max_images}")
    if not frames:
        _die("provide --image or --video with --at")
    crop_aspects = _parse_csv(args.crop_aspect)
    if crop_aspects:
        if len(frames) != 1:
            _die("--crop-aspect requires exactly one source image/frame")
        frames = _build_crop_variants(
            frames[0],
            aspects=crop_aspects,
            positions=_parse_csv(args.crop_position),
            out_dir=out_dir,
            force=args.force,
        )
        if len(frames) > args.max_images:
            _die(f"too many crop variants: {len(frames)} > {args.max_images}")
        sheet_path = args.contact_sheet or (out_dir / "crop-contact-sheet.jpg")
        return frames, _build_contact_sheet(
            frames,
            out_path=sheet_path,
            cols=args.cols,
            tile_width=args.tile_width,
            label_prefix=args.label_prefix,
        )
    if len(frames) == 1 and not args.contact_sheet:
        return frames, frames[0][0]
    sheet_path = args.contact_sheet or (out_dir / "contact-sheet.jpg")
    return frames, _build_contact_sheet(
        frames,
        out_path=sheet_path,
        cols=args.cols,
        tile_width=args.tile_width,
        label_prefix=args.label_prefix,
    )


def run(args: argparse.Namespace) -> int:
    if args.max_images < 1 or args.max_images > DEFAULT_MAX_IMAGES:
        _die(f"--max-images must be between 1 and {DEFAULT_MAX_IMAGES}")
    frames, image_for_query = _collect_inputs(args)
    primary_model = args.model or MODEL_PRESETS[args.mode]
    models = [primary_model, *args.compare_model]
    payload_preview = {
        "endpoint": API_URL,
        "models": models,
        "query": args.query,
        "image": str(image_for_query),
        "frames": [{"index": index, "path": str(path), "label": label} for index, (path, label) in enumerate(frames, start=1)],
        "detail": args.detail,
    }
    if args.dry_run:
        print(json.dumps(payload_preview, indent=2))
        return 0

    api_key = load_api_key(args.env_file)
    results: list[dict[str, Any]] = []
    for model in models:
        print(f"querying={model} image={image_for_query}", file=sys.stderr)
        started = time.time()
        try:
            response = _call_responses_api(
                api_key=api_key,
                model=model,
                query=args.query,
                image_path=image_for_query,
                detail=args.detail,
                max_output_tokens=args.max_output_tokens,
                timeout=args.timeout,
            )
            result = {
                "model": model,
                "status": "ok",
                "elapsed_sec": round(time.time() - started, 2),
                "answer": _response_text(response),
                "usage": response.get("usage"),
                "response_id": response.get("id"),
            }
        except Exception as exc:
            result = {
                "model": model,
                "status": "error",
                "elapsed_sec": round(time.time() - started, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)

    output = {**payload_preview, "results": results}
    text = json.dumps(output, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote={args.out}", file=sys.stderr)
    return 0 if all(result["status"] == "ok" for result in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ask an OpenAI vision model about one image or a numbered contact sheet.",
        epilog="Tip: if you do not know which video frames to query, run boundary_candidates.py first to package transcript, scenes, shots, quality zones, and holding-screen refs into candidate frame sets.",
    )
    add = parser.add_argument
    add("--query", required=True, help="Question/instruction for the model.")
    add("--image", type=Path, action="append", help="Image path; repeat for multiple images.")
    add("--video", type=Path, help="Video path to sample frames from.")
    add("--at", action="append", help="Frame timestamp(s), comma-separated or repeated. Supports seconds, MM:SS, HH:MM:SS.")
    add("--mode", choices=sorted(MODEL_PRESETS), default=DEFAULT_MODE, help="Model preset: fast is cheapest/default, best uses the strongest detail model.")
    add("--model", help="Explicit model override; bypasses --mode for the primary query.")
    add("--compare-model", action="append", default=[], help="Additional model to query with the same image/contact sheet.")
    add("--detail", choices=["low", "high", "auto"], default="low")
    add("--cols", type=int, default=4)
    add("--tile-width", type=int, default=480)
    add("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    add("--label-prefix", default="Frame")
    add("--contact-sheet", type=Path, help="Optional output path for the generated contact sheet.")
    add("--crop-aspect", action="append", help="Create crop variants from a single source image/frame, e.g. 9:16 or 1:1. Repeat or comma-separate.")
    add("--crop-position", action="append", help="Crop alignment(s), e.g. left,center,right or top,center,bottom. Repeat or comma-separate.")
    add("--out-dir", type=Path, default=Path("runs/visual-understanding"))
    add("--out", type=Path, help="Optional JSON result path.")
    add("--env-file", type=Path)
    add("--max-output-tokens", type=int, default=700)
    add("--timeout", type=int, default=120)
    add("--force", action="store_true")
    add("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
