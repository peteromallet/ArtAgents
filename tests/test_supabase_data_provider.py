"""Unit tests for artagents.core.reigh.data_provider.SupabaseDataProvider."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from artagents.core.reigh import data_provider as dp_mod
from artagents.core.reigh import timeline_io as tio
from artagents.core.reigh.data_provider import SupabaseDataProvider
from artagents.core.reigh.errors import TimelineVersionConflictError
from artagents.core.reigh.supabase_client import SupabaseHTTPError
from artagents.core.reigh.timeline_io import save_timeline


def _canonical_timeline() -> dict[str, Any]:
    return {
        "theme": "banodoco-default",
        "clips": [
            {
                "id": "c1",
                "at": 0,
                "track": "main",
                "clipType": "text",
                "text": {"content": "hi"},
                "hold": 1.0,
            }
        ],
    }


class _FakeFetch:
    """Stand-in for reigh-data-fetch responses."""

    def __init__(self, versions: list[int]) -> None:
        self.versions = list(versions)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url, payload, *, auth, timeout):  # noqa: D401
        self.calls.append({"url": url, "payload": dict(payload or {}), "auth": auth})
        version = self.versions.pop(0) if self.versions else self.versions[-1] if self.versions else 0
        return {
            "timelines": [
                {
                    "id": payload["timeline_id"],
                    "config": _canonical_timeline(),
                    "config_version": version,
                }
            ]
        }


class LoadTimelineTest(unittest.TestCase):
    def test_returns_config_and_version_round_tripped(self) -> None:
        fake = _FakeFetch(versions=[7])
        with patch.object(dp_mod, "post_json", side_effect=fake):
            with patch.object(tio, "post_json", side_effect=fake):
                provider = SupabaseDataProvider(
                    supabase_url="https://example.supabase.co",
                    fetch_url="https://example.supabase.co/functions/v1/reigh-data-fetch",
                    pat="pat-token",
                )
                config, version = provider.load_timeline("proj-1", "tl-1")
        self.assertEqual(version, 7)
        # Round-trip through artagents.timeline preserves the canonical clip shape.
        self.assertEqual(config["clips"][0]["id"], "c1")
        self.assertEqual(fake.calls[0]["auth"], ("pat", "pat-token"))


class SaveTimelineTest(unittest.TestCase):
    def _make_fetch(self, versions: list[int]) -> _FakeFetch:
        return _FakeFetch(versions=versions)

    def test_rpc_called_with_exact_three_param_shape_via_service_role(self) -> None:
        fetch = self._make_fetch([0])
        rpc_calls: list[dict[str, Any]] = []

        def fake_rpc(name, params, *, supabase_url, auth, timeout):
            rpc_calls.append(
                {"name": name, "params": dict(params), "auth": auth, "supabase_url": supabase_url}
            )
            return {"config_version": 1}

        with patch.object(tio, "post_json", side_effect=fetch), patch.object(tio, "rpc", side_effect=fake_rpc):
            result = save_timeline(
                timeline_id="tl-1",
                project_id="proj-1",
                mutator=lambda config, _version: config,
                fetch_url="https://x/functions/v1/reigh-data-fetch",
                supabase_url="https://x",
                read_auth=("pat", "pat-token"),
                write_auth=("service_role", "srv-key"),
                expected_version=0,
            )
        self.assertEqual(result.new_version, 1)
        self.assertEqual(len(rpc_calls), 1)
        call = rpc_calls[0]
        self.assertEqual(call["name"], "update_timeline_config_versioned")
        self.assertEqual(set(call["params"].keys()), {"p_timeline_id", "p_expected_version", "p_config"})
        self.assertNotIn("project_id", call["params"])
        # Service-role on the worker path; explicitly never user_jwt.
        self.assertEqual(call["auth"][0], "service_role")
        self.assertNotEqual(call["auth"][0], "user_jwt")

    def test_version_mismatch_retries_then_exhausts_at_three(self) -> None:
        fetch = self._make_fetch([0, 0, 0])
        attempts = {"count": 0}

        def fake_rpc(name, params, *, supabase_url, auth, timeout):
            attempts["count"] += 1
            raise SupabaseHTTPError(
                "version_conflict", status=409, body="version_conflict expected_version mismatch"
            )

        with patch.object(tio, "post_json", side_effect=fetch), patch.object(tio, "rpc", side_effect=fake_rpc):
            with self.assertRaises(TimelineVersionConflictError):
                save_timeline(
                    timeline_id="tl-1",
                    project_id="proj-1",
                    mutator=lambda config, _version: config,
                    fetch_url="https://x/functions/v1/reigh-data-fetch",
                    supabase_url="https://x",
                    read_auth=("pat", "pat-token"),
                    write_auth=("service_role", "srv-key"),
                    expected_version=0,
                    retries=3,
                )
        self.assertEqual(attempts["count"], 3)

    def test_save_timeline_rejects_expected_version_none_unless_force(self) -> None:
        with self.assertRaises(ValueError):
            save_timeline(
                timeline_id="tl-1",
                project_id="proj-1",
                mutator=lambda c, v: c,
                fetch_url="https://x",
                supabase_url="https://x",
                read_auth=("pat", "t"),
                write_auth=("service_role", "k"),
                expected_version=None,
                force=False,
            )

        # force=True allows expected_version=None (logged WARNING).
        fetch = self._make_fetch([5])
        with patch.object(tio, "post_json", side_effect=fetch), patch.object(
            tio, "rpc", return_value={"config_version": 6}
        ):
            result = save_timeline(
                timeline_id="tl-1",
                project_id="proj-1",
                mutator=lambda c, v: c,
                fetch_url="https://x",
                supabase_url="https://x",
                read_auth=("pat", "t"),
                write_auth=("service_role", "k"),
                expected_version=None,
                force=True,
            )
        self.assertEqual(result.new_version, 6)


class UploadAssetTest(unittest.TestCase):
    def test_upload_asset_writes_to_timeline_assets_bucket_then_register_asset(self) -> None:
        provider = SupabaseDataProvider(
            supabase_url="https://example.supabase.co",
            fetch_url="https://example.supabase.co/functions/v1/reigh-data-fetch",
            pat="pat-token",
        )

        captured: dict[str, Any] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, *, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["data_len"] = len(request.data) if request.data else 0
            return FakeResponse()

        register_calls: list[dict[str, Any]] = []

        def fake_register(self, **kwargs):  # type: ignore[no-redef]
            register_calls.append(kwargs)
            return {"ok": True}

        with patch("urllib.request.urlopen", fake_urlopen), patch.object(
            SupabaseDataProvider, "register_asset", fake_register
        ), patch("time.time", return_value=1700000000.123):
            provider.upload_asset(
                project_id="proj-1",
                timeline_id="tl-1",
                user_id="user-1",
                asset_id="asset-a",
                filename="clip.mp4",
                data=b"data",
                content_type="video/mp4",
                auth=("pat", "pat-token"),
            )

        self.assertIn("/storage/v1/object/timeline-assets/", captured["url"])
        self.assertIn("user-1/tl-1/", captured["url"])
        self.assertIn("clip.mp4", captured["url"])
        # Epoch in ms (1700000000123)
        self.assertIn("1700000000123-", captured["url"])
        self.assertEqual(len(register_calls), 1)
        self.assertEqual(register_calls[0]["asset_id"], "asset-a")
        self.assertIn("timeline-assets/", register_calls[0]["entry"]["file"])


class DataProviderSurfaceTest(unittest.TestCase):
    def test_required_methods_present_and_forbidden_methods_absent(self) -> None:
        present = [m for m in dir(SupabaseDataProvider) if not m.startswith("_")]
        for required in (
            "load_timeline",
            "save_timeline",
            "load_asset_registry",
            "resolve_asset_url",
            "register_asset",
            "upload_asset",
            "load_checkpoints",
            "save_checkpoint",
            "load_waveform",
            "load_asset_profile",
        ):
            self.assertIn(required, present, f"missing {required}")
        for forbidden in ("save_waveform", "save_profile", "load_profile"):
            self.assertNotIn(forbidden, present, f"{forbidden} must not be present")


if __name__ == "__main__":
    unittest.main()
