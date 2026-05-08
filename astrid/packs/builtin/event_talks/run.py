from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from astrid.timeline import save_timeline


ADOS_SUNDAY_SPEAKERS = [
    {"speaker": "Enigmatic E", "title": "Creative Intent in an Automated World"},
    {"speaker": "Miki Durán", "title": "Creating with LTX Studio"},
    {"speaker": "Mohamed Oumoumad", "title": "IC LoRAs and the End of Impossible"},
    {"speaker": "VisualFrisson", "title": "Custom Pipelines: The Open Source Advantage"},
    {"speaker": "Yaron Inger", "title": "Your Model Now: LTX and the Builders Who Define It"},
    {"speaker": "Ziv Ilan", "title": "You Might Not Need 50 Diffusion Steps"},
    {"speaker": "Calvin Herbst", "title": "Creating New Aesthetics with Old Data"},
    {"speaker": "Matt Szymanowski", "title": "When AI Kills the Artist"},
    {"speaker": "Nekodificador", "title": "Embracing the Liquid Paradigm"},
    {"speaker": "Ingi Erlingsson", "title": "Remix Culture"},
]

ADOS_CARD_STYLE_VERSION = 6


@dataclass(frozen=True)
class Talk:
    slug: str
    speaker: str
    title: str
    source: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and render individual event talk videos from long recordings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule = subparsers.add_parser("ados-sunday-template", help="Write the ADOS Paris Sunday speaker template.")
    schedule.add_argument("--out", type=Path, required=True)

    search = subparsers.add_parser("search-transcript", help="Search a Whisper JSON transcript for speaker/title phrases.")
    search.add_argument("--transcript", type=Path, required=True)
    search.add_argument("--phrases", nargs="*", default=[])
    search.add_argument("--context", type=float, default=12.0)

    holding = subparsers.add_parser("find-holding-screens", help="Sample video frames and OCR likely wait/holding/title-card screens.")
    holding.add_argument("--video", type=Path, required=True)
    holding.add_argument("--out", type=Path, required=True)
    holding.add_argument("--sample-sec", type=float, default=10.0)
    holding.add_argument("--phrases", nargs="*", default=["LUNCH BREAK", "WE'LL BE BACK", "THANK YOU", "BREAK"])

    render = subparsers.add_parser("render", help="Render each manifest talk with ADOS intro, lower-third, and outro.")
    render.add_argument("--manifest", type=Path, required=True)
    render.add_argument("--out-dir", type=Path, required=True)
    render.add_argument(
        "--renderer",
        choices=["remotion-wrapper", "remotion", "ffmpeg-proof"],
        default="remotion-wrapper",
        help=(
            "Renderer to use. remotion-wrapper renders animated intro/outro cards through Remotion "
            "and uses ffmpeg for the long media pass; remotion renders the whole timeline through "
            "render_remotion.py; ffmpeg-proof is only for rough boundary checks."
        ),
    )
    render.add_argument("--logo", type=Path)
    render.add_argument("--sponsor", type=Path, action="append", default=[])
    render.add_argument("--character-sequence", type=str, help="Optional ffmpeg image2 pattern for a transparent PNG character animation, e.g. frames/%%03d.png.")
    render.add_argument("--width", type=int, default=1920)
    render.add_argument("--height", type=int, default=1080)
    render.add_argument("--fps", type=int, default=30)
    render.add_argument("--intro-sec", type=float, default=4.0)
    render.add_argument("--outro-sec", type=float, default=3.0)
    render.add_argument("--preset", default="veryfast")
    render.add_argument("--crf", type=float, default=18.0, help="x264 CRF for ffmpeg-based talk body renders. Higher is smaller/lower quality.")
    render.add_argument("--card-min-free-gb", type=float, default=1.0, help="Minimum free disk space required before rendering Remotion intro/outro cards.")
    render.add_argument("--force-card-render", action="store_true", help="Re-render Remotion intro/outro cards even if the cache key matches.")
    render.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "ados-sunday-template":
        return _write_ados_sunday_template(args.out)
    if args.command == "search-transcript":
        return _search_transcript(args.transcript, args.phrases, args.context)
    if args.command == "find-holding-screens":
        return _find_holding_screens(args)
    if args.command == "render":
        return _render_manifest(args)
    raise AssertionError(args.command)


