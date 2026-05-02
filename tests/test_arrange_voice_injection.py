import unittest
from unittest import mock

from artagents.executors.arrange import run as arrange
from artagents import timeline


class StubClaudeClient:
    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "target_duration_sec": 80.0,
            "clips": [
                {
                    "order": 1,
                    "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 8.0]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": "Opening quote.",
                }
            ],
        }


def fixture_pool() -> dict:
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
                "src_end": 8.0,
                "duration": 8.0,
                "source_ids": {"segment_ids": [0], "scene_id": "scene_001"},
                "scores": {"quotability": 0.9},
                "excluded": False,
                "text": "Opening quote.",
            }
        ],
    }


class ArrangeVoiceInjectionTest(unittest.TestCase):
    def test_theme_voice_and_pacing_land_in_system_prompt(self) -> None:
        theme = {
            "id": "fixture",
            "visual": {},
            "voice": {
                "tone": "reverent and restrained",
                "lexicon_prefer": ["honor", "preserve"],
                "lexicon_avoid": ["epic", "viral"],
                "overlay_copy_style": "title-case, short noun phrases",
            },
            "pacing": {
                "default_clip_sec": 5.0,
                "cut_tempo": "calm",
            },
        }
        client = StubClaudeClient()

        with mock.patch("artagents.domains.hype.arrangement_rules.compile_arrangement_plan", return_value=[]):
            arrange.build_arrangement(
                fixture_pool(),
                "Use the first quote.",
                client=client,
                target_duration_sec=80.0,
                theme=theme,
            )

        system = client.calls[0]["system"]
        self.assertIn("reverent and restrained", system)
        self.assertIn("honor, preserve", system)
        self.assertIn("epic, viral", system)
        self.assertIn("title-case, short noun phrases", system)
        self.assertIn("5.0s", system)
        self.assertIn("calm", system)

    def test_partial_theme_skips_missing_lines(self) -> None:
        block = arrange._voice_prompt_block({"voice": {"tone": "quiet"}})

        self.assertIn("quiet", block)
        self.assertNotIn("- Prefer lexicon:", block)
        self.assertNotIn("- Avoid lexicon:", block)
        self.assertNotIn("- Overlay copy style:", block)
        self.assertNotIn("- Pacing hint:", block)
        self.assertNotRegex(block, r"-\\s*$")


if __name__ == "__main__":
    unittest.main()
