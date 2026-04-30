import tempfile
import unittest
from pathlib import Path

import quote_scout


def has_key_named_brief(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if "brief" in str(key).lower() or has_key_named_brief(child):
                return True
    elif isinstance(value, list):
        return any(has_key_named_brief(child) for child in value)
    return False


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


class QuoteScoutTest(unittest.TestCase):
    def test_payload_passes_validator(self) -> None:
        transcript = {"segments": [{"text": "hello", "speaker": "A"}, {"text": "world", "speaker": "A"}]}
        client = StubClaudeClient(
            {
                "candidates": [
                    {
                        "segment_ids": [0, 1],
                        "text": "hello world",
                        "speaker": "A",
                        "theme": "intro",
                        "power": 4,
                        "quote_kind": "hook",
                    }
                ]
            }
        )

        payload = quote_scout.build_quote_candidates(transcript, client=client)

        quote_scout.validate_quote_candidates(payload)
        self.assertEqual(payload["candidates"][0]["segment_ids"], [0, 1])

    def test_messages_omit_brief_keys(self) -> None:
        transcript = {"segments": [{"text": "hello", "speaker": None}]}
        client = StubClaudeClient(
            {
                "candidates": [
                    {
                        "segment_ids": [0],
                        "text": "hello",
                        "speaker": None,
                        "theme": "intro",
                        "power": 3,
                        "quote_kind": "hook",
                    }
                ]
            }
        )

        quote_scout.build_quote_candidates(transcript, client=client)

        self.assertFalse(has_key_named_brief(client.calls[0]["messages"]))

    def test_response_schema_has_no_forbidden_time_keys(self) -> None:
        self.assertFalse(has_forbidden_time_keys(quote_scout.RESPONSE_SCHEMA, {"start", "end", "timestamp", "seconds", "time", "src_start", "src_end", "from", "to", "at"}))

    def test_cli_rejects_unknown_brief_flag(self) -> None:
        parser = quote_scout.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--transcript", "x.json", "--out", "out", "--brief", "brief.txt"])


if __name__ == "__main__":
    unittest.main()