def _write_ados_sunday_template(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": "ADOS Paris 2026",
        "day": "Sunday",
        "talks": [
            {
                "slug": _slugify(f"{entry['speaker']} {entry['title']}"),
                **entry,
                "source": "",
                "start": None,
                "end": None,
            }
            for entry in ADOS_SUNDAY_SPEAKERS
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote={path}")
    return 0


def _search_transcript(path: Path, phrases: list[str], context: float) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if not phrases:
        phrases = [entry["speaker"] for entry in ADOS_SUNDAY_SPEAKERS] + [entry["title"] for entry in ADOS_SUNDAY_SPEAKERS]
    compiled = [(phrase, re.compile(re.escape(_fold(phrase)), re.IGNORECASE)) for phrase in phrases]
    found = 0
    for segment in segments:
        text = str(segment.get("text") or "")
        folded = _fold(text)
        matches = [phrase for phrase, pattern in compiled if pattern.search(folded)]
        if matches:
            found += 1
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or start)
            print(f"{_fmt_time(start)}-{_fmt_time(end)} | {', '.join(matches)} | {text.strip()}")
            if context > 0:
                _print_context(segments, start, end, context)
    print(f"matches={found}")
    return 0


def _find_holding_screens(args: argparse.Namespace) -> int:
    _require_ffmpeg()
    if shutil.which("tesseract") is None:
        raise SystemExit("tesseract is required for find-holding-screens")
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"video not found: {video}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    work_dir = args.out.parent / f"{args.out.stem}.frames"
    work_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(video)
    phrases = [_fold(phrase) for phrase in args.phrases]
    hits: list[dict[str, Any]] = []
    t = 0.0
    while t <= duration:
        frame = work_dir / f"frame_{int(round(t)):06d}.jpg"
        if not frame.is_file():
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(frame)], check=True)
        text = subprocess.run(["tesseract", str(frame), "stdout", "--psm", "6"], check=False, capture_output=True, text=True).stdout.strip()
        folded = _fold(text)
        matched = [phrase for phrase in phrases if phrase in folded]
        if matched:
            hits.append({"time": round(t, 3), "timecode": _fmt_time(t), "matched": matched, "text": text, "frame": str(frame)})
        t += float(args.sample_sec)
    intervals = _coalesce_hit_intervals(hits, float(args.sample_sec))
    payload = {"video": str(video), "sample_sec": float(args.sample_sec), "phrases": args.phrases, "hits": hits, "intervals": intervals}
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote={args.out} hits={len(hits)} intervals={len(intervals)}")
    for interval in intervals:
        print(f"{interval['start_timecode']}-{interval['end_timecode']} {', '.join(interval['matched'])}")
    return 0


