import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import arrange
from artagents import timeline


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


class ArrangeTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="arrange-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def fixture_pool(self) -> dict:
        return {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "ados",
            "entries": [
                {
                    "id": "pool_d_0001",
                    "kind": "source",
                    "category": "dialogue",
                    "asset": "main",
                    "src_start": 0.0,
                    "src_end": 1.6,
                    "duration": 1.6,
                    "source_ids": {"segment_ids": [0, 1], "scene_id": "scene_001"},
                    "scores": {"quotability": 0.9},
                    "excluded": False,
                    "text": "Open strong on the first quote.",
                    "speaker": "Host",
                    "quote_kind": "hook",
                },
                {
                    "id": "pool_v_0001",
                    "kind": "source",
                    "category": "visual",
                    "asset": "main",
                    "src_start": 0.0,
                    "src_end": 1.6,
                    "duration": 1.6,
                    "source_ids": {"scene_id": "scene_001"},
                    "scores": {"triage": 0.8, "deep": 0.6},
                    "excluded": False,
                    "subject": "speaker on stage",
                    "motion_tags": ["speaker"],
                    "mood_tags": ["focused"],
                    "camera": "medium",
                },
                {
                    "id": "pool_v_0002",
                    "kind": "source",
                    "category": "visual",
                    "asset": "broll",
                    "src_start": 1.6,
                    "src_end": 3.1,
                    "duration": 1.5,
                    "source_ids": {"scene_id": "scene_002"},
                    "scores": {"triage": 0.7, "deep": 0.8},
                    "excluded": False,
                    "subject": "audience reaction",
                    "motion_tags": ["crowd"],
                    "mood_tags": ["warm"],
                    "camera": "wide",
                },
                {
                    "id": "pool_v_9999",
                    "kind": "source",
                    "category": "visual",
                    "asset": "main",
                    "src_start": 9.0,
                    "src_end": 11.0,
                    "duration": 2.0,
                    "source_ids": {"scene_id": "scene_099"},
                    "scores": {"triage": 0.1},
                    "excluded": True,
                    "excluded_reason": "duration_out_of_window",
                    "subject": "do not use",
                },
            ],
        }

    def add_text_card_entry(self, pool: dict) -> None:
        pool["entries"].append(
            {
                "id": "pool_g_text_card",
                "kind": "generative",
                "category": "visual",
                "effect_id": "text-card",
                "param_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
                "defaults": {"align": "center"},
                "meta": {"whenToUse": "Use for quote cards."},
                "duration": None,
                "scores": {},
                "excluded": False,
            }
        )

    def test_payload_passes_validate_arrangement(self) -> None:
        pool = self.fixture_pool()
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_0002", "role": "overlay"},
                        "text_overlay": {"content": "ADOS 2026", "style_preset": "title"},
                        "rationale": "Open with the speaker, then cut wide.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with mock.patch("artagents.arrangement_rules.compile_arrangement_plan", return_value=[]):
            payload = arrange.build_arrangement(pool, "Open with the strongest quote.", client=client, target_duration_sec=80.0)

        timeline.validate_arrangement(payload, {"pool_d_0001", "pool_v_0001", "pool_v_0002"})
        self.assertEqual(payload["clips"][0]["visual_source"]["pool_id"], "pool_v_0002")
        self.assertEqual(payload["target_duration_sec"], 80.0)
        self.assertRegex(payload["clips"][0]["uuid"], r"^[0-9a-f]{8}$")

    def test_fresh_build_assigns_clip_uuid_when_llm_omits_it(self) -> None:
        pool = self.fixture_pool()
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_0002", "role": "overlay"},
                        "text_overlay": None,
                        "rationale": "Open strong.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with mock.patch("artagents.arrangement_rules.compile_arrangement_plan", return_value=[]):
            payload = arrange.build_arrangement(pool, "Open strong.", client=client, target_duration_sec=80.0)

        self.assertRegex(payload["clips"][0]["uuid"], r"^[0-9a-f]{8}$")

    def test_response_schema_has_no_forbidden_time_keys(self) -> None:
        self.assertFalse(has_forbidden_time_keys(arrange.RESPONSE_SCHEMA, arrange.FORBIDDEN_TIME_KEYS))

    def test_source_cut_arrange_hides_and_rejects_generative_entries_by_default(self) -> None:
        pool = self.fixture_pool()
        self.add_text_card_entry(pool)
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": None,
                        "visual_source": {
                            "pool_id": "pool_g_text_card",
                            "role": "stinger",
                            "params": {"content": "Generated title"},
                        },
                        "text_overlay": None,
                        "rationale": "Bad source-cut generative pick.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with self.assertRaises(ValueError):
            arrange.build_arrangement(pool, "Use source-cut output only.", client=client)

        system_prompt = client.calls[0]["system"]
        user_prompt = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("GENERATIVE:", system_prompt)
        self.assertNotIn("pool_g_text_card", system_prompt)
        self.assertIn("visual_source.pool_id must come from VISUAL source entries only", user_prompt)

    def test_generative_entries_are_allowed_only_when_explicitly_enabled(self) -> None:
        pool = self.fixture_pool()
        self.add_text_card_entry(pool)
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": None,
                        "visual_source": {
                            "pool_id": "pool_g_text_card",
                            "role": "stinger",
                            "params": {"content": "Generated title"},
                        },
                        "text_overlay": None,
                        "rationale": "Good pure-generative pick.",
                    }
                ],
                "target_duration_sec": 10.0,
            }
        )

        with mock.patch("artagents.arrangement_rules.compile_arrangement_plan", return_value=[]):
            payload = arrange.build_arrangement(
                pool,
                "Make a title card.",
                client=client,
                target_duration_sec=10.0,
                allow_generative_effects=True,
            )

        self.assertEqual(payload["clips"][0]["visual_source"]["pool_id"], "pool_g_text_card")
        self.assertIn("GENERATIVE:", client.calls[0]["system"])

    def test_no_audio_prompt_removes_dialogue_constraints(self) -> None:
        pool = self.fixture_pool()
        self.add_text_card_entry(pool)
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": None,
                        "visual_source": {
                            "pool_id": "pool_g_text_card",
                            "role": "primary",
                            "params": {"content": "Generated title"},
                        },
                        "text_overlay": None,
                        "rationale": "Good visual-only pick.",
                    }
                ],
                "target_duration_sec": 6.0,
            }
        )

        with mock.patch("artagents.arrangement_rules.compile_arrangement_plan", return_value=[]):
            payload = arrange.build_arrangement(
                pool,
                "Make a title card.",
                client=client,
                target_duration_sec=6.0,
                allow_generative_effects=True,
                no_audio=True,
            )

        user_prompt = client.calls[0]["messages"][0]["content"]
        self.assertEqual(payload["clips"][0]["audio_source"], None)
        self.assertIn("visual-only and no audio track will be rendered", user_prompt)
        self.assertIn("Every clip must set audio_source to null", user_prompt)
        self.assertIn("Every clip must use a generative visual_source", user_prompt)
        self.assertNotIn("anchored to the rant audio", user_prompt)
        self.assertNotIn("Every dialogue-driven clip", user_prompt)
        self.assertNotIn("audio_source may be null only for stinger beats", user_prompt)

    def test_no_audio_all_generative_can_be_below_source_window(self) -> None:
        pool = self.fixture_pool()
        self.add_text_card_entry(pool)
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": None,
                        "visual_source": {
                            "pool_id": "pool_g_text_card",
                            "role": "primary",
                            "params": {"content": "Short visual"},
                        },
                        "text_overlay": None,
                        "rationale": "A short visual-only beat.",
                    }
                ],
                "target_duration_sec": 6.0,
            }
        )

        payload = arrange.build_arrangement(
            pool,
            "Make a short visual.",
            client=client,
            target_duration_sec=6.0,
            allow_generative_effects=True,
            no_audio=True,
        )

        self.assertEqual(payload["target_duration_sec"], 6.0)
        self.assertTrue(timeline.is_all_generative_arrangement(payload, pool))

    def test_post_validation_rejects_unknown_pool_id(self) -> None:
        pool = self.fixture_pool()
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_4040", "role": "overlay"},
                        "text_overlay": None,
                        "rationale": "Bad visual.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with self.assertRaises(ValueError):
            arrange.build_arrangement(pool, "Keep it tight.", client=client)

    def test_post_validation_rejects_duplicate_and_negative_orders(self) -> None:
        pool = self.fixture_pool()
        duplicate_client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_0001", "role": "overlay"},
                        "text_overlay": None,
                        "rationale": "Duplicate.",
                    },
                    {
                        "order": 1,
                        "audio_source": None,
                        "visual_source": {"pool_id": "pool_v_0002", "role": "stinger"},
                        "text_overlay": None,
                        "rationale": "Duplicate.",
                    },
                ],
                "target_duration_sec": 80.0,
            }
        )
        negative_client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": -1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_0001", "role": "overlay"},
                        "text_overlay": None,
                        "rationale": "Negative.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with self.assertRaises(ValueError):
            arrange.build_arrangement(pool, "Duplicate order should fail.", client=duplicate_client)
        with self.assertRaises(ValueError):
            arrange.build_arrangement(pool, "Negative order should fail.", client=negative_client)

    def test_cli_fills_hash_envelope_from_file_bytes(self) -> None:
        tmp_dir = self.make_tempdir()
        pool = self.fixture_pool()
        pool_path = tmp_dir / "pool.json"
        brief_path = tmp_dir / "brief.txt"
        out_dir = tmp_dir / "out"
        timeline.save_pool(pool, pool_path)
        brief_path.write_text("Lead with the clearest quote.\nThen widen out.", encoding="utf-8")
        client = StubClaudeClient(
            {
                "clips": [
                    {
                        "order": 1,
                        "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 1.6]},
                        "visual_source": {"pool_id": "pool_v_0002", "role": "overlay"},
                        "text_overlay": {"content": "ADOS 2026", "style_preset": "title"},
                        "rationale": "Open strong.",
                    }
                ],
                "target_duration_sec": 80.0,
            }
        )

        with mock.patch.object(arrange, "build_claude_client", return_value=client), mock.patch(
            "artagents.arrangement_rules.compile_arrangement_plan", return_value=[]
        ):
            result = arrange.main(
                [
                    "--pool",
                    str(pool_path),
                    "--brief",
                    str(brief_path),
                    "--out",
                    str(out_dir),
                    "--source-slug",
                    "ados-full",
                    "--brief-slug",
                    "launch",
                ]
            )

        self.assertEqual(result, 0)
        saved = timeline.load_arrangement(out_dir / "arrangement.json", {"pool_d_0001", "pool_v_0001", "pool_v_0002"})
        self.assertEqual(saved["source_slug"], "ados-full")
        self.assertEqual(saved["brief_slug"], "launch")
        self.assertEqual(saved["pool_sha256"], hashlib.sha256(pool_path.read_bytes()).hexdigest())
        self.assertEqual(saved["brief_sha256"], hashlib.sha256(brief_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
