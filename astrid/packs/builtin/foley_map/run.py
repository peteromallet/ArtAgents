#!/usr/bin/env python3
"""Foley Map orchestrator: tile → VLM → Foley → review → spatial-audio page."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


GLOBAL_QUERY = (
    "You are designing AMBIENT atmosphere audio for a video — drones, hums, "
    "textures, room tone, environmental beds. NOT discrete sound effects, NOT "
    "music, NOT speech. In 2-3 sentences, describe the scene's ambient "
    "soundscape: setting, materials, mood, the textural sound of the "
    "environment itself. Plain prose, no lists. Do not mention 'video' or "
    "'frame'."
)


def _tile_query(global_context: str, row: int, col: int, rows: int, cols: int) -> str:
    return (
        f"Global ambient scene: {global_context}\n\n"
        f"This image shows the (row {row}, col {col}) region of a {rows}x{cols} "
        f"grid covering that scene. Write a single audio prompt — about 20 "
        f"words — that combines TWO things:\n"
        f"  (1) an AMBIENT BED suited to this region's materials and motion "
        f"(drone, hum, room tone, environmental texture). Keep this dominant.\n"
        f"  (2) ONE distinct, quirky, or playful detail specific to what's in "
        f"this region — a small character noise, an unusual material gesture, "
        f"a single tiny flourish that gives this region its own personality.\n"
        f"No music, no speech. Do not mention 'tile', 'crop', 'region', or "
        f"'image'. Output only the prompt."
    )


def _run_subprocess(cmd: list[str], *, label: str) -> str:
    print(f"[foley_map] {label}: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"[foley_map] {label} failed (exit {proc.returncode})")
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    return proc.stdout


def step_tile(args: argparse.Namespace, out: Path) -> Path:
    cmd = [
        sys.executable, "-m", "astrid.packs.builtin.tile_video.run",
        "--video", str(args.video),
        "--out", str(out),
        "--grid", f"{args.grid[0]}x{args.grid[1]}",
        "--overlap", str(args.overlap),
    ]
    if args.trim is not None:
        cmd += ["--trim", str(args.trim)]
    if args.dry_run:
        cmd += ["--dry-run"]
    _run_subprocess(cmd, label="tile_video")
    return out / "tiles.json"


def _visual_understand_query(image: Path, query: str, env_file: Path | None,
                              out_json: Path, dry_run: bool) -> str:
    cmd = [
        sys.executable, "-m", "astrid.packs.builtin.visual_understand.run",
        "--image", str(image),
        "--query", query,
        "--out-dir", str(out_json.parent / "_vlm_scratch"),
        "--out", str(out_json),
        "--mode", "fast",
        "--max-output-tokens", "300",
    ]
    if env_file:
        cmd += ["--env-file", str(env_file)]
    if dry_run:
        cmd += ["--dry-run"]
    _run_subprocess(cmd, label=f"visual_understand({image.name})")
    if dry_run:
        return f"[dry-run prompt for {image.name}]"
    data = json.loads(out_json.read_text(encoding="utf-8"))
    results = data.get("results") or []
    if not results or results[0].get("status") != "ok":
        raise SystemExit(f"VLM call failed: {results}")
    return (results[0].get("answer") or "").strip()


def step_prompts(args: argparse.Namespace, out: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    prompts_path = out / "prompts.json"
    if prompts_path.exists() and not args.force_prompts:
        return json.loads(prompts_path.read_text(encoding="utf-8"))

    global_frame = (out / manifest["global_first_frame"]).resolve()
    rows = manifest["grid"]["rows"]
    cols = manifest["grid"]["cols"]

    global_context = _visual_understand_query(
        global_frame, GLOBAL_QUERY,
        args.env_file, out / "_vlm_global.json",
        args.dry_run,
    )

    tile_prompts: dict[str, str] = {}
    work = []
    for tile in manifest["tiles"]:
        frame_abs = (out / tile["first_frame"]).resolve()
        out_json = out / f"_vlm_{tile['id']}.json"
        query = _tile_query(global_context, tile["row"], tile["col"], rows, cols)
        work.append((tile["id"], frame_abs, query, out_json))

    # VLM calls are network-bound but cheap; run a few in parallel.
    with ThreadPoolExecutor(max_workers=args.vlm_concurrency) as pool:
        futures = {
            pool.submit(_visual_understand_query, fp, q, args.env_file, oj, args.dry_run): tid
            for (tid, fp, q, oj) in work
        }
        for fut in as_completed(futures):
            tid = futures[fut]
            tile_prompts[tid] = fut.result()

    prompts_payload = {
        "global_context": global_context,
        "tile_prompts": tile_prompts,
    }
    prompts_path.write_text(json.dumps(prompts_payload, indent=2) + "\n", encoding="utf-8")
    print(f"[foley_map] wrote prompts: {prompts_path}", file=sys.stderr)
    return prompts_payload


def _foley_one(clip: Path, prompt: str, out_audio: Path, env_file: Path | None,
                dry_run: bool) -> None:
    cmd = [
        sys.executable, "-m", "astrid.packs.external.fal_foley.run",
        "--clip", str(clip),
        "--prompt", prompt,
        "--out", str(out_audio),
    ]
    if env_file:
        cmd += ["--env-file", str(env_file)]
    if dry_run:
        cmd += ["--dry-run"]
    _run_subprocess(cmd, label=f"fal_foley({out_audio.name})")


def step_foley(args: argparse.Namespace, out: Path, manifest: dict[str, Any],
                prompts: dict[str, Any], retry_ids: set[str] | None) -> dict[str, Any]:
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tile_prompts = prompts["tile_prompts"]

    work = []
    for tile in manifest["tiles"]:
        tid = tile["id"]
        out_audio = audio_dir / f"{tile['row']}_{tile['col']}.wav"
        existing = out_audio.exists() and (retry_ids is None or tid not in retry_ids)
        if retry_ids is not None and tid not in retry_ids and existing:
            continue
        if existing and not args.force_foley:
            continue
        clip_abs = (out / tile["tile_clip"]).resolve()
        work.append((tid, clip_abs, tile_prompts[tid], out_audio))

    print(f"[foley_map] foley work: {len(work)} tiles "
          f"(skipped {len(manifest['tiles']) - len(work)} cached)", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.foley_concurrency) as pool:
        futures = [
            pool.submit(_foley_one, clip, prompt, out_audio, args.env_file, args.dry_run)
            for (_tid, clip, prompt, out_audio) in work
        ]
        for fut in as_completed(futures):
            fut.result()

    # Augment manifest with prompt + audio paths for downstream tools.
    enriched = dict(manifest)
    enriched_tiles = []
    for tile in manifest["tiles"]:
        tid = tile["id"]
        audio_rel = f"audio/{tile['row']}_{tile['col']}.wav"
        enriched_tiles.append({
            **tile,
            "prompt": tile_prompts.get(tid, ""),
            "foley_audio": audio_rel,
        })
    enriched["tiles"] = enriched_tiles
    enriched["global_context"] = prompts["global_context"]
    return enriched


def step_review(out: Path, enriched: dict[str, Any]) -> Path:
    manifest_path = out / "tiles.json"
    manifest_path.write_text(json.dumps(enriched, indent=2) + "\n", encoding="utf-8")
    review_path = out / "review.html"
    cmd = [
        sys.executable, "-m", "astrid.packs.builtin.foley_review.run",
        "--manifest", str(manifest_path),
        "--out", str(review_path),
    ]
    _run_subprocess(cmd, label="foley_review")
    return review_path


def step_page(out: Path) -> Path:
    page_dir = out / "page"
    cmd = [
        sys.executable, "-m", "astrid.packs.builtin.spatial_audio_page.run",
        "--manifest", str(out / "tiles.json"),
        "--out", str(page_dir),
    ]
    _run_subprocess(cmd, label="spatial_audio_page")
    return page_dir / "index.html"


def _parse_grid(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*([1-9][0-9]*)\s*[xX]\s*([1-9][0-9]*)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("--grid must be COLSxROWS, e.g. 4x4")
    return int(match.group(1)), int(match.group(2))


def _load_flagged(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    flags = raw.get("flags") or raw  # allow {flags: {...}} or {...} directly
    return {tile_id for tile_id, status in flags.items() if status == "bad"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Spatial Foley pipeline: tile → VLM → Foley → review → page.")
    p.add_argument("--video", type=Path, required=True, help="Source video.")
    p.add_argument("--out", type=Path, required=True, help="Output directory.")
    p.add_argument("--grid", type=_parse_grid, default=(4, 4), help="COLSxROWS, default 4x4.")
    p.add_argument("--overlap", type=float, default=0.25, help="Tile overlap fraction (default 0.25).")
    p.add_argument("--trim", type=float, default=None, help="Trim each tile clip to this many seconds.")
    p.add_argument("--env-file", type=Path, help="Env file with FAL_KEY and OPENAI_API_KEY.")
    p.add_argument("--vlm-concurrency", type=int, default=4, help="Parallel VLM calls.")
    p.add_argument("--foley-concurrency", type=int, default=4, help="Parallel fal Foley calls.")
    p.add_argument("--retry-flagged", type=Path, default=None,
                   help="Path to flagged.json (downloaded from review.html); only re-run tiles flagged 'bad'.")
    p.add_argument("--force-prompts", action="store_true", help="Re-run VLM prompts even if prompts.json exists.")
    p.add_argument("--force-foley", action="store_true", help="Re-run Foley calls even when audio file exists.")
    p.add_argument("--stop-after", choices=["tile", "prompts", "foley", "review", "page"], default="page",
                   help="Stop after the named stage.")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan everything; tile_video runs (cheap), VLM and Foley are stubbed.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    retry_ids = _load_flagged(args.retry_flagged) if args.retry_flagged else None

    print(f"[foley_map] step 1/5: tile_video", file=sys.stderr)
    tiles_manifest_path = step_tile(args, out)
    if args.stop_after == "tile":
        return 0
    manifest = json.loads(tiles_manifest_path.read_text(encoding="utf-8"))

    print(f"[foley_map] step 2/5: visual_understand (global + per-tile)", file=sys.stderr)
    prompts = step_prompts(args, out, manifest)
    if args.stop_after == "prompts":
        return 0

    print(f"[foley_map] step 3/5: fal_foley × {len(manifest['tiles'])}", file=sys.stderr)
    enriched = step_foley(args, out, manifest, prompts, retry_ids)
    if args.stop_after == "foley":
        # Still write the enriched manifest for resumption.
        (out / "tiles.json").write_text(json.dumps(enriched, indent=2) + "\n", encoding="utf-8")
        return 0

    print(f"[foley_map] step 4/5: foley_review", file=sys.stderr)
    review_path = step_review(out, enriched)
    print(f"open file://{review_path}")
    if args.stop_after == "review":
        return 0

    print(f"[foley_map] step 5/5: spatial_audio_page", file=sys.stderr)
    page_path = step_page(out)
    print(f"open file://{page_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
