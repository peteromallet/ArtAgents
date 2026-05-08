import json
import shutil
import tempfile
import unittest
from pathlib import Path

from astrid.packs.builtin.triage import run as triage


def has_forbidden_time_keys(value, forbidden) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden or has_forbidden_time_keys(child, forbidden):
                return True
    elif isinstance(value, list):
        return any(has_forbidden_time_keys(child, forbidden) for child in value)
    return False


class StubClaudeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class TriageTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="triage-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def write_frame(self, path: Path) -> None:
        path.write_bytes(b"frame")

    def test_build_triage_passes_validator_and_schema_has_no_time_keys(self) -> None:
        tmp_dir = self.make_tempdir()
        frame = tmp_dir / "scene001_k1.jpg"
        self.write_frame(frame)
        scenes = [{"index": 1, "start": 0.0, "end": 1.0, "duration": 1.0}]
        shots = [{"scene_index": 1, "frames": [{"path": str(frame), "timestamp": 0.5}]}]
        client = StubClaudeClient({"entries": [{"scene_id": "scene_001", "triage_score": 4, "triage_tag": "speaker"}]})

        payload = triage.build_triage(scenes, shots, tmp_dir, client=client, grid_size=20)

        triage.validate_scene_triage(payload)
        self.assertEqual(payload["entries"][0]["scene_id"], "scene_001")
        self.assertFalse(has_forbidden_time_keys(client.calls[0]["response_schema"], triage.FORBIDDEN_TIME_KEYS))

    def test_hard_filter_skips_client_call(self) -> None:
        tmp_dir = self.make_tempdir()
        scenes = [{"index": 1, "start": 0.0, "end": 0.2, "duration": 0.2}]
        shots = [{"scene_index": 1, "frames": []}]
        client = StubClaudeClient({"entries": []})

        payload = triage.build_triage(scenes, shots, tmp_dir, client=client, grid_size=20)

        self.assertEqual(client.calls, [])
        self.assertEqual(payload["entries"], [{"scene_id": "scene_001", "triage_score": 0, "triage_tag": "hard_filtered"}])

    def test_stub_inspects_schema_dict_forbidden_keys(self) -> None:
        tmp_dir = self.make_tempdir()
        frame = tmp_dir / "scene001_k1.jpg"
        self.write_frame(frame)
        scenes = [{"index": 1, "start": 0.0, "end": 1.0, "duration": 1.0}]
        shots = [{"scene_index": 1, "frames": [{"path": str(frame), "timestamp": 0.5}]}]
        client = StubClaudeClient({"entries": [{"scene_id": "scene_001", "triage_score": 3, "triage_tag": "motion"}]})

        triage.build_triage(scenes, shots, tmp_dir, client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertFalse(has_forbidden_time_keys(client.calls[0]["response_schema"], triage.FORBIDDEN_TIME_KEYS))


if __name__ == "__main__":
    unittest.main()
