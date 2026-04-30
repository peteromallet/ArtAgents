import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import arrange
from artagents import timeline


class StubClaudeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class ArrangeReviseTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="arrange-revise-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def fixture_pool(self) -> dict:
        entries = []
        for index in range(1, 11):
            start = float((index - 1) * 10)
            entries.append(
                {
                    "id": f"pool_d_{index:04d}",
                    "kind": "source",
                    "category": "dialogue",
                    "asset": "main",
                    "src_start": start,
                    "src_end": start + 10.0,
                    "duration": 10.0,
                    "source_ids": {"segment_ids": [index], "scene_id": f"scene_{index:03d}"},
                    "scores": {"quotability": 0.8},
                    "excluded": False,
                    "text": f"Quote {index}",
                    "speaker": "Host",
                    "quote_kind": "body",
                }
            )
        entries.extend(
            [
                {
                    "id": "pool_v_0001",
                    "kind": "source",
                    "category": "visual",
                    "asset": "main",
                    "src_start": 0.0,
                    "src_end": 10.0,
                    "duration": 10.0,
                    "source_ids": {"scene_id": "scene_v001"},
                    "scores": {"triage": 0.7},
                    "excluded": False,
                    "subject": "speaker on stage",
                },
                {
                    "id": "pool_v_0002",
                    "kind": "source",
                    "category": "visual",
                    "asset": "broll",
                    "src_start": 0.0,
                    "src_end": 10.0,
                    "duration": 10.0,
                    "source_ids": {"scene_id": "scene_v002"},
                    "scores": {"triage": 0.9},
                    "excluded": False,
                    "subject": "audience reaction",
                },
            ]
        )
        return {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "ados",
            "entries": entries,
        }

    def prior_arrangement(self) -> dict:
        return {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Lead with urgency and keep the speaker flow clear.",
            "target_duration_sec": 80.0,
            "source_slug": "ados",
            "brief_slug": "brief",
            "pool_sha256": "pool",
            "brief_sha256": "brief",
            "clips": [
                {
                    "order": index,
                    "uuid": f"{index:08x}",
                    "audio_source": {"pool_id": f"pool_d_{index:04d}", "trim_sub_range": [float((index - 1) * 10), float((index - 1) * 10 + 8)]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": f"Beat {index}",
                }
                for index in range(1, 11)
            ],
        }

    def editor_notes(self) -> dict:
        return {
            "iteration": 1,
            "notes": [
                {
                    "clip_order": 1,
                    "clip_uuid": "00000001",
                    "observation": "Opening needs a stronger visual.",
                    "brief_impact": "Improves the hook.",
                    "action": "swap",
                    "action_detail": {"candidate_pool_id": "pool_v_0002", "role": "overlay", "reason": "Better hook."},
                    "priority": "high",
                    "candidate_pool_id": "pool_v_0002",
                }
            ],
            "verdict": "iterate",
            "ship_confidence": 0.4,
        }

    def revised_response(self) -> dict:
        clips = [dict(clip) for clip in self.prior_arrangement()["clips"]]
        clips[0] = {
            **clips[0],
            "visual_source": {"pool_id": "pool_v_0002", "role": "overlay"},
            "rationale": "Beat 1 with editor-requested audience reaction overlay.",
        }
        return {"target_duration_sec": 80.0, "clips": clips}

    def test_revise_smoke(self) -> None:
        tmp_dir = self.make_tempdir()
        pool = self.fixture_pool()
        client = StubClaudeClient(self.revised_response())

        revised = arrange.build_revised_arrangement(
            pool,
            self.prior_arrangement(),
            self.editor_notes(),
            client=client,
            model="claude-sonnet-4-6",
        )

        timeline.validate_arrangement(revised, arrange._eligible_pool_ids(pool))
        out_path = tmp_dir / "arrangement.json"
        timeline.save_arrangement(revised, out_path, arrange._eligible_pool_ids(pool))
        saved = timeline.load_arrangement(out_path, arrange._eligible_pool_ids(pool))
        self.assertEqual(saved["clips"][0]["visual_source"]["pool_id"], "pool_v_0002")
        self.assertEqual(client.calls[0]["response_schema"]["properties"]["target_duration_sec"]["minimum"], 76.0)
        self.assertEqual(client.calls[0]["response_schema"]["properties"]["target_duration_sec"]["maximum"], 84.0)

    def test_revise_preserves_uuids_across_reorder(self) -> None:
        pool = self.fixture_pool()
        prior = self.prior_arrangement()
        clips = [dict(clip) for clip in prior["clips"]]
        reordered = [
            {**clips[1], "order": 1},
            {**clips[0], "order": 2},
            {key: value for key, value in {**clips[2], "order": 3}.items() if key != "uuid"},
            *clips[3:],
        ]
        client = StubClaudeClient({"target_duration_sec": 80.0, "clips": reordered})

        revised = arrange.build_revised_arrangement(
            pool,
            prior,
            self.editor_notes(),
            client=client,
            model="claude-sonnet-4-6",
        )

        prior_uuids = {clip["uuid"] for clip in prior["clips"]}
        self.assertEqual(revised["clips"][0]["uuid"], "00000002")
        self.assertEqual(revised["clips"][1]["uuid"], "00000001")
        self.assertRegex(revised["clips"][2]["uuid"], r"^[0-9a-f]{8}$")
        self.assertNotIn(revised["clips"][2]["uuid"], prior_uuids)

    def test_revise_cli(self) -> None:
        tmp_dir = self.make_tempdir()
        pool = self.fixture_pool()
        prior = self.prior_arrangement()
        notes = self.editor_notes()
        pool_path = tmp_dir / "pool.json"
        brief_path = tmp_dir / "brief.txt"
        prior_path = tmp_dir / "prior.json"
        notes_path = tmp_dir / "editor_review.json"
        out_dir = tmp_dir / "out"
        timeline.save_pool(pool, pool_path)
        timeline.save_arrangement(prior, prior_path, arrange._eligible_pool_ids(pool))
        brief_path.write_text(prior["brief_text"], encoding="utf-8")
        notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
        client = StubClaudeClient(self.revised_response())

        with mock.patch.object(arrange, "build_claude_client", return_value=client):
            result = arrange.main(
                [
                    "--pool",
                    str(pool_path),
                    "--brief",
                    str(brief_path),
                    "--out",
                    str(out_dir),
                    "--revise",
                    "--from-arrangement",
                    str(prior_path),
                    "--editor-notes",
                    str(notes_path),
                ]
            )

        self.assertEqual(result, 0)
        saved = timeline.load_arrangement(out_dir / "arrangement.json", arrange._eligible_pool_ids(pool))
        self.assertEqual(saved["clips"][0]["visual_source"]["pool_id"], "pool_v_0002")

    def test_revise_flag_parity(self) -> None:
        with self.assertRaises(SystemExit):
            arrange.main(["--pool", "pool.json", "--brief", "brief.txt", "--out", "out", "--revise"])


if __name__ == "__main__":
    unittest.main()
