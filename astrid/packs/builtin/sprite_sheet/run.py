#!/usr/bin/env python3
"""Generate a GPT Image sprite sheet, slice frames, and assemble previews."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid
import zlib

from astrid.packs.builtin.generate_image.run import (
    API_URL,
    DEFAULT_MODEL,
    GPT_IMAGE_2_MAX_EDGE,
    GPT_IMAGE_2_MAX_PIXELS,
    GPT_IMAGE_2_MAX_RATIO,
    GPT_IMAGE_2_MIN_PIXELS,
    _call_image_api,
    _candidate_env_files,
    _die,
    _read_env_value,
    _validate_payload,
    load_api_key,
)

EDIT_API_URL = "https://api.openai.com/v1/images/edits"
DEFAULT_KEY_COLOR = "#ff00ff"
DEFAULT_FAL_UPSCALER = "fal-ai/clarity-upscaler"
FAL_KEY_NAMES = ("FAL_KEY", "FAL_API_KEY")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _write_rgb_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start : start + stride])
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _png_chunk(b"IEND", b""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_rgba_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start : start + stride])
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _png_chunk(b"IEND", b""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _read_rgba_png(path: Path) -> tuple[int, int, bytearray]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        _die(f"Expected PNG image: {path}")
    pos = 8
    width = height = bit_depth = color_type = None
    idat: list[bytes] = []
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
    if width is None or height is None or bit_depth != 8 or color_type != 6:
        _die(f"Expected 8-bit RGBA PNG: {path}")
    raw = zlib.decompress(b"".join(idat))
    bpp = 4
    stride = width * bpp
    prev = bytearray(stride)
    pixels = bytearray()
    i = 0
    for _ in range(height):
        filter_type = raw[i]
        i += 1
        scan = bytearray(raw[i : i + stride])
        i += stride
        out = bytearray(stride)
        for x in range(stride):
            left = out[x - bpp] if x >= bpp else 0
            up = prev[x]
            upper_left = prev[x - bpp] if x >= bpp else 0
            if filter_type == 0:
                value = scan[x]
            elif filter_type == 1:
                value = (scan[x] + left) & 255
            elif filter_type == 2:
                value = (scan[x] + up) & 255
            elif filter_type == 3:
                value = (scan[x] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                predictor = left + up - upper_left
                pa = abs(predictor - left)
                pb = abs(predictor - up)
                pc = abs(predictor - upper_left)
                predicted = left if pa <= pb and pa <= pc else (up if pb <= pc else upper_left)
                value = (scan[x] + predicted) & 255
            else:
                _die(f"Unsupported PNG filter type {filter_type} in {path}")
            out[x] = value
        pixels.extend(out)
        prev = out
    return width, height, pixels


def scrub_fully_transparent_rgb(path: Path) -> None:
    width, height, pixels = _read_rgba_png(path)
    for offset in range(0, len(pixels), 4):
        if pixels[offset + 3] == 0:
            pixels[offset : offset + 3] = b"\x00\x00\x00"
    _write_rgba_png(path, width, height, pixels)


def _alpha_bbox(pixels: bytearray, width: int, height: int, threshold: int = 8) -> tuple[int, int, int, int] | None:
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        row = y * width * 4
        for x in range(width):
            if pixels[row + x * 4 + 3] > threshold:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return None
    return min_x, min_y, max_x, max_y


def analyze_frames(frames: list[str], *, edge_margin: int) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for frame in frames:
        path = Path(frame)
        width, height, pixels = _read_rgba_png(path)
        bbox = _alpha_bbox(pixels, width, height)
        if bbox is None:
            report.append({"path": str(path), "empty": True, "touches_edge": False})
            continue
        min_x, min_y, max_x, max_y = bbox
        touches_edge = min_x <= edge_margin or min_y <= edge_margin or max_x >= width - 1 - edge_margin or max_y >= height - 1 - edge_margin
        report.append(
            {
                "path": str(path),
                "empty": False,
                "bbox": [min_x, min_y, max_x, max_y],
                "width": max_x - min_x + 1,
                "height": max_y - min_y + 1,
                "center": [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0],
                "touches_edge": touches_edge,
            }
        )
    return report


def normalize_frame_frame(path: Path, out_path: Path, *, margin: int, force: bool) -> dict[str, Any]:
    width, height, pixels = _read_rgba_png(path)
    bbox = _alpha_bbox(pixels, width, height)
    if bbox is None:
        if path != out_path:
            out_path.write_bytes(path.read_bytes())
        return {"path": str(out_path), "empty": True, "scaled": False}
    min_x, min_y, max_x, max_y = bbox
    crop_w = max_x - min_x + 1
    crop_h = max_y - min_y + 1
    target_w = max(1, width - margin * 2)
    target_h = max(1, height - margin * 2)
    scale = min(1.0, target_w / crop_w, target_h / crop_h)
    crop_expr = f"crop={crop_w}:{crop_h}:{min_x}:{min_y}"
    if scale < 0.999:
        scaled_w = max(1, int(round(crop_w * scale)))
        scaled_h = max(1, int(round(crop_h * scale)))
        filter_chain = f"{crop_expr},scale={scaled_w}:{scaled_h}:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
    else:
        filter_chain = f"{crop_expr},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
    if out_path.exists() and not force:
        _die(f"Output exists: {out_path} (use --force to overwrite)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(path),
            "-vf",
            filter_chain,
            "-frames:v",
            "1",
            str(out_path),
        ]
    )
    scrub_fully_transparent_rgb(out_path)
    return {"path": str(out_path), "empty": False, "scaled": scale < 0.999, "scale": scale, "source_bbox": [min_x, min_y, max_x, max_y]}


def normalize_frames(frames: list[str], out_dir: Path, *, margin: int, force: bool) -> tuple[list[str], list[dict[str, Any]]]:
    normalized: list[str] = []
    report: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        out = out_dir / f"frame_{index:03d}.png"
        item = normalize_frame_frame(Path(frame), out, margin=margin, force=force)
        normalized.append(str(out))
        report.append(item)
    return normalized, report


def upscale_frames(frames: list[str], out_dir: Path, *, factor: float, filter_name: str, force: bool) -> list[str]:
    if factor <= 0:
        _die("--upscale-factor must be > 0")
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, frame in enumerate(frames, start=1):
        out = out_dir / f"frame_{index:03d}.png"
        if out.exists() and not force:
            _die(f"Output exists: {out} (use --force to overwrite)")
        if abs(factor - 1.0) < 0.0001:
            out.write_bytes(Path(frame).read_bytes())
        else:
            _run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y" if force else "-n",
                    "-i",
                    str(frame),
                    "-vf",
                    f"scale=round(iw*{factor})*1:round(ih*{factor})*1:flags={filter_name},format=rgba",
                    "-frames:v",
                    "1",
                    str(out),
                ]
            )
            scrub_fully_transparent_rgb(out)
        outputs.append(str(out))
    return outputs


def _workspace_env_files(env_file: Path | None) -> list[Path]:
    candidates = _candidate_env_files(env_file)
    repo_root = Path(__file__).resolve().parents[3]
    workspace = repo_root.parent
    candidates.extend(
        [
            Path.cwd() / ".env",
            workspace / ".env",
            workspace / "reigh-app" / ".env",
            workspace / "reigh-worker" / ".env",
            workspace / "reigh-worker-orchestrator" / ".env",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def load_fal_key(env_file: Path | None = None) -> str:
    for key_name in FAL_KEY_NAMES:
        if key := os.environ.get(key_name, "").strip():
            return key
    tried: list[str] = [", ".join(FAL_KEY_NAMES) + " environment variables"]
    for candidate in _workspace_env_files(env_file):
        tried.append(str(candidate))
        for key_name in FAL_KEY_NAMES:
            if key := _read_env_value(candidate, key_name):
                return key
    raise SystemExit(f"FAL_KEY or FAL_API_KEY not found. Tried: {', '.join(tried)}")


def _download_url(url: str, output_path: Path, *, force: bool, timeout: int) -> None:
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Astrid/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            output_path.write_bytes(response.read())
    except (HTTPError, URLError, TimeoutError) as exc:
        _die(f"Failed to download FAL output: {exc}")


def _fal_image_url(result: dict[str, Any]) -> str:
    image = result.get("image")
    if isinstance(image, dict) and isinstance(image.get("url"), str):
        return image["url"]
    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"]
        if isinstance(first, str):
            return first
    _die("FAL upscaler result did not include an image URL")
    return ""


def _ai_upscale_prompt(args: argparse.Namespace) -> str:
    if args.ai_upscale_prompt:
        return args.ai_upscale_prompt
    return (
        f"High-quality AI upscaling for a transparent game sprite frame. Preserve the exact pose, silhouette, animation timing, "
        f"character identity, and clean 2D sprite style. Subject: {args.subject}. Animation: {args.animation}."
    )


def _merge_upscaled_rgb_with_source_alpha(source_frame: Path, upscaled_rgb: Path, output_path: Path, *, factor: float, force: bool) -> None:
    width, height, _ = _read_rgba_png(source_frame)
    target_width = max(1, int(round(width * factor)))
    target_height = max(1, int(round(height * factor)))
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(upscaled_rgb),
            "-i",
            str(source_frame),
            "-filter_complex",
            (
                f"[0:v]scale={target_width}:{target_height}:flags=lanczos,format=rgb24[rgb];"
                f"[1:v]alphaextract,scale={target_width}:{target_height}:flags=lanczos[alpha];"
                "[rgb][alpha]alphamerge,format=rgba[out]"
            ),
            "-map",
            "[out]",
            "-frames:v",
            "1",
            str(output_path),
        ]
    )
    scrub_fully_transparent_rgb(output_path)


def _scale_upscaled_image(source_frame: Path, upscaled_image: Path, output_path: Path, *, factor: float, force: bool) -> None:
    width, height = _png_dimensions(source_frame)
    target_width = max(1, int(round(width * factor)))
    target_height = max(1, int(round(height * factor)))
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(upscaled_image),
            "-vf",
            f"scale={target_width}:{target_height}:flags=lanczos,format=rgba",
            "-frames:v",
            "1",
            str(output_path),
        ]
    )


def ai_upscale_frames_with_fal(
    frames: list[str],
    out_dir: Path,
    *,
    args: argparse.Namespace,
    force: bool,
) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        import fal_client
    except ImportError:
        _die("fal-client is required for --ai-upscale-provider fal. Install requirements or run: pip install fal-client")

    fal_key = load_fal_key(args.fal_env_file or args.env_file)
    client = fal_client.SyncClient(key=fal_key, default_timeout=float(args.fal_timeout))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "fal_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prompt = _ai_upscale_prompt(args)
    outputs: list[str] = []
    reports: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        source_frame = Path(frame)
        raw_output = raw_dir / f"frame_{index:03d}.png"
        final_output = out_dir / f"frame_{index:03d}.png"
        print(f"FAL upscaling frame {index}/{len(frames)} with {args.ai_upscale_model}", file=sys.stderr)
        image_url = client.upload_file(source_frame)
        payload = {
            "image_url": image_url,
            "prompt": prompt,
            "upscale_factor": args.ai_upscale_factor,
            "negative_prompt": args.ai_upscale_negative_prompt,
            "creativity": args.ai_upscale_creativity,
            "resemblance": args.ai_upscale_resemblance,
            "guidance_scale": args.ai_upscale_guidance_scale,
            "num_inference_steps": args.ai_upscale_steps,
            "enable_safety_checker": True,
        }
        result = client.subscribe(
            args.ai_upscale_model,
            arguments=payload,
            with_logs=args.fal_logs,
            client_timeout=float(args.fal_timeout),
        )
        output_url = _fal_image_url(result)
        _download_url(output_url, raw_output, force=force, timeout=args.fal_timeout)
        if args.transparent:
            _merge_upscaled_rgb_with_source_alpha(
                source_frame,
                raw_output,
                final_output,
                factor=args.ai_upscale_factor,
                force=force,
            )
        else:
            _scale_upscaled_image(source_frame, raw_output, final_output, factor=args.ai_upscale_factor, force=force)
        outputs.append(str(final_output))
        reports.append(
            {
                "frame": index,
                "source": str(source_frame),
                "raw_output": str(raw_output),
                "output": str(final_output),
                "model": args.ai_upscale_model,
                "upscale_factor": args.ai_upscale_factor,
                "seed": result.get("seed") if isinstance(result, dict) else None,
            }
        )
    return outputs, reports


def _parse_hex_color(raw: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", raw.strip())
    if not match:
        _die("color must be a hex RGB value like #ff00ff")
    value = match.group(1)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex_color_no_hash(raw: str) -> str:
    _parse_hex_color(raw)
    return raw.strip().lstrip("#").lower()


def _key_color_name(raw: str) -> str:
    normalized = "#" + _hex_color_no_hash(raw)
    if normalized == "#ff00ff":
        return "pure magenta #ff00ff"
    if normalized == "#00ff00":
        return "pure green #00ff00"
    if normalized == "#0000ff":
        return "pure blue #0000ff"
    return normalized


def _set_pixel(pixels: bytearray, width: int, height: int, x: int, y: int, rgb: tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    offset = (y * width + x) * 3
    pixels[offset : offset + 3] = bytes(rgb)


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    rgb: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    if x0 == x1:
        for x in range(x0 - thickness // 2, x0 + (thickness + 1) // 2):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                _set_pixel(pixels, width, height, x, y, rgb)
        return
    if y0 == y1:
        for y in range(y0 - thickness // 2, y0 + (thickness + 1) // 2):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                _set_pixel(pixels, width, height, x, y, rgb)
        return
    steps = max(abs(x1 - x0), abs(y1 - y0))
    for step in range(steps + 1):
        t = step / max(1, steps)
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t)
        for yy in range(y - thickness // 2, y + (thickness + 1) // 2):
            for xx in range(x - thickness // 2, x + (thickness + 1) // 2):
                _set_pixel(pixels, width, height, xx, yy, rgb)


def _layout_is_valid(cols: int, rows: int, frame_width: int, frame_height: int) -> bool:
    width = cols * frame_width
    height = rows * frame_height
    if width % 16 or height % 16:
        return False
    if max(width, height) > GPT_IMAGE_2_MAX_EDGE:
        return False
    if max(width, height) / min(width, height) > GPT_IMAGE_2_MAX_RATIO:
        return False
    pixels = width * height
    return GPT_IMAGE_2_MIN_PIXELS <= pixels <= GPT_IMAGE_2_MAX_PIXELS


def choose_layout(frame_count: int, *, frame_width: int, frame_height: int, fixed_cols: int | None = None, fixed_rows: int | None = None) -> dict[str, int]:
    if frame_count < 1:
        _die("--frames must be >= 1")
    if fixed_cols is not None and fixed_cols < 1:
        _die("--cols must be >= 1")
    if fixed_rows is not None and fixed_rows < 1:
        _die("--rows must be >= 1")

    candidates: list[tuple[float, int, int]] = []
    max_cols = GPT_IMAGE_2_MAX_EDGE // frame_width
    max_rows = GPT_IMAGE_2_MAX_EDGE // frame_height

    if fixed_cols is not None and fixed_rows is not None:
        if fixed_cols * fixed_rows < frame_count:
            _die(f"Grid {fixed_cols}x{fixed_rows} only has {fixed_cols * fixed_rows} cells for {frame_count} frames")
        if not _layout_is_valid(fixed_cols, fixed_rows, frame_width, frame_height):
            _die(f"Grid {fixed_cols}x{fixed_rows} at {frame_width}x{frame_height} per frame violates gpt-image-2 size limits")
        return {"cols": fixed_cols, "rows": fixed_rows, "frame_count": frame_count, "capacity": fixed_cols * fixed_rows}

    if fixed_cols is not None:
        rows = (frame_count + fixed_cols - 1) // fixed_cols
        if not _layout_is_valid(fixed_cols, rows, frame_width, frame_height):
            _die(f"Auto rows for {fixed_cols} columns violates gpt-image-2 size limits")
        return {"cols": fixed_cols, "rows": rows, "frame_count": frame_count, "capacity": fixed_cols * rows}

    if fixed_rows is not None:
        cols = (frame_count + fixed_rows - 1) // fixed_rows
        if not _layout_is_valid(cols, fixed_rows, frame_width, frame_height):
            _die(f"Auto columns for {fixed_rows} rows violates gpt-image-2 size limits")
        return {"cols": cols, "rows": fixed_rows, "frame_count": frame_count, "capacity": cols * fixed_rows}

    for rows in range(1, max_rows + 1):
        cols = (frame_count + rows - 1) // rows
        if cols < 1 or cols > max_cols:
            continue
        if not _layout_is_valid(cols, rows, frame_width, frame_height):
            continue
        capacity = cols * rows
        empty = capacity - frame_count
        sheet_width = cols * frame_width
        sheet_height = rows * frame_height
        aspect_penalty = abs((sheet_width / sheet_height) - 1.0)
        area_penalty = (sheet_width * sheet_height) / GPT_IMAGE_2_MAX_PIXELS
        row_penalty = rows * 0.001
        score = empty * 100.0 + aspect_penalty * 10.0 + area_penalty + row_penalty
        candidates.append((score, cols, rows))

    if not candidates:
        _die(
            f"Could not fit {frame_count} frames at {frame_width}x{frame_height}. "
            "Lower the frame size, lower frame count, or set explicit rows/cols."
        )

    _, cols, rows = min(candidates)
    return {"cols": cols, "rows": rows, "frame_count": frame_count, "capacity": cols * rows}


def write_layout_guide(
    path: Path,
    *,
    cols: int,
    rows: int,
    frame_width: int,
    frame_height: int,
    frame_count: int | None = None,
    safe_margin: int | None = None,
    background_color: str = "#ffffff",
) -> dict[str, Any]:
    width = cols * frame_width
    height = rows * frame_height
    bg = _parse_hex_color(background_color)
    pixels = bytearray(list(bg) * width * height)

    grid = (20, 20, 20)
    border = (0, 0, 0)
    safe = (255, 255, 255)
    for col in range(cols + 1):
        x = min(width - 1, col * frame_width)
        _draw_line(pixels, width, height, x, 0, x, height - 1, border if col in {0, cols} else grid, 5 if col in {0, cols} else 3)
    for row in range(rows + 1):
        y = min(height - 1, row * frame_height)
        _draw_line(pixels, width, height, 0, y, width - 1, y, border if row in {0, rows} else grid, 5 if row in {0, rows} else 3)

    inset = safe_margin if safe_margin is not None else max(24, min(frame_width, frame_height) // 8)
    for row in range(rows):
        for col in range(cols):
            x0 = col * frame_width + inset
            y0 = row * frame_height + inset
            x1 = (col + 1) * frame_width - inset
            y1 = (row + 1) * frame_height - inset
            _draw_line(pixels, width, height, x0, y0, x1, y0, safe)
            _draw_line(pixels, width, height, x0, y1, x1, y1, safe)
            _draw_line(pixels, width, height, x0, y0, x0, y1, safe)
            _draw_line(pixels, width, height, x1, y0, x1, y1, safe)
            center_x = col * frame_width + frame_width // 2
            center_y = row * frame_height + frame_height // 2
            cross = max(8, min(frame_width, frame_height) // 24)
            _draw_line(pixels, width, height, center_x - cross, center_y, center_x + cross, center_y, safe, 2)
            _draw_line(pixels, width, height, center_x, center_y - cross, center_x, center_y + cross, safe, 2)

    _write_rgb_png(path, width, height, pixels)
    capacity = cols * rows
    actual_frame_count = frame_count if frame_count is not None else capacity
    if actual_frame_count > capacity:
        _die(f"frame_count {actual_frame_count} exceeds grid capacity {capacity}")
    frames = []
    for index in range(actual_frame_count):
        col = index % cols
        row = index // cols
        frames.append(
            {
                "index": index + 1,
                "x": col * frame_width,
                "y": row * frame_height,
                "width": frame_width,
                "height": frame_height,
            }
        )
    return {
        "cols": cols,
        "rows": rows,
        "capacity": capacity,
        "frame_count": actual_frame_count,
        "sheet_width": width,
        "sheet_height": height,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "safe_margin": inset,
        "frames": frames,
    }


def _sprite_prompt(args: argparse.Namespace, layout: dict[str, Any]) -> str:
    frame_count = int(layout["frame_count"])
    capacity = int(layout["capacity"])
    extra = ""
    if capacity > frame_count:
        extra = f" Use only the first {frame_count} cells for animation frames; leave the final {capacity - frame_count} unused cell(s) blank white."
    safe_margin = int(layout.get("safe_margin") or 0)
    style = args.style.strip() if args.style else "clean high-quality 2D game animation, crisp silhouette, consistent character design"
    if args.transparent:
        background = (
            f"perfectly flat solid {_key_color_name(args.key_color)} chroma-key background. "
            "The background must be one uniform exact color with no shadows, gradients, texture, floor, glow, or lighting variation. "
            f"Do not use {_key_color_name(args.key_color)} anywhere in the character, props, outline, highlights, shadows, or effects."
        )
    else:
        background = args.background.strip() if args.background else "plain white background"
    return "\n".join(
        [
            "Create one complete animation sprite sheet.",
            f"Animation: {args.animation.strip()}",
            f"Subject: {args.subject.strip()}",
            f"Style: {style}",
            f"Canvas: {layout['sheet_width']}x{layout['sheet_height']} pixels.",
            f"Grid: {layout['cols']} columns by {layout['rows']} rows, {capacity} cells total.",
            f"Animation frames: exactly {frame_count} sequential frames.{extra}",
            f"Each frame cell is exactly {layout['frame_width']}x{layout['frame_height']} pixels.",
            f"Safe area: keep the entire character, all limbs, cape, backpack, motion arcs, and effects at least {safe_margin} pixels inside each cell boundary.",
            "Never let any body part cross, touch, or continue through a cell boundary. No partial heads, feet, hands, capes, or limbs at any cell edge.",
            "Frame order is left-to-right across each row, then top-to-bottom.",
            "Each cell must contain one sequential pose from the animation.",
            "Keep the subject centered inside each cell with consistent scale, camera, lighting, and proportions.",
            f"Background for every cell: {background}.",
            "Do not include text, labels, numbers, watermarks, UI, borders, grid lines, gutters, or frame separators in the final artwork.",
            "Do not merge frames together. Do not create a collage. Do not vary art style between frames.",
            "The provided guide image is only a layout template showing cell placement and safe areas; remove all guide lines from the final sprite sheet.",
        ]
    )


def _multipart_field(name: str, value: str, boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def _multipart_file(name: str, path: Path, boundary: str, content_type: str = "image/png") -> bytes:
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    return header + path.read_bytes() + b"\r\n"


def _call_image_edit_api(payload: dict[str, Any], image_path: Path, api_key: str, timeout: int) -> dict[str, Any]:
    boundary = f"astrid-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in payload.items():
        if value is not None:
            parts.append(_multipart_field(key, str(value), boundary))
    parts.append(_multipart_file("image", image_path, boundary))
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    request = Request(
        EDIT_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _die(f"OpenAI API error {exc.code}: {detail}")
    except URLError as exc:
        _die(f"Network error: {exc}")
    return {}


def _write_first_image(response: dict[str, Any], out_path: Path, force: bool) -> None:
    data = response.get("data") or []
    if not data or not data[0].get("b64_json"):
        _die("OpenAI response did not include b64_json image data")
    if out_path.exists() and not force:
        _die(f"Output exists: {out_path} (use --force to overwrite)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(data[0]["b64_json"]))
    print(f"Wrote {out_path}")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        _die(f"Expected PNG image: {path}")
    return struct.unpack(">II", data[16:24])


def validate_sheet_dimensions(sheet_path: Path, *, expected_width: int, expected_height: int) -> None:
    width, height = _png_dimensions(sheet_path)
    if width != expected_width or height != expected_height:
        _die(f"Sprite sheet is {width}x{height}, expected {expected_width}x{expected_height}")


def remove_chroma_key(
    input_path: Path,
    output_path: Path,
    *,
    key_color: str,
    similarity: float,
    blend: float,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    color = "0x" + _hex_color_no_hash(key_color)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(input_path),
            "-vf",
            f"format=rgba,colorkey={color}:{similarity}:{blend}",
            "-frames:v",
            "1",
            str(output_path),
        ]
    )


def slice_frames(sheet_path: Path, frames_dir: Path, *, cols: int, rows: int, frame_width: int, frame_height: int, frame_count: int, trim: int, force: bool) -> list[str]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    output_width = frame_width - trim * 2
    output_height = frame_height - trim * 2
    if output_width < 16 or output_height < 16:
        _die("--slice-trim is too large for the frame size")
    for index in range(frame_count):
        col = index % cols
        row = index // cols
        x = col * frame_width + trim
        y = row * frame_height + trim
        out = frames_dir / f"frame_{index + 1:03d}.png"
        if out.exists() and not force:
            _die(f"Output exists: {out} (use --force to overwrite)")
        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y" if force else "-n",
                "-i",
                str(sheet_path),
                "-vf",
                f"crop={output_width}:{output_height}:{x}:{y}",
                "-frames:v",
                "1",
                str(out),
            ]
        )
        outputs.append(str(out))
    return outputs


def assemble_review_video(frames_dir: Path, video_path: Path, *, fps: int, background: str, force: bool) -> None:
    if video_path.exists() and not force:
        _die(f"Output exists: {video_path} (use --force to overwrite)")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    frame_width, frame_height = _png_dimensions(frames_dir / "frame_001.png")
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%03d.png"),
            "-f",
            "lavfi",
            "-i",
            f"color=c={background}:s={frame_width}x{frame_height}:r={fps}",
            "-filter_complex",
            "[1:v][0:v]overlay=shortest=1:format=auto,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "15",
            "-preset",
            "slow",
            "-movflags",
            "+faststart",
            str(video_path),
        ]
    )


def assemble_prores_video(frames_dir: Path, video_path: Path, *, fps: int, force: bool) -> None:
    if video_path.exists() and not force:
        _die(f"Output exists: {video_path} (use --force to overwrite)")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%03d.png"),
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            str(video_path),
        ]
    )


def _scale_filter_for_web(max_dim: int | None) -> str:
    if max_dim is None or max_dim <= 0:
        return "format=rgba"
    return (
        "scale='if(gt(iw,ih),min(iw,"
        f"{max_dim}),-2)':'if(gt(ih,iw),min(ih,{max_dim}),-2)':force_original_aspect_ratio=decrease,"
        "format=rgba"
    )


def convert_image_to_webp(input_path: Path, output_path: Path, *, quality: int, lossless: bool, max_dim: int | None, force: bool) -> None:
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(input_path),
            "-vf",
            _scale_filter_for_web(max_dim),
            "-frames:v",
            "1",
            "-c:v",
            "libwebp",
            "-lossless",
            "1" if lossless else "0",
            "-quality",
            str(quality),
            str(output_path),
        ]
    )


def convert_frames_to_webp(frames: list[str], out_dir: Path, *, quality: int, lossless: bool, max_dim: int | None, force: bool) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, frame in enumerate(frames, start=1):
        out = out_dir / f"frame_{index:03d}.webp"
        convert_image_to_webp(Path(frame), out, quality=quality, lossless=lossless, max_dim=max_dim, force=force)
        outputs.append(str(out))
    return outputs


def assemble_web_mp4(frames_dir: Path, video_path: Path, *, fps: int, background: str, max_dim: int | None, crf: int, force: bool) -> None:
    if video_path.exists() and not force:
        _die(f"Output exists: {video_path} (use --force to overwrite)")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    frame_width, frame_height = _png_dimensions(frames_dir / "frame_001.png")
    scale_filter = ""
    if max_dim is not None and max_dim > 0:
        scale_filter = f",scale='if(gt(iw,ih),min(iw,{max_dim}),-2)':'if(gt(ih,iw),min(ih,{max_dim}),-2)':force_original_aspect_ratio=decrease"
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%03d.png"),
            "-f",
            "lavfi",
            "-i",
            f"color=c={background}:s={frame_width}x{frame_height}:r={fps}",
            "-filter_complex",
            f"[1:v][0:v]overlay=shortest=1:format=auto{scale_filter},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            str(video_path),
        ]
    )


def assemble_animated_webp(frames_dir: Path, output_path: Path, *, fps: int, quality: int, max_dim: int | None, force: bool) -> None:
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_chain = _scale_filter_for_web(max_dim)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%03d.png"),
            "-vf",
            filter_chain,
            "-loop",
            "0",
            "-c:v",
            "libwebp_anim",
            "-lossless",
            "0",
            "-quality",
            str(quality),
            "-compression_level",
            "6",
            str(output_path),
        ]
    )


def assemble_sprite_sheet_from_frames(frames_dir: Path, output_path: Path, *, cols: int, rows: int, force: bool) -> None:
    if output_path.exists() and not force:
        _die(f"Output exists: {output_path} (use --force to overwrite)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(frames_dir / "frame_%03d.png"),
            "-filter_complex",
            f"tile={cols}x{rows}:padding=0:margin=0:color=0x00000000,format=rgba",
            "-frames:v",
            "1",
            str(output_path),
        ]
    )
    scrub_fully_transparent_rgb(output_path)


def build_web_outputs(
    *,
    source_sheet: Path,
    frames: list[str],
    frames_dir: Path,
    out_dir: Path,
    fps: int,
    background: str,
    quality: int,
    lossless_frames: bool,
    max_dim: int | None,
    mp4_crf: int,
    animated: bool,
    force: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_width: int | None = None
    frame_height: int | None = None
    if frames:
        frame_width, frame_height = _png_dimensions(Path(frames[0]))
    sheet_webp = out_dir / "sprite_sheet.webp"
    frames_web_dir = out_dir / "frames"
    mp4_path = out_dir / "sprite_preview_web.mp4"
    animated_webp = out_dir / "sprite_preview.webp"
    convert_image_to_webp(source_sheet, sheet_webp, quality=quality, lossless=lossless_frames, max_dim=None, force=force)
    frame_outputs = convert_frames_to_webp(frames, frames_web_dir, quality=quality, lossless=lossless_frames, max_dim=max_dim, force=force)
    assemble_web_mp4(frames_dir, mp4_path, fps=fps, background=background, max_dim=max_dim, crf=mp4_crf, force=force)
    animated_webp_path: str | None = None
    if animated:
        try:
            assemble_animated_webp(frames_dir, animated_webp, fps=fps, quality=quality, max_dim=max_dim, force=force)
            animated_webp_path = str(animated_webp)
        except Exception as exc:
            print(f"Warning: animated WebP export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    web_manifest = {
        "sheet_webp": str(sheet_webp),
        "frames_webp": frame_outputs,
        "review_mp4": str(mp4_path),
        "animated_webp": animated_webp_path,
        "quality": quality,
        "lossless_frames": lossless_frames,
        "max_dim": max_dim,
        "mp4_crf": mp4_crf,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "frame_count": len(frames),
        "recommended_runtime": "Use sheet_webp as a CSS/canvas atlas when frame dimensions match runtime needs; use frames_webp for lazy-loaded frame sequences.",
    }
    (out_dir / "sprite_web_manifest.json").write_text(json.dumps(web_manifest, indent=2) + "\n", encoding="utf-8")
    return web_manifest


def build(args: argparse.Namespace) -> int:
    input_sheet = args.input_sheet.expanduser().resolve() if args.input_sheet is not None else None
    inferred_cols = args.cols
    inferred_rows = args.rows
    if input_sheet is not None:
        if not input_sheet.is_file():
            _die(f"--input-sheet not found: {input_sheet}")
        input_width, input_height = _png_dimensions(input_sheet)
        if inferred_cols is None:
            if input_width % args.frame_width:
                _die("--input-sheet width is not divisible by --frame-width; pass --cols explicitly or adjust frame size")
            inferred_cols = input_width // args.frame_width
        if inferred_rows is None:
            if input_height % args.frame_height:
                _die("--input-sheet height is not divisible by --frame-height; pass --rows explicitly or adjust frame size")
            inferred_rows = input_height // args.frame_height

    requested_frames = args.frames if args.frames is not None else ((inferred_cols or 4) * (inferred_rows or 4) if inferred_cols or inferred_rows else 16)
    planned = choose_layout(requested_frames, frame_width=args.frame_width, frame_height=args.frame_height, fixed_cols=inferred_cols, fixed_rows=inferred_rows)
    cols = planned["cols"]
    rows = planned["rows"]
    frame_count = planned["frame_count"]
    sheet_width = cols * args.frame_width
    sheet_height = rows * args.frame_height
    size = f"{sheet_width}x{sheet_height}"
    _validate_payload(
        {
            "model": args.model,
            "prompt": "validation",
            "n": 1,
            "size": size,
            "quality": args.quality,
            "output_format": "png",
            "background": "opaque",
        }
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    guide_path = args.out_dir / "layout_guide.png"
    sheet_path = args.out_dir / "sprite_sheet.png"
    alpha_sheet_path = args.out_dir / "sprite_sheet_alpha.png"
    frames_dir = args.out_dir / "frames"
    normalized_frames_dir = args.out_dir / "frames_normalized"
    upscaled_frames_dir = args.out_dir / "frames_upscaled"
    ai_upscaled_frames_dir = args.out_dir / "frames_ai_upscaled"
    web_dir = args.out_dir / "web"
    processed_sheet_path = args.out_dir / "sprite_sheet_processed.png"
    review_video_path = args.out_dir / "sprite_preview.mp4"
    master_video_path = args.out_dir / "sprite_preview_prores.mov"
    manifest_path = args.out_dir / "sprite_manifest.json"

    guide_background = args.key_color if args.transparent else "#ffffff"
    layout = write_layout_guide(
        guide_path,
        cols=cols,
        rows=rows,
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        frame_count=frame_count,
        safe_margin=args.safe_margin,
        background_color=guide_background,
    )
    prompt = _sprite_prompt(args, layout)
    request_payload = {
        "model": args.model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": args.quality,
        "output_format": "png",
        "background": "opaque",
    }

    if args.dry_run:
        print(
            json.dumps(
                {
                    "endpoint": "postprocess" if input_sheet is not None else (EDIT_API_URL if args.use_layout_guide else API_URL),
                    "input_sheet": str(input_sheet) if input_sheet is not None else None,
                    "layout_guide": str(guide_path),
                    "sprite_sheet": str(input_sheet or sheet_path),
                    "alpha_sprite_sheet": str(alpha_sheet_path) if args.transparent else None,
                    "frames_dir": str(frames_dir),
                    "review_video": str(review_video_path),
                    "master_video": str(master_video_path),
                    "web_dir": str(web_dir) if args.web else None,
                    "ai_upscale_provider": args.ai_upscale_provider,
                    "ai_upscale_model": args.ai_upscale_model if args.ai_upscale_provider != "none" else None,
                    "manifest": str(manifest_path),
                    **request_payload,
                },
                indent=2,
            )
        )
        return 0

    response: dict[str, Any] = {}
    source_sheet_path = input_sheet or sheet_path
    if input_sheet is None:
        api_key = load_api_key(args.env_file)
        print(f"Calling {args.model} for {size} sprite sheet", file=sys.stderr)
        started = time.time()
        if args.use_layout_guide:
            response = _call_image_edit_api(request_payload, guide_path, api_key, args.timeout)
        else:
            response = _call_image_api(request_payload, api_key, args.timeout)
        print(f"Sprite sheet completed in {time.time() - started:.1f}s", file=sys.stderr)
        _write_first_image(response, sheet_path, args.force)
    else:
        print(f"Post-processing existing sprite sheet {input_sheet}", file=sys.stderr)

    validate_sheet_dimensions(source_sheet_path, expected_width=sheet_width, expected_height=sheet_height)
    slice_source_path = source_sheet_path
    if args.transparent:
        remove_chroma_key(
            source_sheet_path,
            alpha_sheet_path,
            key_color=args.key_color,
            similarity=args.key_similarity,
            blend=args.key_blend,
            force=args.force,
        )
        validate_sheet_dimensions(alpha_sheet_path, expected_width=sheet_width, expected_height=sheet_height)
        slice_source_path = alpha_sheet_path

    frames = slice_frames(
        slice_source_path,
        frames_dir,
        cols=cols,
        rows=rows,
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        frame_count=frame_count,
        trim=args.slice_trim,
        force=args.force,
    )
    frame_analysis = analyze_frames(frames, edge_margin=args.edge_margin)
    edge_warnings = [item for item in frame_analysis if item.get("touches_edge")]
    if edge_warnings:
        print(f"Warning: {len(edge_warnings)} frame(s) touch the safety edge after slicing.", file=sys.stderr)

    output_frames = frames
    normalized_frame_paths: list[str] | None = None
    normalize_report: list[dict[str, Any]] | None = None
    preview_frames_dir = frames_dir
    if args.normalize_frames:
        output_frames, normalize_report = normalize_frames(frames, normalized_frames_dir, margin=args.normalize_margin, force=args.force)
        normalized_frame_paths = output_frames
        preview_frames_dir = normalized_frames_dir
    upscaled_frames: list[str] | None = None
    ai_upscaled_frames: list[str] | None = None
    ai_upscale_report: list[dict[str, Any]] | None = None
    if abs(args.upscale_factor - 1.0) >= 0.0001:
        upscaled_frames = upscale_frames(output_frames, upscaled_frames_dir, factor=args.upscale_factor, filter_name=args.upscale_filter, force=args.force)
        output_frames = upscaled_frames
        preview_frames_dir = upscaled_frames_dir
    if args.ai_upscale_provider == "fal":
        ai_upscaled_frames, ai_upscale_report = ai_upscale_frames_with_fal(output_frames, ai_upscaled_frames_dir, args=args, force=args.force)
        output_frames = ai_upscaled_frames
        preview_frames_dir = ai_upscaled_frames_dir

    final_sheet_path: Path | None = None
    if preview_frames_dir != frames_dir:
        assemble_sprite_sheet_from_frames(preview_frames_dir, processed_sheet_path, cols=cols, rows=rows, force=args.force)
        final_sheet_path = processed_sheet_path

    assemble_review_video(preview_frames_dir, review_video_path, fps=args.fps, background=args.review_background, force=args.force)
    if args.prores:
        assemble_prores_video(preview_frames_dir, master_video_path, fps=args.fps, force=args.force)
    web_outputs: dict[str, Any] | None = None
    if args.web:
        web_outputs = build_web_outputs(
            source_sheet=final_sheet_path or slice_source_path,
            frames=output_frames,
            frames_dir=preview_frames_dir,
            out_dir=web_dir,
            fps=args.fps,
            background=args.review_background,
            quality=args.web_quality,
            lossless_frames=args.web_lossless,
            max_dim=args.web_max_dim,
            mp4_crf=args.web_mp4_crf,
            animated=args.web_animated,
            force=args.force,
        )

    manifest = {
        "animation": args.animation,
        "subject": args.subject,
        "style": args.style,
        "layout": layout,
        "prompt": prompt,
        "layout_guide": str(guide_path),
        "sprite_sheet": str(source_sheet_path),
        "alpha_sprite_sheet": str(alpha_sheet_path) if args.transparent else None,
        "processed_sprite_sheet": str(final_sheet_path) if final_sheet_path else None,
        "frames": frames,
        "normalized_frames": normalized_frame_paths,
        "upscaled_frames": upscaled_frames,
        "ai_upscaled_frames": ai_upscaled_frames,
        "review_video": str(review_video_path),
        "master_video": str(master_video_path) if args.prores else None,
        "web_outputs": web_outputs,
        "fps": args.fps,
        "slice_trim": args.slice_trim,
        "transparent": args.transparent,
        "key_color": args.key_color if args.transparent else None,
        "key_similarity": args.key_similarity if args.transparent else None,
        "key_blend": args.key_blend if args.transparent else None,
        "review_background": args.review_background,
        "frame_analysis": frame_analysis,
        "edge_warning_count": len(edge_warnings),
        "normalized_frame_report": normalize_report,
        "upscale_factor": args.upscale_factor,
        "upscale_filter": args.upscale_filter if abs(args.upscale_factor - 1.0) >= 0.0001 else None,
        "ai_upscale": {
            "provider": args.ai_upscale_provider,
            "model": args.ai_upscale_model if args.ai_upscale_provider != "none" else None,
            "factor": args.ai_upscale_factor if args.ai_upscale_provider != "none" else None,
            "creativity": args.ai_upscale_creativity if args.ai_upscale_provider != "none" else None,
            "resemblance": args.ai_upscale_resemblance if args.ai_upscale_provider != "none" else None,
            "guidance_scale": args.ai_upscale_guidance_scale if args.ai_upscale_provider != "none" else None,
            "steps": args.ai_upscale_steps if args.ai_upscale_provider != "none" else None,
            "report": ai_upscale_report,
        },
        "request": {key: value for key, value in request_payload.items() if key != "prompt"},
        "usage": response.get("usage"),
        "created": response.get("created"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate, slice, and preview a GPT Image sprite sheet.")
    add = parser.add_argument
    add("--animation", required=True, help="Specific animation to depict across the frames.")
    add("--subject", required=True, help="Character/object being animated.")
    add("--style", default="clean high-quality 2D game animation, crisp silhouette, consistent character design")
    add("--background", default="plain white background")
    add("--transparent", dest="transparent", action="store_true", default=True, help="Generate on chroma key and remove it into alpha PNG frames.")
    add("--no-transparent", dest="transparent", action="store_false", help="Keep the prompted background instead of removing it.")
    add("--key-color", default=DEFAULT_KEY_COLOR, help="Chroma-key color used when --transparent is enabled.")
    add("--key-similarity", type=float, default=0.08, help="ffmpeg colorkey similarity threshold.")
    add("--key-blend", type=float, default=0.03, help="ffmpeg colorkey edge blend.")
    add("--review-background", default="white", help="Background color for the review MP4 after alpha extraction.")
    add("--edge-margin", type=int, default=4, help="Warn when sliced alpha content is within this many pixels of a frame edge.")
    add("--normalize-frames", action="store_true", help="Crop each sliced frame to alpha content, scale down if needed, and recenter it in the frame.")
    add("--normalize-margin", type=int, default=16, help="Minimum transparent margin for --normalize-frames.")
    add("--upscale-factor", type=float, default=1.0, help="Scale transparent frames after slicing/normalization and before video/web exports.")
    add("--upscale-filter", default="lanczos", choices=["lanczos", "bicubic", "spline", "neighbor"], help="ffmpeg scale filter for --upscale-factor.")
    add("--ai-upscale-provider", default="none", choices=["none", "fal"], help="Run a proper AI upscaler after slicing/normalization. Use fal for FAL Clarity Upscaler.")
    add("--ai-upscale-model", default=DEFAULT_FAL_UPSCALER, help="FAL model id for --ai-upscale-provider fal.")
    add("--ai-upscale-factor", type=float, default=2.0, help="AI upscale multiplier passed to the provider.")
    add("--ai-upscale-prompt", help="Prompt for the AI upscaler. Defaults to a sprite-preserving prompt derived from --subject and --animation.")
    add("--ai-upscale-negative-prompt", default="low quality, blurry, distorted, changed pose, changed silhouette, extra limbs, background, text, watermark")
    add("--ai-upscale-creativity", type=float, default=0.18, help="FAL Clarity creativity/denoise strength. Lower preserves sprite frames better.")
    add("--ai-upscale-resemblance", type=float, default=0.9, help="FAL Clarity resemblance/control strength. Higher preserves the source frame better.")
    add("--ai-upscale-guidance-scale", type=float, default=4.0)
    add("--ai-upscale-steps", type=int, default=28)
    add("--fal-env-file", type=Path, help="Env file containing FAL_KEY or FAL_API_KEY. Falls back to workspace env files.")
    add("--fal-timeout", type=int, default=900)
    add("--fal-logs", action="store_true", help="Print FAL queue logs while AI upscaling.")
    add("--frames", type=int, help="Number of animation frames to generate. Defaults to grid capacity, or 16 when no grid is supplied.")
    add("--cols", type=int, help="Grid columns. If omitted, chosen automatically.")
    add("--rows", type=int, help="Grid rows. If omitted, chosen automatically.")
    add("--frame-width", type=int, default=256)
    add("--frame-height", type=int, default=256)
    add("--safe-margin", type=int, help="Minimum pixel margin inside each cell requested in the layout guide and prompt. Defaults to max(24, frame_size/8).")
    add("--fps", type=int, default=8)
    add("--slice-trim", type=int, default=0, help="Pixels to trim from each cell edge while slicing frames.")
    add("--model", default=DEFAULT_MODEL)
    add("--quality", default="medium")
    add("--out-dir", type=Path, default=Path("runs/sprite-sheet"))
    add("--input-sheet", type=Path, help="Existing PNG sprite sheet to post-process instead of generating a new sheet.")
    add("--env-file", type=Path)
    add("--timeout", type=int, default=240)
    add("--force", action="store_true")
    add("--dry-run", action="store_true")
    add("--prores", dest="prores", action="store_true", default=True, help="Also write a high-quality ProRes MOV preview.")
    add("--no-prores", dest="prores", action="store_false")
    add("--web", dest="web", action="store_true", default=True, help="Write web-optimized WebP frames/sheet and a lighter MP4 preview.")
    add("--no-web", dest="web", action="store_false")
    add("--web-quality", type=int, default=82, help="WebP quality for web exports.")
    add("--web-lossless", action="store_true", help="Use lossless WebP for sheet and frame exports.")
    add("--web-max-dim", type=int, default=512, help="Maximum width/height for web frame animation exports. Use 0 for original size.")
    add("--web-mp4-crf", type=int, default=24, help="CRF for web MP4 preview; lower is higher quality.")
    add("--web-animated", action="store_true", help="Also write animated WebP. Off by default because atlas/frame assets are faster for web runtimes.")
    add("--use-layout-guide", dest="use_layout_guide", action="store_true", default=True)
    add("--no-layout-guide", dest="use_layout_guide", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cols is not None and args.cols < 1:
        _die("--cols must be >= 1")
    if args.rows is not None and args.rows < 1:
        _die("--rows must be >= 1")
    if args.frame_width < 16 or args.frame_height < 16:
        _die("--frame-width and --frame-height must be >= 16")
    if args.frame_width % 16 or args.frame_height % 16:
        _die("--frame-width and --frame-height must be multiples of 16")
    if args.fps < 1:
        _die("--fps must be >= 1")
    if args.slice_trim < 0:
        _die("--slice-trim must be >= 0")
    if args.safe_margin is not None and args.safe_margin < 0:
        _die("--safe-margin must be >= 0")
    _parse_hex_color(args.key_color)
    if args.key_similarity < 0 or args.key_similarity > 1:
        _die("--key-similarity must be between 0 and 1")
    if args.key_blend < 0 or args.key_blend > 1:
        _die("--key-blend must be between 0 and 1")
    if args.edge_margin < 0:
        _die("--edge-margin must be >= 0")
    if args.normalize_margin < 0:
        _die("--normalize-margin must be >= 0")
    if args.upscale_factor <= 0:
        _die("--upscale-factor must be > 0")
    if args.ai_upscale_factor <= 0:
        _die("--ai-upscale-factor must be > 0")
    if args.ai_upscale_provider == "fal" and not args.ai_upscale_model:
        _die("--ai-upscale-model is required for --ai-upscale-provider fal")
    if args.ai_upscale_steps < 1:
        _die("--ai-upscale-steps must be >= 1")
    if args.fal_timeout < 1:
        _die("--fal-timeout must be >= 1")
    for name in ("ai_upscale_creativity", "ai_upscale_resemblance"):
        value = getattr(args, name)
        if value < 0 or value > 1:
            _die(f"--{name.replace('_', '-')} must be between 0 and 1")
    if args.web_quality < 0 or args.web_quality > 100:
        _die("--web-quality must be between 0 and 100")
    if args.web_max_dim < 0:
        _die("--web-max-dim must be >= 0")
    if args.web_mp4_crf < 0 or args.web_mp4_crf > 51:
        _die("--web-mp4-crf must be between 0 and 51")
    if args.web_max_dim == 0:
        args.web_max_dim = None
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
