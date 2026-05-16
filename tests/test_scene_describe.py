import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astrid.packs.builtin.executors.scene_describe import run as scene_describe


def has_forbidden_time_keys(value, forbidden) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden or has_forbidden_time_keys(child, forbidden):
                return True
    elif isinstance(value, list):
        return any(has_forbidden_time_keys(child, forbidden) for child in value)
    return False


class StubGeminiClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def describe_video(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class SceneDescribeTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="scene-describe-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def test_build_scene_descriptions_passes_validator(self) -> None:
        tmp_dir = self.make_tempdir()
        video = tmp_dir / "main.mp4"
        video.write_bytes(b"video")
        scenes = [
            {"index": 1, "start": 0.0, "end": 2.0, "duration": 2.0},
            {"index": 2, "start": 2.0, "end": 5.5, "duration": 3.5},
        ]
        triage = {
            "version": 1,
            "generated_at": "2026-04-21T12:00:00Z",
            "entries": [
                {"scene_id": "scene_001", "triage_score": 4, "triage_tag": "speaker"},
                {"scene_id": "scene_002", "triage_score": 5, "triage_tag": "motion"},
            ],
        }
        client = StubGeminiClient(
            {
                "description": "speaker on stage",
                "mood": "energetic",
                "motion_level": "high",
                "speaker_visible": True,
                "dialogue_salient": True,
                "motion_tags": ["walk"],
                "mood_tags": ["bright"],
            }
        )

        def fake_extract(video, start, end, out):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"clip")
            return out

        with mock.patch.object(scene_describe, "extract_scene_clip", side_effect=fake_extract):
            payload = scene_describe.build_scene_descriptions(
                scenes,
                triage,
                video,
                client=client,
                top_n=1,
                out_dir=tmp_dir,
            )

        scene_describe.validate_scene_descriptions(payload)
        self.assertEqual(len(payload["entries"]), 1)
        self.assertFalse(has_forbidden_time_keys(scene_describe.RESPONSE_SCHEMA, scene_describe.FORBIDDEN_TIME_KEYS))

    def test_caching_skips_client_call_when_cache_and_entry_exist(self) -> None:
        tmp_dir = self.make_tempdir()
        video = tmp_dir / "main.mp4"
        video.write_bytes(b"video")
        cache_dir = tmp_dir / "_describe_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "scene_001.mp4").write_bytes(b"clip")
        existing = {
            "version": 1,
            "generated_at": "2026-04-21T12:00:00Z",
            "entries": [
                {
                    "scene_id": "scene_001",
                    "description": "cached",
                    "mood": "calm",
                    "motion_level": "low",
                    "speaker_visible": False,
                    "dialogue_salient": False,
                    "motion_tags": [],
                    "mood_tags": [],
                    "deep_score": 0.25,
                }
            ],
        }
        (tmp_dir / "scene_descriptions.json").write_text(json.dumps(existing), encoding="utf-8")
        scenes = [{"index": 1, "start": 0.0, "end": 2.0, "duration": 2.0}]
        triage = {
            "version": 1,
            "generated_at": "2026-04-21T12:00:00Z",
            "entries": [{"scene_id": "scene_001", "triage_score": 4, "triage_tag": "speaker"}],
        }
        client = StubGeminiClient({})

        payload = scene_describe.build_scene_descriptions(
            scenes,
            triage,
            video,
            client=client,
            top_n=1,
            out_dir=tmp_dir,
        )

        self.assertEqual(client.calls, [])
        self.assertEqual(payload["entries"][0]["description"], "cached")

    def test_response_schema_has_no_forbidden_time_keys(self) -> None:
        self.assertFalse(has_forbidden_time_keys(scene_describe.RESPONSE_SCHEMA, scene_describe.FORBIDDEN_TIME_KEYS))


if __name__ == "__main__":
    unittest.main()
