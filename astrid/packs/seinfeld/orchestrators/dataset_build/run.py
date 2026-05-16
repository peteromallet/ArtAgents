#!/usr/bin/env python3
"""Seinfeld dataset_build orchestrator — bucket-fill loop.

Searches YouTube, downloads candidate videos, segments scenes, judges each
scene against the locked vocabulary, captions the accepted ones, and writes
a training manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Per-bucket search queries — multiple per bucket for variety.
BUCKET_QUERIES: dict[str, list[str]] = {
    "jerrys_apt": [
        "seinfeld jerry kramer apartment scene HD",
        "seinfeld jerry george apartment conversation",
        "seinfeld kramer enters jerry apartment",
        "seinfeld jerry apartment full scene",
        "seinfeld elaine in jerry's apartment",
    ],
    "monks_diner": [
        "seinfeld monks diner george elaine full scene",
        "seinfeld jerry george monks coffee shop",
        "seinfeld elaine monks diner scene",
        "seinfeld monks restaurant booth scene",
        "seinfeld kramer monks diner",
    ],
}

# Per-bucket query hints for the VLM judge.
BUCKET_DESCRIPTIONS = {
    "jerrys_apt": "Jerry's apartment = exposed brick, beige kitchen cabinets, kitchen island, big window in living room.",
    "monks_diner": "Monk's diner = restaurant booth with formica table and vinyl seats, diner counter visible behind, large hanging lamps.",
}


def _run(cmd: list[str], env: dict | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _pyenv_env() -> dict:
    return {**os.environ, "PYENV_VERSION": "3.11.11"}


def yt_search(query: str, n: int, log) -> list[dict]:
    env = _pyenv_env()
    proc = _run(
        ["yt-dlp", "--skip-download", "--flat-playlist",
         "--print", "%(id)s|%(title)s|%(duration)s",
         f"ytsearch{n}:{query}"],
        env=env,
    )
    out = []
    for line in proc.stdout.splitlines():
        if "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        vid, title, dur = parts
        try:
            dur_s = float(dur)
        except ValueError:
            dur_s = 0.0
        out.append({"id": vid, "title": title, "duration": dur_s,
                    "url": f"https://www.youtube.com/watch?v={vid}"})
    log(f"  search '{query}' → {len(out)} results")
    return out


def yt_download(url: str, out_no_ext: Path, log) -> Path | None:
    env = _pyenv_env()
    proc = _run([
        "python3", "-m", "astrid.packs.builtin.youtube_audio.run",
        "--url", url, "--mode", "video",
        "--out", str(out_no_ext),
    ], env=env, timeout=900)
    target = out_no_ext.with_suffix(".mp4")
    if proc.returncode != 0 or not target.exists():
        log(f"    download FAILED: {proc.stderr[-200:].strip()}")
        return None
    return target


def detect_scenes(video: Path, out_json: Path, log) -> list[dict]:
    env = _pyenv_env()
    proc = _run([
        "python3", "-m", "astrid.packs.builtin.scenes.run",
        "--video", str(video), "--out", str(out_json),
    ], env=env, timeout=600)
    if proc.returncode != 0 or not out_json.exists():
        log(f"    scenes FAILED: {proc.stderr[-200:].strip()}")
        return []
    scenes = json.loads(out_json.read_text())
    return scenes if isinstance(scenes, list) else []


def vlm_call(video: Path, at_s: float, query: str, schema_path: Path, mode: str, out_json: Path, log) -> dict | None:
    env = _pyenv_env()
    proc = _run([
        "python3", "-m", "astrid.packs.builtin.visual_understand.run",
        "--video", str(video), "--at", f"{at_s:.2f}",
        "--query", query,
        "--response-schema", str(schema_path),
        "--env-file", ".env.local",
        "--mode", mode,
        "--out", str(out_json),
    ], env=env, timeout=180)
    if proc.returncode != 0 or not out_json.exists():
        log(f"    VLM FAILED: {proc.stderr[-200:].strip()}")
        return None
    try:
        r = json.loads(out_json.read_text())["results"][0]
        if r["status"] != "ok":
            log(f"    VLM error: {r.get('error', '')[:200]}")
            return None
        return json.loads(r["answer"])
    except Exception as exc:
        log(f"    VLM parse error: {exc}")
        return None


def cut_clip(source: Path, start: float, end: float, out: Path, log) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start
    proc = _run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source),
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(out),
    ])
    if proc.returncode != 0 or not out.exists():
        log(f"    ffmpeg cut FAILED: {proc.stderr[-200:].strip()}")
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vocabulary", type=Path,
                   default=Path("astrid/packs/seinfeld/vocabulary.yaml"))
    p.add_argument("--schemas-dir", type=Path,
                   default=Path("astrid/packs/seinfeld/schemas"))
    p.add_argument("--target", type=int, default=15,
                   help="Target accepted clips per bucket.")
    p.add_argument("--buckets", nargs="+", default=["jerrys_apt", "monks_diner"],
                   help="Bucket ids to fill.")
    p.add_argument("--candidates-per-search", type=int, default=3,
                   help="YouTube results pulled per search query.")
    p.add_argument("--max-scenes-per-video", type=int, default=10,
                   help="Cap per-video scene judgements (longest scenes first).")
    p.add_argument("--min-scene-s", type=float, default=2.5)
    p.add_argument("--max-scene-s", type=float, default=15.0)
    p.add_argument("--judge-mode", default="fast")
    p.add_argument("--caption-mode", default="best")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    log_path = out / "build.log"

    state: dict[str, Any]
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {
            "buckets": {b: {"accepted": 0, "clips": []} for b in args.buckets},
            "processed_video_ids": [],
            "started_at": time.time(),
        }
    for b in args.buckets:
        state["buckets"].setdefault(b, {"accepted": 0, "clips": []})

    def save_state():
        state_path.write_text(json.dumps(state, indent=2))

    def log(msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with log_path.open("a") as f:
            f.write(line + "\n")

    if args.dry_run:
        log("DRY RUN — would search and process candidates per bucket:")
        for b in args.buckets:
            log(f"  {b}: target={args.target}, queries={BUCKET_QUERIES.get(b, [])}")
        return 0

    judge_schema = args.schemas_dir / "bucket_judge.json"
    caption_schema = args.schemas_dir / "caption.json"
    for p in (judge_schema, caption_schema):
        if not p.is_file():
            log(f"FATAL: missing schema {p}")
            return 2

    candidates_root = out / "candidates"
    candidates_root.mkdir(exist_ok=True)
    accepted_root = out / "accepted"
    accepted_root.mkdir(exist_ok=True)

    # Build the candidate URL queue (deduped, shuffled across buckets).
    queue: list[tuple[str, dict]] = []  # (bucket, candidate)
    for bucket in args.buckets:
        if state["buckets"][bucket]["accepted"] >= args.target:
            log(f"bucket {bucket} already at target")
            continue
        for query in BUCKET_QUERIES.get(bucket, []):
            for cand in yt_search(query, args.candidates_per_search, log):
                if cand["id"] in state["processed_video_ids"]:
                    continue
                queue.append((bucket, cand))
    # Deduplicate by video id while preserving bucket-of-first-see.
    seen_ids: set[str] = set()
    deduped: list[tuple[str, dict]] = []
    for bucket, cand in queue:
        if cand["id"] in seen_ids:
            continue
        seen_ids.add(cand["id"])
        deduped.append((bucket, cand))
    random.seed(42)
    random.shuffle(deduped)
    log(f"queue: {len(deduped)} unique candidate videos across {len(args.buckets)} buckets")

    for bucket, cand in deduped:
        if all(state["buckets"][b]["accepted"] >= args.target for b in args.buckets):
            log("all buckets full — stopping")
            break
        if state["buckets"][bucket]["accepted"] >= args.target and not any(
            state["buckets"][b]["accepted"] < args.target for b in args.buckets
        ):
            continue

        vid = cand["id"]
        log(f"=== video {vid} ({cand['duration']:.0f}s) primary_bucket={bucket} ===")
        log(f"    title: {cand['title']!r}")
        if cand["duration"] > 0 and cand["duration"] > 1800:
            log("    skip: > 30 min (likely compilation, too expensive)")
            state["processed_video_ids"].append(vid)
            save_state()
            continue
        vid_dir = candidates_root / vid
        vid_dir.mkdir(exist_ok=True)
        video_path = yt_download(cand["url"], vid_dir / "source", log)
        if video_path is None:
            state["processed_video_ids"].append(vid)
            save_state()
            continue

        scenes_path = vid_dir / "scenes.json"
        scenes = detect_scenes(video_path, scenes_path, log)
        log(f"    {len(scenes)} scenes detected")

        usable = [s for s in scenes if args.min_scene_s <= s["duration"] <= args.max_scene_s]
        usable.sort(key=lambda s: -s["duration"])
        usable = usable[: args.max_scenes_per_video]
        log(f"    {len(usable)} usable scenes after duration filter")

        for scene in usable:
            # Only judge if any bucket still has room.
            if all(state["buckets"][b]["accepted"] >= args.target for b in args.buckets):
                break

            mid = (scene["start"] + scene["end"]) / 2
            sidx = scene["index"]
            judge_out = vid_dir / f"scene-{sidx:02d}.judge.json"
            descriptions = "; ".join(f"{k}: {v}" for k, v in BUCKET_DESCRIPTIONS.items())
            judge_query = (
                f"Classify this Seinfeld frame strictly per the schema. "
                f"Bucket descriptions: {descriptions}. "
                "Characters: Jerry mid-30s short dark hair; George short stocky balding glasses; "
                "Elaine curly dark hair; Kramer tall lanky wild hair. Be conservative — "
                "if uncertain, set accept=false and bucket=null. "
                "Reject talking-head, title cards, credits, ad cards, or non-show footage."
            )
            j = vlm_call(video_path, mid, judge_query, judge_schema, args.judge_mode, judge_out, log)
            if j is None:
                continue
            log(f"    scene {sidx} ({scene['duration']:.1f}s @ {mid:.1f}s): "
                f"accept={j['accept']} bucket={j['bucket']} chars={j['characters_visible']} "
                f"conf={j['confidence']:.2f}")

            if not j["accept"]:
                continue
            target_bucket = j["bucket"]
            if target_bucket not in args.buckets:
                continue
            if state["buckets"][target_bucket]["accepted"] >= args.target:
                log(f"    bucket {target_bucket} already full — skipping")
                continue

            # Cut clip
            clip_id = f"{vid}-s{sidx:02d}"
            clip_path = accepted_root / target_bucket / f"{clip_id}.mp4"
            if not cut_clip(video_path, scene["start"], scene["end"], clip_path, log):
                continue

            # Caption (best mode — accepted only)
            caption_out = accepted_root / target_bucket / f"{clip_id}.caption.json"
            caption_query = (
                f"Caption this Seinfeld clip frame for the locked-template schema. "
                f"Scene is {target_bucket}. Pick characters from those visible and the closest outfit "
                f"token for each. Don't invent new tokens. Assemble the final caption string per template."
            )
            cap = vlm_call(video_path, mid, caption_query, caption_schema, args.caption_mode, caption_out, log)
            if cap is None:
                clip_path.unlink(missing_ok=True)
                continue
            log(f"    CAPTION: {cap['caption']}")

            state["buckets"][target_bucket]["accepted"] += 1
            state["buckets"][target_bucket]["clips"].append({
                "clip_id": clip_id,
                "video_id": vid,
                "scene_index": sidx,
                "source_url": cand["url"],
                "start_s": scene["start"],
                "end_s": scene["end"],
                "duration_s": scene["duration"],
                "clip_file": str(clip_path),
                "caption_file": str(caption_out),
                "caption": cap["caption"],
                "judge_confidence": j["confidence"],
            })
            save_state()
            log(f"    --> bucket {target_bucket} now {state['buckets'][target_bucket]['accepted']}/{args.target}")

        state["processed_video_ids"].append(vid)
        save_state()
        log(f"  progress: " + " | ".join(
            f"{b}={state['buckets'][b]['accepted']}/{args.target}" for b in args.buckets
        ))

    # Write manifest.
    manifest = {
        "vocabulary": str(args.vocabulary),
        "buckets": {b: state["buckets"][b]["clips"] for b in args.buckets},
        "stats": {b: state["buckets"][b]["accepted"] for b in args.buckets},
        "completed_at": time.time(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"\nDONE. manifest at {out / 'manifest.json'}")
    log(f"final: " + " | ".join(
        f"{b}={state['buckets'][b]['accepted']}/{args.target}" for b in args.buckets
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
