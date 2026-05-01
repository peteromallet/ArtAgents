#!/usr/bin/env python3
"""Generate image files with OpenAI GPT Image models."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from artagents.audit import AuditContext

API_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_FORMAT = "png"

QUALITIES = {"low", "medium", "high", "auto"}
FORMATS = {"png", "jpeg", "jpg", "webp"}
BACKGROUNDS = {"opaque", "auto", "transparent"}
MODERATION = {"auto", "low"}

GPT_IMAGE_2_MIN_PIXELS = 655_360
GPT_IMAGE_2_MAX_PIXELS = 8_294_400
GPT_IMAGE_2_MAX_EDGE = 3840
GPT_IMAGE_2_MAX_RATIO = 3.0


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        env_key, env_value = line.split("=", 1)
        if env_key.strip() == key:
            return env_value.strip().strip('"').strip("'")
    return ""


def _candidate_env_files(env_file: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(env_file)
    repo_root = Path(__file__).resolve().parents[1]
    workspace = repo_root.parent
    candidates.extend(
        [
            Path.cwd() / "this.env",
            Path.cwd() / ".env",
            Path(__file__).resolve().parent / "this.env",
            Path(__file__).resolve().parent / ".env",
            repo_root / "this.env",
            repo_root / ".env",
            workspace / "this.env",
            workspace / ".env",
            workspace / "reigh-app" / "this.env",
            workspace / "reigh-app" / ".env",
            workspace / "reigh-worker" / "this.env",
            workspace / "reigh-worker" / ".env",
            workspace / "reigh-worker-orchestrator" / "this.env",
            workspace / "reigh-worker-orchestrator" / ".env",
            Path.home() / "this.env",
            Path.home() / ".env",
            Path.home() / ".codex" / "this.env",
            Path.home() / ".codex" / ".env",
            Path.home() / ".claude" / "this.env",
            Path.home() / ".claude" / ".env",
            Path.home() / ".hermes" / "this.env",
            Path.home() / ".hermes" / ".env",
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


def load_api_key(env_file: Path | None = None) -> str:
    if key := os.environ.get("OPENAI_API_KEY", "").strip():
        return key
    tried: list[str] = ["OPENAI_API_KEY environment variable"]
    for candidate in _candidate_env_files(env_file):
        tried.append(str(candidate))
        if key := _read_env_value(candidate, "OPENAI_API_KEY"):
            return key
    raise SystemExit(f"OPENAI_API_KEY not found. Tried: {', '.join(tried)}")


def _normalize_format(value: str) -> str:
    fmt = value.lower()
    if fmt not in FORMATS:
        _die("--output-format must be png, jpeg, jpg, or webp")
    return "jpeg" if fmt == "jpg" else fmt


def _parse_size(size: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _validate_size(size: str, model: str) -> None:
    if size == "auto":
        return
    if model != "gpt-image-2":
        if size not in {"1024x1024", "1536x1024", "1024x1536"}:
            _die("For models before gpt-image-2, size must be 1024x1024, 1536x1024, 1024x1536, or auto.")
        return
    parsed = _parse_size(size)
    if parsed is None:
        _die("size must be auto or WIDTHxHEIGHT, for example 1024x1024")
    width, height = parsed
    if width % 16 or height % 16:
        _die("gpt-image-2 size width and height must be multiples of 16px")
    if max(width, height) > GPT_IMAGE_2_MAX_EDGE:
        _die("gpt-image-2 size maximum edge length is 3840px")
    if max(width, height) / min(width, height) > GPT_IMAGE_2_MAX_RATIO:
        _die("gpt-image-2 size long edge to short edge ratio must not exceed 3:1")
    pixels = width * height
    if pixels < GPT_IMAGE_2_MIN_PIXELS or pixels > GPT_IMAGE_2_MAX_PIXELS:
        _die("gpt-image-2 size total pixels must be between 655,360 and 8,294,400")


def _validate_payload(payload: dict[str, Any]) -> None:
    model = str(payload["model"])
    if not model.startswith("gpt-image-"):
        _die("--model must be a GPT Image model, for example gpt-image-2")
    n = int(payload["n"])
    if n < 1 or n > 10:
        _die("--n must be between 1 and 10")
    _validate_size(str(payload["size"]), model)
    if payload["quality"] not in QUALITIES:
        _die("--quality must be low, medium, high, or auto")
    if payload.get("background") and payload["background"] not in BACKGROUNDS:
        _die("--background must be opaque, auto, or transparent")
    if model == "gpt-image-2" and payload.get("background") == "transparent":
        _die("gpt-image-2 does not support transparent backgrounds; use opaque/auto or explicitly choose an older supported model")
    if payload.get("moderation") and payload["moderation"] not in MODERATION:
        _die("--moderation must be auto or low")
    compression = payload.get("output_compression")
    if compression is not None and not (0 <= int(compression) <= 100):
        _die("--output-compression must be between 0 and 100")


def _normalize_job(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        prompt = item.strip()
        if not prompt:
            _die(f"Empty prompt at item {index}")
        return {"prompt": prompt}
    if isinstance(item, dict) and str(item.get("prompt", "")).strip():
        return dict(item)
    _die(f"Invalid prompt item {index}; expected string or object with prompt")
    return {}


def _load_prompts(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        _die(f"Prompts file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        _die(f"Prompts file is empty: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, list):
            _die("JSON prompts file must contain an array")
        return [_normalize_job(item, index + 1) for index, item in enumerate(data)]
    jobs: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{") or line.startswith('"'):
            jobs.append(_normalize_job(json.loads(line), line_no))
        else:
            jobs.append({"prompt": line})
    if not jobs:
        _die("No prompts found")
    return jobs


def _slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return value[:64] or "image"


def _output_paths(out_dir: Path, prompt: str, fmt: str, job_index: int, n: int, explicit_out: str | None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "." + fmt
    if explicit_out:
        base = Path(explicit_out)
        if not base.suffix:
            base = base.with_suffix(ext)
        base = out_dir / base.name
    else:
        base = out_dir / f"{job_index:03d}-{_slugify(prompt)}{ext}"
    if n == 1:
        return [base]
    return [base.with_name(f"{base.stem}-{i}{base.suffix}") for i in range(1, n + 1)]


def _call_image_api(payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
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
        detail = exc.read().decode("utf-8", errors="replace")
        _die(f"OpenAI API error {exc.code}: {detail}")
    except URLError as exc:
        _die(f"Network error: {exc}")
    return {}


def _write_images(response: dict[str, Any], paths: list[Path], force: bool) -> list[str]:
    written: list[str] = []
    for item, path in zip(response.get("data") or [], paths):
        image_b64 = item.get("b64_json")
        if not image_b64:
            _warn(f"No b64_json returned for {path}")
            continue
        if path.exists() and not force:
            _die(f"Output exists: {path} (use --force to overwrite)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(image_b64))
        print(f"Wrote {path}")
        written.append(str(path))
    return written


def _jobs_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    jobs = [{"prompt": prompt} for prompt in args.prompt or []]
    if args.prompts_file:
        jobs.extend(_load_prompts(args.prompts_file))
    if not jobs:
        _die("Provide --prompt or --prompts-file")
    return jobs


def generate(args: argparse.Namespace) -> int:
    jobs = _jobs_from_args(args)
    api_key = "" if args.dry_run else load_api_key(args.env_file)
    out_dir = args.out_dir
    default_format = _normalize_format(args.output_format)
    manifest: list[dict[str, Any]] = []
    audit = AuditContext.from_env()

    for index, job in enumerate(jobs, start=1):
        prompt = str(job["prompt"]).strip()
        payload = {
            "model": job.get("model", args.model),
            "prompt": prompt,
            "n": int(job.get("n", args.n)),
            "size": job.get("size", args.size),
            "quality": job.get("quality", args.quality),
            "output_format": _normalize_format(str(job.get("output_format", default_format))),
            "output_compression": job.get("output_compression", args.output_compression),
            "background": job.get("background", args.background),
            "moderation": job.get("moderation", args.moderation),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        _validate_payload(payload)
        paths = _output_paths(out_dir, prompt, payload["output_format"], index, int(payload["n"]), job.get("out"))

        if args.dry_run:
            print(json.dumps({"endpoint": API_URL, "outputs": [str(path) for path in paths], **payload}, indent=2))
            continue

        print(f"[{index}/{len(jobs)}] Calling {payload['model']} for {payload['n']} image(s)", file=sys.stderr)
        started = time.time()
        response = _call_image_api(payload, api_key, args.timeout)
        print(f"[{index}/{len(jobs)}] Completed in {time.time() - started:.1f}s", file=sys.stderr)
        written = _write_images(response, paths, args.force)
        if audit is not None:
            prompt_id = audit.register_prompt_ref(
                prompt=prompt,
                label=f"Image prompt {index}",
                stage="generate_image",
                metadata={key: value for key, value in payload.items() if key != "prompt"},
            )
            output_ids = [
                audit.register_asset(
                    kind="generated_image",
                    path=output,
                    label=Path(output).name,
                    parents=[prompt_id],
                    stage="generate_image",
                    metadata={
                        "model": payload.get("model"),
                        "size": payload.get("size"),
                        "quality": payload.get("quality"),
                        "output_format": payload.get("output_format"),
                        "created": response.get("created"),
                    },
                )
                for output in written
            ]
            audit.register_node(
                stage="generate_image",
                label=f"Generate image job {index}",
                parents=[prompt_id],
                outputs=output_ids,
                metadata={"model": payload.get("model"), "n": payload.get("n"), "usage": response.get("usage")},
            )
        manifest.append(
            {
                "prompt": prompt,
                "request": {key: value for key, value in payload.items() if key != "prompt"},
                "outputs": written,
                "usage": response.get("usage"),
                "created": response.get("created"),
            }
        )

    if args.manifest and not args.dry_run:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if audit is not None:
            audit.register_asset(
                kind="image_manifest",
                path=args.manifest,
                label="Generated image manifest",
                stage="generate_image",
                metadata={"jobs": len(manifest)},
            )
        print(f"Wrote {args.manifest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate images with OpenAI GPT Image models.")
    add = parser.add_argument
    add("--prompt", action="append", help="Prompt; repeat for multiple prompts.")
    add("--prompts-file", type=Path, help="Text, JSON, or JSONL prompt list.")
    add("--model", default=DEFAULT_MODEL)
    add("--n", type=int, default=1, help="Images per prompt.")
    add("--size", default=DEFAULT_SIZE)
    add("--quality", default=DEFAULT_QUALITY)
    add("--output-format", default=DEFAULT_FORMAT)
    add("--output-compression", type=int)
    add("--background", choices=sorted(BACKGROUNDS))
    add("--moderation", choices=sorted(MODERATION))
    add("--out-dir", type=Path, default=Path("output/gpt-image"))
    add("--manifest", type=Path, default=Path("output/gpt-image/manifest.json"))
    add("--env-file", type=Path)
    add("--timeout", type=int, default=180)
    add("--force", action="store_true")
    add("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return generate(args)
