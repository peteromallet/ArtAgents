"""Unit tests for tools/publish.py.

Coverage:
  (a) PAT/non-JWT rejection at startup;
  (b) HEAD-200 short-circuits the upload (idempotent skip);
  (c) HEAD-404 -> upload (the upload library is mocked);
  (d) HEAD-404 -> upload returns 409 (race) -> treated as success;
  (e) version-mismatch surfaced cleanly through the CLI return path.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artagents.packs.builtin.publish import run as publish  # noqa: E402  (path tweak above is intentional)


def _make_jwt(payload: dict) -> str:
    """Synthesize a JWT with header.payload.signature where signature is
    a fixed dummy. Only the payload is decoded by the CLI."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.signature"


class AssertSupabaseUserJWTTest(unittest.TestCase):
    def test_rejects_pat_shaped_token(self):
        with self.assertRaisesRegex(publish.PublishError, "JWT"):
            publish.assert_supabase_user_jwt("pat_abcdef1234567890")

    def test_rejects_random_string(self):
        with self.assertRaisesRegex(publish.PublishError, "JWT"):
            publish.assert_supabase_user_jwt("clearly-not-a-jwt-token")

    def test_rejects_jwt_without_sub(self):
        token = _make_jwt({"aud": "authenticated"})
        with self.assertRaisesRegex(publish.PublishError, "sub"):
            publish.assert_supabase_user_jwt(token)

    def test_rejects_jwt_without_authenticated_audience(self):
        token = _make_jwt({"sub": "user-123", "aud": "service_role"})
        with self.assertRaisesRegex(publish.PublishError, "authenticated"):
            publish.assert_supabase_user_jwt(token)

    def test_accepts_valid_user_jwt(self):
        token = _make_jwt({"sub": "user-abc", "aud": "authenticated"})
        self.assertEqual(publish.assert_supabase_user_jwt(token), "user-abc")

    def test_accepts_role_authenticated_jwt(self):
        # Some Supabase JWT shapes carry `role` instead of `aud`.
        token = _make_jwt({"sub": "user-xyz", "role": "authenticated"})
        self.assertEqual(publish.assert_supabase_user_jwt(token), "user-xyz")


class UploadAssetIdempotencyTest(unittest.TestCase):
    BASE_KWARGS = dict(
        supabase_url="https://example.supabase.co",
        user_token=_make_jwt({"sub": "u1", "aud": "authenticated"}),
        bucket="timeline-assets",
        key="u1/t1/sha.mp4",
    )

    def setUp(self):
        self.tmp_file = ROOT / "tests" / "fixtures" / "publish-tmp-asset.bin"
        self.tmp_file.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_file.write_bytes(b"placeholder-content")
        self.addCleanup(lambda: self.tmp_file.unlink(missing_ok=True))

    def _resp(self, status, body=b""):
        return publish.HttpResponse(status=status, headers={}, body=body)

    def test_head_200_skips_upload(self):
        with mock.patch.object(publish, "_request") as request:
            request.return_value = self._resp(200)
            outcome = publish.upload_asset(
                **self.BASE_KWARGS,
                file_path=self.tmp_file,
                content_type="video/mp4",
            )
            self.assertEqual(outcome, "skipped")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[0], "HEAD")

    def test_head_404_then_upload_201(self):
        with mock.patch.object(publish, "_request") as request:
            request.side_effect = [self._resp(404), self._resp(201)]
            outcome = publish.upload_asset(
                **self.BASE_KWARGS,
                file_path=self.tmp_file,
                content_type="video/mp4",
            )
            self.assertEqual(outcome, "uploaded")
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.args[0], "POST")
            # Confirm we never set upsert: true.
            headers = request.call_args.kwargs["headers"]
            self.assertEqual(headers.get("x-upsert"), "false")

    def test_head_404_then_upload_409_treated_as_success(self):
        with mock.patch.object(publish, "_request") as request:
            request.side_effect = [self._resp(404), self._resp(409, b"duplicate")]
            outcome = publish.upload_asset(
                **self.BASE_KWARGS,
                file_path=self.tmp_file,
                content_type="video/mp4",
            )
            self.assertEqual(outcome, "uploaded")

    def test_head_403_raises_actionable(self):
        with mock.patch.object(publish, "_request") as request:
            request.return_value = self._resp(403)
            with self.assertRaisesRegex(publish.PublishError, "owned by another user"):
                publish.upload_asset(
                    **self.BASE_KWARGS,
                    file_path=self.tmp_file,
                    content_type="video/mp4",
                )