def _render_manifest(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    talks = [_talk_from_raw(raw) for raw in manifest.get("talks", []) if raw.get("start") is not None and raw.get("end") is not None]
    if not talks:
        raise SystemExit("manifest has no talks with start/end")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.renderer == "remotion-wrapper":
        return _render_manifest_remotion_wrapper(talks, args)
    if args.renderer == "remotion":
        return _render_manifest_remotion(talks, args)
    _require_ffmpeg()
    work_dir = args.out_dir / ".render-assets"
    work_dir.mkdir(parents=True, exist_ok=True)
    for talk in talks:
        output = args.out_dir / f"{talk.slug}.mp4"
        command = _render_command(talk, output, args, work_dir=work_dir)
        if args.dry_run:
            print(" ".join(command))
            continue
        print(f"rendering={output} source={talk.source} range={_fmt_time(talk.start)}-{_fmt_time(talk.end)}")
        subprocess.run(command, check=True)
    return 0


def _render_manifest_remotion_wrapper(talks: list[Talk], args: argparse.Namespace) -> int:
    from astrid.packs.builtin.render.run import render as render_remotion

    _require_ffmpeg()
    brand_assets = _remotion_brand_assets(args)
    for talk in talks:
        package_dir = args.out_dir / talk.slug
        package_dir.mkdir(parents=True, exist_ok=True)
        card_dir = package_dir / "remotion-cards"
        card_dir.mkdir(parents=True, exist_ok=True)
        intro_timeline, intro_assets = _remotion_card_package(talk, args, brand_assets=brand_assets, variant="intro")
        outro_timeline, outro_assets = _remotion_card_package(talk, args, brand_assets=brand_assets, variant="outro")
        intro_timeline_path = card_dir / "intro.timeline.json"
        intro_assets_path = card_dir / "intro.assets.json"
        outro_timeline_path = card_dir / "outro.timeline.json"
        outro_assets_path = card_dir / "outro.assets.json"
        save_timeline(intro_timeline, intro_timeline_path)
        intro_assets_path.write_text(json.dumps(intro_assets, indent=2) + "\n", encoding="utf-8")
        save_timeline(outro_timeline, outro_timeline_path)
        outro_assets_path.write_text(json.dumps(outro_assets, indent=2) + "\n", encoding="utf-8")
        intro_mp4 = card_dir / "intro.mp4"
        outro_mp4 = card_dir / "outro.mp4"
        output = args.out_dir / f"{talk.slug}.mp4"
        if args.dry_run:
            print(f"intro={intro_timeline_path} outro={outro_timeline_path} output={output}")
            continue
        _render_cached_card(
            variant="intro",
            talk=talk,
            args=args,
            timeline_path=intro_timeline_path,
            assets_path=intro_assets_path,
            output=intro_mp4,
            brand_assets=brand_assets,
            render_remotion=render_remotion,
        )
        _render_cached_card(
            variant="outro",
            talk=talk,
            args=args,
            timeline_path=outro_timeline_path,
            assets_path=outro_assets_path,
            output=outro_mp4,
            brand_assets=brand_assets,
            render_remotion=render_remotion,
        )
        print(f"rendering={output} source={talk.source} range={_fmt_time(talk.start)}-{_fmt_time(talk.end)} renderer=remotion-wrapper", flush=True)
        _render_wrapper_body(talk, args, intro_mp4=intro_mp4, outro_mp4=outro_mp4, output=output, brand_assets=brand_assets, package_dir=package_dir)
    return 0


def _render_cached_card(
    *,
    variant: str,
    talk: Talk,
    args: argparse.Namespace,
    timeline_path: Path,
    assets_path: Path,
    output: Path,
    brand_assets: dict[str, Path],
    render_remotion: Any,
) -> None:
    cache_path = output.with_suffix(output.suffix + ".cache.json")
    cache_key = _card_cache_key(variant=variant, talk=talk, args=args, brand_assets=brand_assets)
    if not args.force_card_render and output.is_file() and _cache_key_matches(cache_path, cache_key):
        print(f"cached-card={output} renderer=remotion", flush=True)
        return
    print(f"rendering-card={output} renderer=remotion", flush=True)
    render_remotion(timeline_path, assets_path, output, min_free_gb=float(args.card_min_free_gb))
    cache_path.write_text(json.dumps({"cache_key": cache_key}, indent=2) + "\n", encoding="utf-8")


def _cache_key_matches(path: Path, expected: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("cache_key") == expected


def _card_cache_key(
    *,
    variant: str,
    talk: Talk,
    args: argparse.Namespace,
    brand_assets: dict[str, Path],
) -> str:
    payload: dict[str, Any] = {
        "version": ADOS_CARD_STYLE_VERSION,
        "variant": variant,
        "speaker": talk.speaker,
        "title": talk.title,
        "width": int(args.width),
        "height": int(args.height),
        "fps": int(args.fps),
        "hold": float(args.intro_sec if variant == "intro" else args.outro_sec),
        "assets": {},
    }
    for key, path in sorted(brand_assets.items()):
        stat = path.stat()
        payload["assets"][key] = {
            "path": str(path.resolve()),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _remotion_card_package(
    talk: Talk,
    args: argparse.Namespace,
    *,
    brand_assets: dict[str, Path],
    variant: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    width = int(args.width)
    height = int(args.height)
    fps = int(args.fps)
    hold = float(args.intro_sec if variant == "intro" else args.outro_sec)
    sponsor_keys = [key for key in sorted(brand_assets) if key.startswith("sponsor_")]
    timeline_payload: dict[str, Any] = {
        "theme": "ados",
        "theme_overrides": {"visual": {"canvas": {"width": width, "height": height, "fps": fps}}},
        "output": {"resolution": f"{width}x{height}", "fps": float(fps), "file": f"{variant}.mp4", "background": "#0d0d10"},
        "tracks": [{"id": "overlay", "kind": "visual", "label": "ADOS Wrapper"}],
        "clips": [
            _ados_card_clip(
                variant,
                at=0,
                hold=hold,
                talk=talk,
                logo_key="ados_logo" if "ados_logo" in brand_assets else None,
                sponsor_keys=sponsor_keys,
                variant=variant,
            )
        ],
    }
    asset_payload = {
        "assets": {
            key: {
                "file": str(path.resolve()),
                "type": _asset_type(path),
            }
            for key, path in brand_assets.items()
        }
    }
    return timeline_payload, asset_payload


def _render_wrapper_body(
    talk: Talk,
    args: argparse.Namespace,
    *,
    intro_mp4: Path,
    outro_mp4: Path,
    output: Path,
    brand_assets: dict[str, Path],
    package_dir: Path,
) -> None:
    source = Path(talk.source).expanduser()
    if not source.is_file():
        raise SystemExit(f"source not found for {talk.slug}: {source}")
    width = int(args.width)
    height = int(args.height)
    fps = int(args.fps)
    intro_sec = float(args.intro_sec)
    outro_sec = float(args.outro_sec)
    body_sec = talk.duration
    body_fade_sec = min(1.0, max(0.0, body_sec / 2))
    body_fade_start = max(0.0, body_sec - body_fade_sec)
    intro_music_tail_sec = min(9.0, max(0.0, body_sec))
    intro_music_tail_fade_sec = min(3.0, intro_music_tail_sec)
    intro_music_tail_fade_start = max(0.0, intro_music_tail_sec - intro_music_tail_fade_sec)
    lower_file = _textfile(package_dir, "lower.txt", f"{talk.speaker.upper()} / {talk.title}")
    font = _font_path("PowerGrotesk-Regular.ttf") or _drawtext_font()
    base_text = f"fontfile='{font}':fontcolor=0xf7f7f7"
    graph_lines = [
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0d0d10,setsar=1,"
        f"drawbox=x=iw*0.48:y=ih-126:w=iw*0.50:h=78:color=0x0d0d10@0.72:t=fill,"
        f"drawbox=x=iw*0.48:y=ih-126:w=8:h=78:color=0x22f7d4@0.95:t=fill,"
        f"drawtext={base_text}:textfile='{lower_file}':fontsize=30:x=w-tw-70:y=h-97,"
        f"fade=t=out:st={body_fade_start:.3f}:d={body_fade_sec:.3f}:color=black[body_text]",
    ]
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(intro_mp4),
        "-ss",
        f"{talk.start:.6f}",
        "-t",
        f"{body_sec:.6f}",
        "-i",
        str(source),
    ]
    body_label = "body_text"
    next_input = 2
    music_input: int | None = None
    background_music = brand_assets.get("background_video")
    if background_music and background_music.is_file():
        command.extend(["-i", str(background_music)])
        music_input = next_input
        next_input += 1
    command.extend(["-i", str(outro_mp4)])
    outro_input = next_input
    audio_lines = [
        f"[0:a]atrim=duration={intro_sec},aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[intro_a]",
        f"[1:a]atrim=duration={body_sec},aresample=48000,aformat=channel_layouts=stereo,"
        f"afade=t=out:st={body_fade_start:.3f}:d={body_fade_sec:.3f},asetpts=PTS-STARTPTS[body_voice]",
    ]
    if music_input is not None and intro_music_tail_sec > 0:
        audio_lines.extend(
            [
                f"[{music_input}:a]atrim=start={intro_sec:.3f}:duration={intro_music_tail_sec:.3f},"
                f"aresample=48000,aformat=channel_layouts=stereo,volume=0.13,"
                f"afade=t=out:st={intro_music_tail_fade_start:.3f}:d={intro_music_tail_fade_sec:.3f},"
                "asetpts=PTS-STARTPTS[body_music]",
                "[body_voice][body_music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[body_a]",
            ]
        )
    else:
        audio_lines.append("[body_voice]anull[body_a]")
    audio_lines.extend(
        [
            f"[{outro_input}:a]atrim=duration={outro_sec},aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[outro_a]",
            "[intro_a][body_a][outro_a]concat=n=3:v=0:a=1[aout]",
        ]
    )
    graph_lines.extend(
        [
            f"[0:v]fps={fps},setsar=1[intro_v]",
            f"[{body_label}]fps={fps},setsar=1[body_v]",
            f"[{outro_input}:v]fps={fps},setsar=1[outro_v]",
            "[intro_v][body_v][outro_v]concat=n=3:v=1:a=0[vout]",
            *audio_lines,
        ]
    )
    graph_file = package_dir / "wrapper-filtergraph.txt"
    graph_file.write_text(";\n".join(graph_lines) + "\n", encoding="utf-8")
    command.extend(
        [
            "-filter_complex_script",
            str(graph_file),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            str(args.preset),
            "-crf",
            f"{float(args.crf):g}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    subprocess.run(command, check=True)


def _render_manifest_remotion(talks: list[Talk], args: argparse.Namespace) -> int:
    from astrid.packs.builtin.render.run import render as render_remotion

    assets = _remotion_brand_assets(args)
    for talk in talks:
        package_dir = args.out_dir / talk.slug
        package_dir.mkdir(parents=True, exist_ok=True)
        packaged_source = _extract_talk_source(talk, package_dir, dry_run=bool(args.dry_run))
        timeline_path = package_dir / "hype.timeline.json"
        assets_path = package_dir / "hype.assets.json"
        metadata_path = package_dir / "hype.metadata.json"
        output = args.out_dir / f"{talk.slug}.mp4"
        timeline_payload, asset_payload, metadata_payload = _remotion_package(
            talk,
            args,
            brand_assets=assets,
            packaged_source=packaged_source,
            output=output,
        )
        save_timeline(timeline_payload, timeline_path)
        assets_path.write_text(json.dumps(asset_payload, indent=2) + "\n", encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8")
        if args.dry_run:
            print(f"timeline={timeline_path} assets={assets_path} output={output}")
            continue
        print(f"rendering={output} source={talk.source} range={_fmt_time(talk.start)}-{_fmt_time(talk.end)} renderer=remotion", flush=True)
        render_remotion(timeline_path, assets_path, output, min_free_gb=_full_remotion_min_free_gb(talk))
    return 0


def _full_remotion_min_free_gb(talk: Talk) -> float:
    # Full-frame Remotion renders long videos through Chrome and can spool a lot
    # of frame data. Keep a conservative floor so failures happen before a
    # half-hour render reaches ENOSPC.
    return max(4.0, talk.duration / 60.0 * 0.8)


def _extract_talk_source(talk: Talk, package_dir: Path, *, dry_run: bool) -> Path:
    _require_ffmpeg()
    source = Path(talk.source).expanduser()
    if not source.is_file():
        raise SystemExit(f"source not found for {talk.slug}: {source}")
    output = package_dir / "source.mp4"
    if output.is_file():
        return output
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{talk.start:.6f}",
        "-t",
        f"{talk.duration:.6f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output),
    ]
    if dry_run:
        print(" ".join(command))
        return output
    subprocess.run(command, check=True)
    return output


def _remotion_brand_assets(args: argparse.Namespace) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    if args.logo:
        logo = Path(args.logo).expanduser()
        if not logo.is_file():
            raise SystemExit(f"logo not found: {logo}")
        assets["ados_logo"] = logo
    for index, item in enumerate(args.sponsor):
        sponsor = Path(item).expanduser()
        if not sponsor.is_file():
            raise SystemExit(f"sponsor asset not found: {sponsor}")
        assets[f"sponsor_{index}"] = sponsor
    font_dir = Path("/Users/peteromalley/Documents/banodoco-workspace/ados/public/fonts")
    for key, filename in {
        "font_body": "PowerGrotesk-Regular.ttf",
        "font_display": "Pilowlava.woff2",
        "font_title": "Tommy.ttf",
    }.items():
        path = font_dir / filename
        if path.is_file():
            assets[key] = path
    background_video = Path("/Users/peteromalley/Documents/banodoco-workspace/ados/public/events/paris-2026-720p.mp4")
    if not background_video.is_file():
        background_video = Path("/Users/peteromalley/Documents/banodoco-workspace/ados/public/videos/video-paris-new2.mp4")
    if background_video.is_file():
        assets["background_video"] = background_video
    return assets


def _remotion_package(
    talk: Talk,
    args: argparse.Namespace,
    *,
    brand_assets: dict[str, Path],
    packaged_source: Path,
    output: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_source = Path(talk.source).expanduser()
    source = packaged_source
    width = int(args.width)
    height = int(args.height)
    fps = int(args.fps)
    intro_sec = float(args.intro_sec)
    outro_sec = float(args.outro_sec)
    body_sec = talk.duration
    sponsor_keys = [key for key in sorted(brand_assets) if key.startswith("sponsor_")]
    timeline_payload: dict[str, Any] = {
        "theme": "ados",
        "theme_overrides": {
            "visual": {
                "canvas": {
                    "width": width,
                    "height": height,
                    "fps": fps,
                }
            }
        },
        "output": {
            "resolution": f"{width}x{height}",
            "fps": float(fps),
            "file": str(output),
            "background": "#0d0d10",
        },
        "tracks": [
            {"id": "v1", "kind": "visual", "label": "Video"},
            {"id": "overlay", "kind": "visual", "label": "ADOS Wrapper"},
        ],
        "clips": [
            _ados_card_clip(
                "intro",
                at=0,
                hold=intro_sec,
                talk=talk,
                logo_key="ados_logo" if "ados_logo" in brand_assets else None,
                sponsor_keys=sponsor_keys,
                variant="intro",
            ),
            {
                "id": "body",
                "at": intro_sec,
                "track": "v1",
                "clipType": "media",
                "asset": "source",
                "from": 0,
                "to": body_sec,
                "volume": 1.0,
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
            },
            {
                "id": "lower-third",
                "at": intro_sec,
                "track": "overlay",
                "clipType": "effect-layer",
                "hold": body_sec,
                "params": {
                    "kind": "ados-lower-third",
                    "speaker": talk.speaker,
                    "title": talk.title,
                },
            },
            _ados_card_clip(
                "outro",
                at=intro_sec + body_sec,
                hold=outro_sec,
                talk=talk,
                logo_key="ados_logo" if "ados_logo" in brand_assets else None,
                sponsor_keys=sponsor_keys,
                variant="outro",
            ),
        ],
    }
    asset_payload = {
        "assets": {
            "source": {
                "file": str(source.resolve()),
                "type": "video/mp4",
                "duration": _probe_duration(source),
                "resolution": f"{width}x{height}",
                "fps": float(fps),
            },
            **{
                key: {
                    "file": str(path.resolve()),
                    "type": _asset_type(path),
                }
                for key, path in brand_assets.items()
            },
        }
    }
    metadata_payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "pipeline": {
            "tool": "event_talks",
            "renderer": "remotion",
            "talk_slug": talk.slug,
            "source_start": talk.start,
            "source_end": talk.end,
            "source_packaged_from": str(original_source.resolve()),
        },
        "clips": {},
        "sources": {
            "source": {
                "file": str(source.resolve()),
                "original_file": str(original_source.resolve()),
            }
        },
    }
    return timeline_payload, asset_payload, metadata_payload


def _ados_card_clip(
    clip_id: str,
    *,
    at: float,
    hold: float,
    talk: Talk,
    logo_key: str | None,
    sponsor_keys: list[str],
    variant: str,
) -> dict[str, Any]:
    return {
        "id": clip_id,
        "at": at,
        "track": "overlay",
        "clipType": "effect-layer",
        "hold": hold,
        "params": {
            "kind": "ados-card",
            "variant": variant,
            "speaker": talk.speaker,
            "title": talk.title,
            "logoAsset": logo_key,
            "sponsorAssets": sponsor_keys,
            "bodyFontAsset": "font_body",
            "displayFontAsset": "font_display",
            "titleFontAsset": "font_title",
            "backgroundVideoAsset": "background_video",
        },
    }


def _asset_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".ttf":
        return "font/ttf"
    if suffix == ".woff2":
        return "font/woff2"
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def _render_command(talk: Talk, output: Path, args: argparse.Namespace, *, work_dir: Path) -> list[str]:
    source = Path(talk.source).expanduser()
    if not source.is_file():
        raise SystemExit(f"source not found for {talk.slug}: {source}")
    logo = Path(args.logo).expanduser() if args.logo else None
    if logo and not logo.is_file():
        raise SystemExit(f"logo not found: {logo}")
    sponsors = [Path(item).expanduser() for item in args.sponsor]
    missing = [str(item) for item in sponsors if not item.is_file()]
    if missing:
        raise SystemExit(f"sponsor asset not found: {missing[0]}")
    character_sequence = str(args.character_sequence) if args.character_sequence else None

    width = int(args.width)
    height = int(args.height)
    intro_sec = float(args.intro_sec)
    outro_sec = float(args.outro_sec)
    talk_dir = work_dir / talk.slug
    talk_dir.mkdir(parents=True, exist_ok=True)
    logo = _prepare_image_input(logo, talk_dir) if logo else None
    sponsors = [_prepare_image_input(sponsor, talk_dir) for sponsor in sponsors]
    title_file = _textfile(talk_dir, "title.txt", talk.title.upper())
    speaker_file = _textfile(talk_dir, "speaker.txt", talk.speaker.upper())
    lower_file = _textfile(talk_dir, "lower.txt", f"{talk.speaker.upper()} / {talk.title}")
    outro_file = _textfile(talk_dir, "outro.txt", "ADOS PARIS 2026")
    graph = _filter_graph(
        width=width,
        height=height,
        intro_sec=intro_sec,
        outro_sec=outro_sec,
        title_file=title_file,
        speaker_file=speaker_file,
        lower_file=lower_file,
        outro_file=outro_file,
        logo=logo,
        sponsors=sponsors,
        character_sequence=character_sequence,
        body_sec=talk.duration,
    )
    graph_file = talk_dir / "filtergraph.txt"
    graph_file.write_text(graph, encoding="utf-8")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss",
        f"{talk.start:.6f}",
        "-t",
        f"{talk.duration:.6f}",
        "-i",
        str(source),
    ]
    if logo:
        command.extend(["-loop", "1", "-t", f"{talk.duration + intro_sec + outro_sec:.3f}", "-i", str(logo)])
    for sponsor in sponsors:
        command.extend(["-loop", "1", "-t", f"{talk.duration + intro_sec + outro_sec:.3f}", "-i", str(sponsor)])
    if character_sequence:
        first_frame = Path(character_sequence.replace("%03d", "001")).expanduser()
        if not first_frame.is_file():
            raise SystemExit(f"character sequence first frame not found: {first_frame}")
        command.extend(["-stream_loop", "-1", "-framerate", str(args.fps), "-i", character_sequence])
    command.extend(
        [
            "-filter_complex_script",
            str(graph_file),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            str(args.preset),
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return command


def _filter_graph(
    *,
    width: int,
    height: int,
    intro_sec: float,
    outro_sec: float,
    title_file: Path,
    speaker_file: Path,
    lower_file: Path,
    outro_file: Path,
    logo: Path | None,
    sponsors: list[Path],
    character_sequence: str | None,
    body_sec: float,
) -> str:
    font = _font_path("PowerGrotesk-Regular.ttf") or _drawtext_font()
    display_font = _font_path("NeutralFace.ttf") or font
    ados_font = _font_path("Pilowlava.woff2") or display_font
    base_text = f"fontfile='{font}':fontcolor=0xf7f7f7"
    display_text = f"fontfile='{display_font}':fontcolor=0xf7f7f7"
    ados_text = f"fontfile='{ados_font}':fontcolor=0xf7f7f7"
    accent = "0x22f7d4"
    magenta = "0xe879f9"
    gold = "0xfbbf24"
    title_y = _drop_y("h-th-230", "-210", 0.9, 0.35)
    speaker_y = _drop_y("h-th-132", "-120", 0.78, 0.65)
    lines = [
        f"color=c=0x0d0d10:s={width}x{height}:r=30:d={intro_sec}[intro_base]",
        f"[intro_base]drawbox=x=0:y=0:w=iw:h=ih:color=0xf7f7f7@0.015:t=fill,"
        f"drawbox=x=120:y=170:w=6:h=650:color={accent}@0.95:t=fill,"
        f"drawbox=x=148:y=170:w=260:h=6:color={magenta}@0.8:t=fill,"
        f"drawbox=x=148:y=814:w=460:h=6:color={gold}@0.75:t=fill,"
        f"drawtext={ados_text}:text='ADOS':fontsize=164:x=160:y='{_drop_y('170', '-240', 0.9, 0.05)}',"
        f"drawtext={base_text}:fontcolor={accent}:text='PARIS 2026':fontsize=28:x=165:y=355,"
        f"drawtext={display_text}:textfile='{title_file}':fontsize=70:x=160:y='{title_y}',"
        f"drawtext={base_text}:fontcolor={accent}:textfile='{speaker_file}':fontsize=42:x=164:y='{speaker_y}',"
        f"drawtext={base_text}:fontcolor=0xf7f7f7@0.62:text='OPEN SOURCE AI ART WEEKEND':fontsize=25:x=165:y=h-88[intro_text]",
        f"color=c=0x0d0d10:s={width}x{height}:r=30:d={outro_sec}[outro_base]",
        f"[outro_base]drawbox=x=0:y=0:w=iw:h=ih:color=0xf7f7f7@0.015:t=fill,"
        f"drawbox=x=120:y=170:w=6:h=650:color={accent}@0.95:t=fill,"
        f"drawbox=x=148:y=170:w=260:h=6:color={magenta}@0.8:t=fill,"
        f"drawbox=x=148:y=814:w=460:h=6:color={gold}@0.75:t=fill,"
        f"drawtext={ados_text}:text='ADOS':fontsize=164:x=160:y=175,"
        f"drawtext={base_text}:fontcolor={accent}:text='PARIS 2026':fontsize=28:x=165:y=360,"
        f"drawtext={display_text}:text='THANK YOU':fontsize=92:x=160:y=610,"
        f"drawtext={base_text}:fontcolor=0xf7f7f7@0.72:textfile='{speaker_file}':fontsize=38:x=164:y=725,"
        f"drawtext={base_text}:fontcolor=0xf7f7f7@0.62:text='OPEN SOURCE AI ART WEEKEND':fontsize=25:x=165:y=h-88[outro_text]",
        f"[0:v]trim=duration={body_sec},setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0d0d10,setsar=1,"
        f"drawbox=x=iw*0.48:y=ih-126:w=iw*0.50:h=78:color=0x0d0d10@0.72:t=fill,"
        f"drawbox=x=iw*0.48:y=ih-126:w=8:h=78:color={accent}@0.95:t=fill,"
        f"drawtext={base_text}:textfile='{lower_file}':fontsize=30:x=w-tw-70:y=h-97,setpts=PTS-STARTPTS[body_text]",
        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={intro_sec}[aintro]",
        f"[0:a]atrim=duration={body_sec},aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[abody]",
        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={outro_sec}[aoutro]",
        "[aintro][abody][aoutro]concat=n=3:v=0:a=1[aout]",
    ]
    intro_label = "intro_text"
    body_label = "body_text"
    outro_label = "outro_text"
    next_input = 1
    if logo:
        logo_y = _drop_y("86", "-180", 0.75, 0.05)
        lines.extend(
            [
                f"[{next_input}:v]scale=128:-1,split=3[logo_intro][logo_body][logo_outro]",
                f"[{intro_label}][logo_intro]overlay=x=W-w-90:y='{logo_y}':shortest=1[intro_logo]",
                f"[{body_label}][logo_body]overlay=x=W-w-44:y=34:shortest=1[body_logo]",
                f"[{outro_label}][logo_outro]overlay=x=W-w-90:y=86:shortest=1[outro_logo]",
            ]
        )
        intro_label = "intro_logo"
        body_label = "body_logo"
        outro_label = "outro_logo"
        next_input += 1
    for index, _sponsor in enumerate(sponsors):
        label = f"sponsor{index}"
        intro_y = 245 + index * 185
        outro_y = 245 + index * 185
        sponsor_y = _drop_y(str(intro_y), "-180", 0.65, 0.2 + index * 0.18)
        lines.append(f"[{next_input}:v]scale=170:-1,split=2[{label}_intro][{label}_outro]")
        lines.append(f"[{intro_label}][{label}_intro]overlay=x=W-w-110:y='{sponsor_y}':shortest=1[intro_sponsor{index}]")
        intro_label = f"intro_sponsor{index}"
        lines.append(f"[{outro_label}][{label}_outro]overlay=x=W-w-110:y={outro_y}:shortest=1[outro_sponsor{index}]")
        outro_label = f"outro_sponsor{index}"
        next_input += 1
    if character_sequence:
        lines.extend(
            [
                f"[{next_input}:v]scale=420:-1,format=rgba,split=2[character_intro][character_outro]",
                f"[{intro_label}][character_intro]overlay=x=W-w-150:y=H-h-210:shortest=1[intro_character]",
                f"[{outro_label}][character_outro]overlay=x=130:y=H-h-120:shortest=1[outro_character]",
            ]
        )
        intro_label = "intro_character"
        outro_label = "outro_character"
        next_input += 1
    lines.append(f"[{intro_label}][{body_label}][{outro_label}]concat=n=3:v=1:a=0,fps=30,setpts=N/(30*TB)[vout]")
    return ";\n".join(lines) + "\n"


def _drop_y(final_y: str, start_y: str, settle_sec: float, delay_sec: float) -> str:
    """FFmpeg expression for a simple top-down intro drop animation."""
    return f"min({final_y}\\,{start_y}+(({final_y})-({start_y}))/{settle_sec}*(t-{delay_sec}))"


def _font_path(name: str) -> str | None:
    path = Path("/Users/peteromalley/Documents/banodoco-workspace/ados/public/fonts") / name
    return str(path) if path.is_file() else None


def _talk_from_raw(raw: dict[str, Any]) -> Talk:
    speaker = str(raw["speaker"])
    title = str(raw["title"])
    return Talk(
        slug=str(raw.get("slug") or _slugify(f"{speaker} {title}")),
        speaker=speaker,
        title=title,
        source=str(raw["source"]),
        start=float(raw["start"]),
        end=float(raw["end"]),
    )


def _print_context(segments: list[dict[str, Any]], start: float, end: float, radius: float) -> None:
    for segment in segments:
        seg_start = float(segment.get("start") or 0.0)
        seg_end = float(segment.get("end") or seg_start)
        if seg_end >= start - radius and seg_start <= end + radius:
            print(f"  {_fmt_time(seg_start)} {str(segment.get('text') or '').strip()}")


def _textfile(tmpdir: Path, name: str, value: str) -> Path:
    path = tmpdir / name
    path.write_text(value + "\n", encoding="utf-8")
    return path


def _prepare_image_input(path: Path, work_dir: Path) -> Path:
    if path.suffix.lower() != ".svg":
        return path
    converted = work_dir / f"{path.stem}.png"
    if converted.is_file() and converted.stat().st_mtime >= path.stat().st_mtime:
        return converted
    if converter := shutil.which("rsvg-convert"):
        with converted.open("wb") as handle:
            subprocess.run([converter, "-f", "png", str(path)], check=True, stdout=handle)
        return converted
    if converter := shutil.which("magick"):
        subprocess.run([converter, str(path), str(converted)], check=True)
        return converted
    raise SystemExit(f"SVG asset requires rsvg-convert or ImageMagick: {path}")


def _drawtext_font() -> str:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        if Path(path).is_file():
            return path
    return ""


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required")


def _probe_duration(media_path: Path) -> float:
    return float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def _coalesce_hit_intervals(hits: list[dict[str, Any]], sample_sec: float) -> list[dict[str, Any]]:
    if not hits:
        return []
    intervals: list[dict[str, Any]] = []
    current = {"start": float(hits[0]["time"]), "end": float(hits[0]["time"]) + sample_sec, "matched": set(hits[0]["matched"])}
    for hit in hits[1:]:
        hit_time = float(hit["time"])
        if hit_time <= float(current["end"]) + sample_sec * 1.5:
            current["end"] = hit_time + sample_sec
            current["matched"].update(hit["matched"])
            continue
        intervals.append(_serialize_interval(current))
        current = {"start": hit_time, "end": hit_time + sample_sec, "matched": set(hit["matched"])}
    intervals.append(_serialize_interval(current))
    return intervals


def _serialize_interval(interval: dict[str, Any]) -> dict[str, Any]:
    start = float(interval["start"])
    end = float(interval["end"])
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "start_timecode": _fmt_time(start),
        "end_timecode": _fmt_time(end),
        "matched": sorted(interval["matched"]),
    }


def _fold(value: str) -> str:
    return value.lower().replace("ú", "u").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o")


def _slugify(value: str) -> str:
    value = _fold(value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return re.sub(r"-{2,}", "-", value)[:96]


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    return f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
