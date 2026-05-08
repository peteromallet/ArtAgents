import json
import shutil
import tempfile
from argparse import Namespace
from pathlib import Path

from astrid.packs.builtin.cut import run as cut
from astrid import timeline


def make_brief_case(testcase, *, quality_zones=None, refine_report=None):
    root = Path(tempfile.mkdtemp(prefix="inspect-cut-tests-"))
    testcase.addCleanup(shutil.rmtree, root, ignore_errors=True)
    pool_dir = root / "pool"
    brief_dir = pool_dir / "briefs" / "brief"
    pool_dir.mkdir(parents=True, exist_ok=True)
    brief_dir.mkdir(parents=True, exist_ok=True)

    media_path = pool_dir / "main.mp4"
    media_path.write_bytes(b"video")
    transcript_path = pool_dir / "transcript.json"
    scenes_path = pool_dir / "scenes.json"
    shots_path = pool_dir / "shots.json"
    quality_zones_path = pool_dir / "quality_zones.json"
    pool_path = pool_dir / "pool.json"
    arrangement_path = brief_dir / "arrangement.json"
    assets_path = brief_dir / "hype.assets.json"
    timeline_path = brief_dir / "hype.timeline.json"
    metadata_path = brief_dir / "hype.metadata.json"
    refine_path = brief_dir / "refine.json"

    transcript_segments = [
        {"start": 10.0, "end": 14.2, "text": "First clean quote."},
        {"start": 25.0, "end": 30.0, "text": "Second clean quote."},
    ]
    scenes = [
        {"index": 1, "start": 100.0, "end": 104.0, "duration": 4.0},
        {"index": 2, "start": 120.0, "end": 125.0, "duration": 5.0},
    ]
    entries = [
        {
            "id": "pool_v_stinger",
            "kind": "source",
                    "category": "visual",
            "asset": "main",
            "src_start": 0.0,
            "src_end": 4.0,
            "duration": 4.0,
            "source_ids": {"scene_id": "scene_stinger"},
            "scores": {"triage": 0.9, "deep": 0.9},
            "excluded": False,
            "subject": "title card",
        },
        {
            "id": "pool_d_0001",
            "kind": "source",
                    "category": "dialogue",
            "asset": "main",
            "src_start": 10.0,
            "src_end": 14.2,
            "duration": 4.2,
            "source_ids": {"segment_ids": [0]},
            "scores": {"quotability": 1.0},
            "excluded": False,
            "text": "First clean quote.",
            "speaker": "Host A",
            "quote_kind": "hook",
        },
        {
            "id": "pool_v_0001",
            "kind": "source",
                    "category": "visual",
            "asset": "main",
            "src_start": 100.0,
            "src_end": 104.0,
            "duration": 4.0,
            "source_ids": {"scene_id": "scene_1"},
            "scores": {"triage": 0.8, "deep": 0.9},
            "excluded": False,
            "subject": "speaker closeup",
        },
        {
            "id": "pool_d_0002",
            "kind": "source",
                    "category": "dialogue",
            "asset": "main",
            "src_start": 25.0,
            "src_end": 30.0,
            "duration": 5.0,
            "source_ids": {"segment_ids": [1]},
            "scores": {"quotability": 1.0},
            "excluded": False,
            "text": "Second clean quote.",
            "speaker": "Host A",
            "quote_kind": "support",
        },
        {
            "id": "pool_v_0002",
            "kind": "source",
                    "category": "visual",
            "asset": "main",
            "src_start": 120.0,
            "src_end": 125.0,
            "duration": 5.0,
            "source_ids": {"scene_id": "scene_2"},
            "scores": {"triage": 0.8, "deep": 0.9},
            "excluded": False,
            "subject": "audience reaction",
        },
    ]
    arrangement = {
        "version": timeline.ARRANGEMENT_VERSION,
        "generated_at": "2026-04-24T12:00:00Z",
        "brief_text": "fixture brief",
        "target_duration_sec": 75.0,
        "source_slug": "fixture",
        "brief_slug": "brief",
        "pool_sha256": "a" * 64,
        "brief_sha256": "b" * 64,
        "clips": [
            {
                "order": 1,
                "uuid": "00000001",
                "audio_source": None,
                "visual_source": {"pool_id": "pool_v_stinger", "role": "stinger"},
                "text_overlay": {"content": "OPEN", "style_preset": "bold-title"},
                "rationale": "Open on a title card.",
            },
            {
                "order": 2,
                "uuid": "00000002",
                "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [10.0, 14.2]},
                "visual_source": None,
                "rationale": "First dialogue beat.",
            },
            {
                "order": 3,
                "uuid": "00000003",
                "audio_source": {"pool_id": "pool_d_0002", "trim_sub_range": [25.0, 30.0]},
                "visual_source": None,
                "rationale": "Second dialogue beat.",
            },
        ],
    }
    for order in range(4, 11):
        src_start = 30.0 + ((order - 3) * 15.0)
        src_end = src_start + 8.5
        segment_index = len(transcript_segments)
        transcript_segments.append({"start": src_start, "end": src_end, "text": f"Filler quote {order}."})
        entries.append(
            {
                "id": f"pool_d_{order:04d}",
                "kind": "source",
                    "category": "dialogue",
                "asset": "main",
                "src_start": src_start,
                "src_end": src_end,
                "duration": 8.5,
                "source_ids": {"segment_ids": [segment_index]},
                "scores": {"quotability": 0.8},
                "excluded": False,
                "text": f"Filler quote {order}.",
                "speaker": f"Host {order}",
                "quote_kind": "support",
            }
        )
        arrangement["clips"].append(
            {
                "order": order,
                "uuid": f"{order:08x}",
                "audio_source": {"pool_id": f"pool_d_{order:04d}", "trim_sub_range": [src_start, src_end]},
                "visual_source": None,
                "rationale": f"Filler dialogue beat {order}.",
            }
        )
    registry = {
        "assets": {
            "main": {
                "file": str(media_path.resolve()),
                "type": "video",
                "duration": 300.0,
                "resolution": "1920x1080",
                "fps": 30.0,
            }
        }
    }

    transcript_path.write_text(json.dumps({"segments": transcript_segments}, indent=2) + "\n", encoding="utf-8")
    scenes_path.write_text(json.dumps(scenes, indent=2) + "\n", encoding="utf-8")
    shots_path.write_text("[]\n", encoding="utf-8")
    quality_zones_path.write_text(
        json.dumps(
            {
                "source_sha256": "d" * 64,
                "asset_key": "main",
                "zones": list(
                    quality_zones
                    or [
                        {"kind": "video_dead", "start": 10.5, "end": 11.5},
                        {"kind": "audio_dead", "start": 25.0, "end": 26.0},
                    ]
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    timeline.save_pool(
        {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-24T12:00:00Z",
            "source_slug": "fixture",
            "entries": entries,
        },
        pool_path,
    )
    timeline.save_arrangement(arrangement, arrangement_path, {entry["id"] for entry in entries})
    timeline.save_registry(registry, assets_path)

    args = Namespace(
        out=brief_dir,
        scenes=scenes_path,
        transcript=transcript_path,
        shots=shots_path,
        renderer="remotion",
        arrangement=arrangement_path,
    )
    pool = timeline.load_pool(pool_path)
    compiled_plan = cut.compile_arrangement_plan(arrangement, pool)
    timeline.save_timeline(
        cut.build_multitrack_timeline(arrangement, pool, registry, "main", compiled_plan=compiled_plan, theme_slug="banodoco-default"),
        timeline_path,
    )
    timeline.save_metadata(
        cut.build_metadata_from_arrangement(
            arrangement,
            pool,
            registry,
            {"main": {"codec": "h264"}},
            args,
            "main",
            transcript_segments,
            quality_zones_ref=quality_zones_path,
            pool_sha256="a" * 64,
            arrangement_sha256="c" * 64,
            brief_sha256="b" * 64,
            compiled_plan=compiled_plan,
        ),
        metadata_path,
    )
    refine_path.write_text(
        json.dumps(
            refine_report
            or {
                "iterations_run": 1,
                "converged": True,
                "auto_fixes": {
                    "audio_boundary": [
                        {
                            "order": 2,
                            "pool_id": "pool_d_0001",
                            "trim_before": [10.0, 14.0],
                            "trim_after": [10.0, 14.2],
                            "issues_resolved": ["mid_sentence_end"],
                            "similarity_before": 0.8,
                            "similarity_after": 1.0,
                            "source_transcript_text_before": "First clean quote",
                            "source_transcript_text_after": "First clean quote.",
                        }
                    ]
                },
                "flags": {
                    "visual_quality": [
                        {"order": 2, "code": "visual_dead_overlap", "message": "Visual trim overlaps a dead zone."}
                    ],
                    "speaker_flow": [
                        {
                            "order": 3,
                            "code": "speaker_repeat_without_break",
                            "message": "Adjacent dialogue clips repeat the same speaker without a break.",
                        }
                    ],
                    "overlay_fit": [],
                },
                "rejected_nudges": [],
                "per_clip": [
                    {
                        "order": 2,
                        "pool_id": "pool_d_0001",
                        "trim_before": [10.0, 14.0],
                        "trim_after": [10.0, 14.2],
                        "issues_resolved": ["mid_sentence_end"],
                        "similarity_before": 0.8,
                        "similarity_after": 1.0,
                        "source_transcript_text_before": "First clean quote",
                        "source_transcript_text_after": "First clean quote.",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "pool_dir": pool_dir,
        "run_dir": brief_dir,
        "pool_path": pool_path,
        "arrangement_path": arrangement_path,
        "timeline_path": timeline_path,
        "metadata_path": metadata_path,
        "assets_path": assets_path,
        "transcript_path": transcript_path,
        "quality_zones_path": quality_zones_path,
        "refine_path": refine_path,
    }