class UploadAssetsAndRewriteTest(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = ROOT / "tests" / "fixtures" / "publish-rewrite"
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        self.local = self.fixture_dir / "local.mp4"
        self.local.write_bytes(b"local-bytes")
        self.addCleanup(lambda: self.local.unlink(missing_ok=True))

    def test_http_url_assets_pass_through_unchanged(self):
        registry = {
            "assets": {
                "remote": {"url": "https://cdn.example.com/clip.mp4", "duration": 10.0, "type": "video"},
            }
        }
        upload = mock.Mock()
        new_registry, summary = publish.upload_assets_and_rewrite(
            registry,
            supabase_url="https://x.supabase.co",
            user_token=_make_jwt({"sub": "u1", "aud": "authenticated"}),
            user_id="u1",
            timeline_id="t1",
            upload_fn=upload,
        )
        upload.assert_not_called()
        self.assertEqual(summary, {"remote": "url"})
        self.assertEqual(new_registry["assets"]["remote"]["url"], "https://cdn.example.com/clip.mp4")

    def test_local_file_gets_uploaded_and_rewritten_to_bucket_key(self):
        registry = {
            "assets": {
                "main": {
                    "file": str(self.local),
                    "duration": 4.2,
                    "type": "video",
                },
            }
        }
        upload = mock.Mock(return_value="uploaded")
        new_registry, summary = publish.upload_assets_and_rewrite(
            registry,
            supabase_url="https://x.supabase.co",
            user_token=_make_jwt({"sub": "u1", "aud": "authenticated"}),
            user_id="u1",
            timeline_id="t1",
            upload_fn=upload,
        )
        self.assertEqual(summary, {"main": "uploaded"})
        rewritten = new_registry["assets"]["main"]
        self.assertTrue(rewritten["file"].startswith("u1/t1/"))
        self.assertTrue(rewritten["file"].endswith(".mp4"))
        self.assertEqual(len(rewritten["content_sha256"]), 64)


class SurfaceResponseTest(unittest.TestCase):
    def test_409_surfaces_actionable_message_with_current_version(self):
        response = publish.HttpResponse(
            status=409,
            headers={},
            body=json.dumps({"ok": False, "error": "version_mismatch", "current_version": 7}).encode(),
        )
        with self.assertRaisesRegex(publish.PublishError, "version mismatch.*7"):
            publish._surface_response(response, expected_version=3)

    def test_404_surfaces_create_if_missing_hint(self):
        response = publish.HttpResponse(status=404, headers={}, body=b"")
        with self.assertRaisesRegex(publish.PublishError, "--create-if-missing"):
            publish._surface_response(response, expected_version=1)

    def test_200_returns_zero(self):
        response = publish.HttpResponse(
            status=200,
            headers={},
            body=json.dumps({"ok": True, "config_version": 2, "created": False}).encode(),
        )
        self.assertEqual(publish._surface_response(response, expected_version=1), 0)


class CLIStartupRejectionTest(unittest.TestCase):
    """End-to-end check: PAT in REIGH_USER_TOKEN should fail before any
    network call. Patches `publish._request` so the test fails loudly if a
    network call slips through."""

    def test_pat_short_circuits_before_any_network_call(self):
        with mock.patch.dict(os.environ, {
            "REIGH_USER_TOKEN": "pat_some_personal_access_token",
            "REIGH_SUPABASE_URL": "https://x.supabase.co",
        }, clear=False), mock.patch.object(publish, "_request") as request:
            rc = publish.main([
                "--project-id", "00000000-0000-0000-0000-000000000000",
                "--timeline-id", "11111111-1111-1111-1111-111111111111",
                "--timeline-file", "/nonexistent.json",
            ])
            self.assertEqual(rc, 1)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
