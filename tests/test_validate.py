import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import validate


class ValidateNoAudioTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="validate-no-audio-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def test_no_audio_timeline_skips_transcribe(self) -> None:
        tmp = self.make_tempdir()
        video = tmp / "hype.mp4"
        timeline_path = tmp / "hype.timeline.json"
        metadata_path = tmp / "hype.metadata.json"
        out_path = tmp / "validation.json"
        video.write_bytes(b"fake mp4")
        timeline_path.write_text(
            json.dumps(
                {
                    "theme": "banodoco-default",
                    "tracks": [{"id": "v1", "kind": "visual", "label": "Speaker"}],
                    "clips": [{"id": "clip_g_1", "at": 0, "track": "v1", "clipType": "text-card", "hold": 4}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        metadata_path.write_text(json.dumps({"clips": {}}) + "\n", encoding="utf-8")

        argv = [
            "validate.py",
            "--video",
            str(video),
            "--timeline",
            str(timeline_path),
            "--metadata",
            str(metadata_path),
            "--out",
            str(out_path),
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            validate, "run_transcribe", side_effect=AssertionError("transcribe should not run")
        ):
            result = validate.main()

        self.assertEqual(result, 0)
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["summary"]["skipped_no_audio"])
        self.assertEqual(payload["summary"]["failures"], 0)
        self.assertEqual(payload["clips"], [])


if __name__ == "__main__":
    unittest.main()
