import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from astrid.domains.hype import enriched_arrangement
from astrid.packs.builtin.executors.quality_zones import run as quality_zones


class QualityZonesTest(unittest.TestCase):
    def test_parse_ffmpeg_ranges(self) -> None:
        audio = """
        [silencedetect @ 0x1] silence_start: 0.5
        [silencedetect @ 0x1] silence_end: 1.2 | silence_duration: 0.7
        [silencedetect @ 0x1] silence_start: 2.0
        [silencedetect @ 0x1] silence_end: 2.8 | silence_duration: 0.8
        """
        video = """
        [blackdetect @ 0x1] black_start:0.3 black_end:0.9 black_duration:0.6
        """
        audio_zones = quality_zones._parse_ranges(audio, enriched_arrangement.ZoneKind.AUDIO_DEAD)
        video_zones = quality_zones._parse_black_ranges(video)

        self.assertEqual([(zone.start, zone.end) for zone in audio_zones], [(0.5, 1.2), (2.0, 2.8)])
        self.assertEqual(video_zones[0].kind, enriched_arrangement.ZoneKind.VIDEO_DEAD)
        self.assertEqual((video_zones[0].start, video_zones[0].end), (0.3, 0.9))

    def test_load_cached_payload_and_main_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quality-zones-tests-") as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            out_path = tmp_path / "quality_zones.json"
            source_path.write_bytes(b"fixture-bytes")
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            cached = {
                "source_sha256": source_sha256,
                "asset_key": "main",
                "zones": [{"kind": "audio_dead", "start": 1.0, "end": 2.0}],
            }
            out_path.write_text(json.dumps(cached, indent=2) + "\n", encoding="utf-8")

            self.assertEqual(quality_zones._load_cached_payload(out_path, source_sha256), cached)
            with mock.patch("quality_zones.compute", side_effect=AssertionError("compute should not run on cache hit")):
                self.assertEqual(quality_zones.main([str(source_path), "--out", str(out_path)]), 0)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), cached)


if __name__ == "__main__":
    unittest.main()
