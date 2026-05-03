#!/usr/bin/env python3
"""Logo Ideas orchestrator: Kimi K2 (Fireworks) drafts prompts, fal renders them."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from artagents.executors.generate_image.run import _candidate_env_files, _read_env_value


FIREWORKS_CHAT_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FAL_QUEUE_URL = "https://queue.fal.run"

DEFAULT_COUNT = 9
DEFAULT_FIREWORKS_MODEL = "accounts/fireworks/models/kimi-k2p5"
DEFAULT_PROVIDER = "z-image"
DEFAULT_IMAGE_SIZE = "square_hd"
DEFAULT_OUTPUT_FORMAT = "png"

PROVIDER_MODEL_IDS = {
    "z-image": "fal-ai/z-image/turbo",
    "gpt-image": "openai/gpt-image-2",
}

FAL_PRESETS = {
    "square_hd",
    "square",
    "portrait_4_3",
    "portrait_16_9",
    "landscape_4_3",
    "landscape_16_9",
}


def _load_env_var(name: str, env_file: Path | None) -> str:
    import os

    value = os.environ.get(name, "").strip()
    if value:
        return value
    tried: list[str] = [f"{name} environment variable"]
    for candidate in _candidate_env_files(env_file):
        tried.append(str(candidate))
        if value := _read_env_value(candidate, name):
            return value
    raise SystemExit(f"{name} not found. Tried: {', '.join(tried)}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_image_size(value: str) -> str | dict[str, int]:
    if value in FAL_PRESETS:
        return value
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            "image-size must be a fal preset (square_hd, portrait_16_9, ...) or WIDTHxHEIGHT"
        )
    return {"width": int(match.group(1)), "height": int(match.group(2))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a grid of logo ideas via Kimi K2 + fal.")
    parser.add_argument("--ideas", required=True, help="Brief describing the logo: brand, vibe, motifs, constraints.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for concepts, prompts, images, and the grid.")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"Number of logos to generate (default {DEFAULT_COUNT}).")
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=sorted(PROVIDER_MODEL_IDS),
        help=f"Image provider (default {DEFAULT_PROVIDER}).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_FIREWORKS_MODEL,
        help=f"Fireworks chat model id (default {DEFAULT_FIREWORKS_MODEL}).",
    )
    parser.add_argument(
        "--image-size",
        default=DEFAULT_IMAGE_SIZE,
        type=parse_image_size,
        help=f"fal image size: preset or WIDTHxHEIGHT (default {DEFAULT_IMAGE_SIZE}).",
    )
    parser.add_argument(
        "--output-format",
        default=DEFAULT_OUTPUT_FORMAT,
        choices=("png", "jpeg", "jpg", "webp"),
        help=f"Image format saved locally (default {DEFAULT_OUTPUT_FORMAT}).",
    )
    parser.add_argument("--env-file", type=Path, help="Env file holding FIREWORKS_API_KEY and FAL_KEY.")
    parser.add_argument("--dry-run", action="store_true", help="Plan and write artifacts; skip both Fireworks and fal calls.")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.count > 64:
        parser.error("--count must be <= 64 (sanity bound)")


def build_layout(out_dir: Path) -> dict[str, Path]:
    root = out_dir.expanduser().resolve()
    layout = {
        "root": root,
        "images": root / "images",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("content-type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _http_get_json(url: str, headers: dict[str, str], *, timeout: int = 60) -> dict[str, Any]:
    request = Request(url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _http_get_bytes(url: str, *, timeout: int = 120) -> bytes:
    with urlopen(Request(url, method="GET"), timeout=timeout) as response:
        return response.read()


def _system_prompt() -> str:
    return (
        "You are a senior brand designer. Given a logo brief, propose distinct, "
        "creatively varied logo concepts. Each concept should differ in style, "
        "composition, or motif — not minor color variants. Return only JSON."
    )


def _user_prompt(ideas: str, count: int) -> str:
    return (
        f"Brief:\n{ideas}\n\n"
        f"Produce exactly {count} logo concepts. Return JSON of the shape:\n"
        '{"concepts":[{"name":"short title","rationale":"1 sentence why",'
        '"prompt":"single self-contained image-gen prompt, ~40 words, '
        "describing style, layout, palette, typography hints, no negative prompts, "
        'no text like \\"logo:\\""}]}\n'
        "The 'prompt' field is fed verbatim to a text-to-image model — make it "
        "concrete and visual. Avoid trademarked references unless the brief asks."
    )


def call_fireworks_concepts(
    *,
    ideas: str,
    count: int,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(ideas, count)},
        ],
        "temperature": 0.9,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    headers = {"authorization": f"Bearer {api_key}"}
    try:
        response = _http_post_json(FIREWORKS_CHAT_URL, headers, payload, timeout=180)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SystemExit(f"Fireworks chat call failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Fireworks chat call failed: {exc}") from exc
    return response


def parse_concepts(response: dict[str, Any], *, count: int) -> list[dict[str, Any]]:
    choices = response.get("choices") or []
    if not choices:
        raise SystemExit("Fireworks response had no choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    text = content.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise SystemExit(f"Could not parse JSON from Fireworks response: {text[:300]}")
        data = json.loads(match.group(0))
    raw_concepts = data.get("concepts") if isinstance(data, dict) else None
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise SystemExit(f"Fireworks response missing 'concepts' list: {text[:300]}")
    concepts: list[dict[str, Any]] = []
    for index, item in enumerate(raw_concepts[:count], start=1):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        concepts.append(
            {
                "candidate_id": f"logo-{index:03d}",
                "index": index,
                "name": str(item.get("name") or f"Concept {index}").strip(),
                "rationale": str(item.get("rationale") or "").strip(),
                "prompt": prompt,
            }
        )
    if not concepts:
        raise SystemExit("Fireworks response yielded no usable concepts")
    return concepts


def _planned_concepts(ideas: str, count: int) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": f"logo-{index:03d}",
            "index": index,
            "name": f"Planned concept {index}",
            "rationale": "Dry-run placeholder; no model call was made.",
            "prompt": f"[dry-run] minimalist logo for: {ideas}",
        }
        for index in range(1, count + 1)
    ]


def _fal_payload(provider: str, prompt: str, image_size: str | dict[str, int], output_format: str) -> dict[str, Any]:
    fmt = "jpeg" if output_format == "jpg" else output_format
    if provider == "z-image":
        return {
            "prompt": prompt,
            "image_size": image_size,
            "num_images": 1,
            "output_format": fmt,
        }
    if provider == "gpt-image":
        return {
            "prompt": prompt,
            "image_size": image_size,
            "num_images": 1,
            "output_format": fmt,
            "quality": "high",
        }
    raise SystemExit(f"unknown provider {provider!r}")


def submit_fal_job(provider: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    model_id = PROVIDER_MODEL_IDS[provider]
    url = f"{FAL_QUEUE_URL}/{model_id}"
    headers = {"authorization": f"Key {api_key}"}
    try:
        return _http_post_json(url, headers, payload, timeout=120)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SystemExit(f"fal submit failed ({exc.code}) for {model_id}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"fal submit failed for {model_id}: {exc}") from exc


def poll_fal_result(submission: dict[str, Any], api_key: str, *, max_wait_sec: int = 300) -> dict[str, Any]:
    status_url = submission.get("status_url")
    response_url = submission.get("response_url")
    if not status_url or not response_url:
        raise SystemExit(f"fal submission missing status_url/response_url: {submission}")
    headers = {"authorization": f"Key {api_key}"}
    deadline = time.monotonic() + max_wait_sec
    delay = 2.0
    while time.monotonic() < deadline:
        try:
            status = _http_get_json(status_url, headers, timeout=30)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise SystemExit(f"fal status poll failed ({exc.code}): {detail}") from exc
        state = str(status.get("status") or "").upper()
        if state in {"COMPLETED", "OK"}:
            return _http_get_json(response_url, headers, timeout=60)
        if state in {"FAILED", "ERROR", "CANCELLED"}:
            raise SystemExit(f"fal job {state}: {status}")
        time.sleep(delay)
        delay = min(delay * 1.4, 8.0)
    raise SystemExit(f"fal job timed out after {max_wait_sec}s; last status_url={status_url}")


def _ext_for_format(output_format: str) -> str:
    return "jpg" if output_format in ("jpeg", "jpg") else output_format


def _save_first_image(result: dict[str, Any], dest: Path) -> dict[str, Any]:
    images = result.get("images") or []
    if not images:
        raise SystemExit(f"fal result had no images: {result}")
    first = images[0]
    url = first.get("url")
    if not url:
        raise SystemExit(f"fal image entry missing url: {first}")
    data = _http_get_bytes(url, timeout=180)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {
        "path": str(dest),
        "source_url": url,
        "width": first.get("width"),
        "height": first.get("height"),
        "content_type": first.get("content_type"),
        "bytes": len(data),
    }


def _placeholder_image(dest: Path, label: str) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        dest.write_bytes(b"")
        return {"path": str(dest), "placeholder": True, "reason": "Pillow unavailable"}
    image = Image.new("RGB", (768, 768), (24, 24, 28))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 24), "[dry-run]", fill=(220, 220, 220), font=font)
    draw.text((24, 72), label[:48], fill=(180, 180, 180), font=font)
    image.save(dest, quality=90)
    return {"path": str(dest), "placeholder": True, "reason": "dry-run"}


def render_concepts(
    *,
    concepts: list[dict[str, Any]],
    layout: dict[str, Path],
    provider: str,
    image_size: str | dict[str, int],
    output_format: str,
    fal_key: str | None,
    dry_run: bool,
) -> list[dict[str, Any]]:
    ext = _ext_for_format(output_format)
    results: list[dict[str, Any]] = []
    for concept in concepts:
        candidate_id = concept["candidate_id"]
        dest = layout["images"] / f"{candidate_id}.{ext}"
        if dry_run or not fal_key:
            generated = _placeholder_image(dest, concept["name"])
        else:
            payload = _fal_payload(provider, concept["prompt"], image_size, output_format)
            submission = submit_fal_job(provider, payload, fal_key)
            result = poll_fal_result(submission, fal_key)
            generated = _save_first_image(result, dest)
            generated["request_id"] = submission.get("request_id")
        results.append({**concept, "generated": generated})
    return results


def write_grid(results: list[dict[str, Any]], out_path: Path) -> dict[str, Any]:
    paths: list[tuple[Path, str]] = []
    for item in results:
        gen = item.get("generated") or {}
        path = Path(str(gen.get("path") or ""))
        if path.is_file() and path.stat().st_size > 0:
            paths.append((path, str(item.get("name") or item.get("candidate_id"))))
    if not paths:
        return {"path": None, "image_count": 0, "reason": "no images available"}
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return {"path": None, "image_count": len(paths), "reason": "Pillow unavailable"}
    cols = max(1, math.ceil(math.sqrt(len(paths))))
    rows = math.ceil(len(paths) / cols)
    tile = 384
    label_h = 28
    grid = Image.new("RGB", (cols * tile, rows * (tile + label_h)), (16, 16, 18))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for index, (path, label) in enumerate(paths):
        col = index % cols
        row = index // cols
        x = col * tile
        y = row * (tile + label_h)
        try:
            with Image.open(path) as opened:
                tile_image = opened.convert("RGB")
                tile_image.thumbnail((tile, tile))
                offset_x = x + (tile - tile_image.width) // 2
                offset_y = y + (tile - tile_image.height) // 2
                grid.paste(tile_image, (offset_x, offset_y))
        except Exception:
            draw.rectangle((x, y, x + tile, y + tile), outline=(60, 60, 64), width=2)
        draw.text((x + 8, y + tile + 4), label[:40], fill=(220, 220, 220), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(out_path, quality=90)
    return {"path": str(out_path), "image_count": len(paths), "cols": cols, "rows": rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    layout = build_layout(args.out)
    image_size_payload = args.image_size if isinstance(args.image_size, str) else dict(args.image_size)

    plan = {
        "tool": "logo_ideas",
        "version": 1,
        "mode": "dry-run" if args.dry_run else "run",
        "ideas": args.ideas,
        "count": args.count,
        "provider": args.provider,
        "fal_model_id": PROVIDER_MODEL_IDS[args.provider],
        "fireworks_model": args.model,
        "image_size": image_size_payload,
        "output_format": args.output_format,
        "out": str(layout["root"]),
    }
    write_json(layout["root"] / "logo-plan.json", plan)

    if args.dry_run:
        concepts = _planned_concepts(args.ideas, args.count)
        concepts_payload = {"mode": "dry-run", "raw_response": None, "concepts": concepts}
    else:
        fireworks_key = _load_env_var("FIREWORKS_API_KEY", args.env_file)
        response = call_fireworks_concepts(
            ideas=args.ideas,
            count=args.count,
            model=args.model,
            api_key=fireworks_key,
        )
        concepts = parse_concepts(response, count=args.count)
        concepts_payload = {
            "mode": "run",
            "model": args.model,
            "usage": response.get("usage"),
            "concepts": concepts,
        }
    write_json(layout["root"] / "concepts.json", concepts_payload)
    write_json(
        layout["root"] / "prompts.json",
        {
            "provider": args.provider,
            "fal_model_id": PROVIDER_MODEL_IDS[args.provider],
            "image_size": image_size_payload,
            "output_format": args.output_format,
            "prompts": [
                {"candidate_id": c["candidate_id"], "name": c["name"], "prompt": c["prompt"]}
                for c in concepts
            ],
        },
    )

    fal_key = None if args.dry_run else _load_env_var("FAL_KEY", args.env_file)
    results = render_concepts(
        concepts=concepts,
        layout=layout,
        provider=args.provider,
        image_size=image_size_payload,
        output_format=args.output_format,
        fal_key=fal_key,
        dry_run=args.dry_run,
    )

    grid = write_grid(results, layout["root"] / "grid.jpg")
    manifest = {
        "version": 1,
        "mode": plan["mode"],
        "ideas": args.ideas,
        "count": args.count,
        "provider": args.provider,
        "fireworks_model": args.model,
        "image_size": image_size_payload,
        "grid": grid,
        "candidates": results,
    }
    write_json(layout["root"] / "logo-manifest.json", manifest)

    print(f"wrote_logo_manifest={layout['root'] / 'logo-manifest.json'}")
    if grid.get("path"):
        print(f"wrote_grid={grid['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
