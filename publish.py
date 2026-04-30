#!/usr/bin/env python3
"""Publish a Banodoco-authored timeline into a Reigh project.

Sprint 6 (Phase 6): hashes-and-uploads each non-HTTP asset to the
`timeline-assets` Supabase Storage bucket under
`<user_id>/<timeline_id>/<sha256>.<ext>`, rewrites the asset registry to
those bucket keys, and POSTs `{timeline, asset_registry, ...}` to the
`timeline-import` edge function.

Auth (SD-018 / SD-022): only Supabase user JWTs are accepted as
``REIGH_USER_TOKEN``. PATs are rejected at startup with an actionable
error pointing to the future edge-mediated upload path. The user JWT
is forwarded to (a) the storage REST API for HEAD+upload (so RLS at
``20260325090001_create_timeline_assets_bucket.sql:15-35`` keys on the
caller's ``auth.uid()``) and (b) the edge function for ownership
verification.

Idempotency (SD-011):
- HEAD the storage key first; on 200 skip upload.
- On 404 ``upload(key, file, {upsert: false})`` against the storage REST API.
- On 409/duplicate-object treat as success (sha256 collision == identical
  bytes by definition).
- ``upsert: true`` is never used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import timeline


TIMELINE_ASSETS_BUCKET = "timeline-assets"
DEFAULT_TIMEOUT = 60.0


class PublishError(RuntimeError):
    """Surface-level publish failures with actionable messages."""


# ---------------------------------------------------------------------------
# JWT / PAT detection
# ---------------------------------------------------------------------------


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Best-effort decode of the JWT payload without verifying the signature.

    Returns the payload dict on success, ``None`` on any malformed input. The
    actual signature/audience verification happens server-side at
    `authenticateRequest()` (Supabase admin client `auth.getUser()`); this
    helper exists only to (a) detect obvious PATs at the CLI surface so we
    fail fast with a useful error and (b) extract `sub` for the storage path.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    # JWT base64url uses no padding; pad before decoding.
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def assert_supabase_user_jwt(token: str) -> str:
    """Validate that ``token`` is a Supabase user JWT and return ``sub``.

    PATs (and other non-JWT tokens) are rejected because (a) Supabase Storage
    RLS at `20260325090001_create_timeline_assets_bucket.sql:15-35` keys on
    `auth.uid()`, which a PAT cannot satisfy, and (b) the edge function path
    does not currently bridge PATs to a Supabase auth identity.
    """
    payload = _decode_jwt_payload(token)
    if payload is None:
        raise PublishError(
            "REIGH_USER_TOKEN does not look like a JWT (3 base64url-encoded "
            "segments separated by dots). PATs are not accepted on this "
            "publish path because Supabase Storage RLS keys on auth.uid(). "
            "Use a Supabase user JWT (e.g. from a signed-in browser session). "
            "Future enhancement (SD-022): edge-mediated upload path for PATs."
        )
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise PublishError(
            "REIGH_USER_TOKEN payload is missing the `sub` claim "
            "(authenticated user id). PATs and service-role tokens are not "
            "accepted on this path; supply a Supabase user JWT."
        )
    aud = payload.get("aud")
    role = payload.get("role")
    aud_ok = (
        aud == "authenticated"
        or (isinstance(aud, list) and "authenticated" in aud)
        or role == "authenticated"
    )
    if not aud_ok:
        raise PublishError(
            "REIGH_USER_TOKEN is a JWT but its `aud`/`role` does not include "
            "`authenticated`. Service-role JWTs and other elevated tokens "
            "are not accepted on this path."
        )
    return sub


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def text(self) -> str:
        try:
            return self.body.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    def json(self) -> Any:
        try:
            return json.loads(self.text())
        except json.JSONDecodeError:
            return None


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpResponse:
    request = urllib.request.Request(url, method=method, data=data)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return HttpResponse(
                status=resp.status,
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=resp.read(),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return HttpResponse(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=body,
        )


# ---------------------------------------------------------------------------
# Asset upload
# ---------------------------------------------------------------------------


_EXT_OVERRIDES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ext_for(path: Path, content_type: str | None) -> str:
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    if content_type and content_type in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[content_type]
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed
    return ".bin"


def _storage_url(supabase_url: str, bucket: str, key: str) -> str:
    return f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{urllib.parse.quote(key, safe='/')}"


def upload_asset(
    *,
    supabase_url: str,
    user_token: str,
    bucket: str,
    key: str,
    file_path: Path,
    content_type: str | None,
) -> str:
    """HEAD-then-upload one asset. Returns ``"skipped"`` or ``"uploaded"``.

    Raises :class:`PublishError` on 4xx/5xx the policy doesn't tolerate.
    """
    url = _storage_url(supabase_url, bucket, key)
    auth_header = {"Authorization": f"Bearer {user_token}"}

    head = _request("HEAD", url, headers=auth_header)
    if head.status == 200:
        return "skipped"
    if head.status == 403:
        raise PublishError(
            f"asset is owned by another user; cannot publish (HEAD {url} -> 403). "
            "A future enhancement may add `--force-reupload-as-mine` to address this."
        )
    if head.status not in (404, 400):
        raise PublishError(
            f"unexpected HEAD status {head.status} for {url}: {head.text()[:200]}"
        )

    payload = file_path.read_bytes()
    upload_headers = {
        **auth_header,
        "x-upsert": "false",
        "Content-Type": content_type or "application/octet-stream",
    }
    upload = _request("POST", url, headers=upload_headers, data=payload)
    if upload.status in (200, 201):
        return "uploaded"
    if upload.status == 409:
        # Duplicate object — sha256 collision means identical bytes.
        return "uploaded"
    if upload.status == 403:
        raise PublishError(
            f"upload to {url} forbidden (403). Storage RLS expects the first "
            "path segment to equal the caller's auth.uid(); confirm the JWT "
            "matches the timeline owner."
        )
    raise PublishError(
        f"upload to {url} failed with status {upload.status}: {upload.text()[:200]}"
    )


# ---------------------------------------------------------------------------
# Timeline + registry rewriting
# ---------------------------------------------------------------------------


def is_http_url(value: Any) -> bool:
    return isinstance(value, str) and (value.startswith("http://") or value.startswith("https://"))


def _content_sha256_from_entry(entry: dict[str, Any], local_path: Path) -> str:
    sha = entry.get("content_sha256")
    if isinstance(sha, str) and len(sha) == 64:
        return sha
    return _sha256_file(local_path)


def _local_path_for_entry(entry: dict[str, Any]) -> Path | None:
    file_value = entry.get("file")
    if not isinstance(file_value, str) or not file_value:
        return None
    if is_http_url(file_value):
        return None
    return Path(file_value).expanduser()


def upload_assets_and_rewrite(
    registry: dict[str, Any],
    *,
    supabase_url: str,
    user_token: str,
    user_id: str,
    timeline_id: str,
    bucket: str = TIMELINE_ASSETS_BUCKET,
    upload_fn: Any = upload_asset,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Walk the asset registry, upload non-HTTP entries, return rewritten copy.

    Returns ``(new_registry, summary)`` where ``summary`` maps asset id to
    ``"skipped"`` / ``"uploaded"`` / ``"url"`` (kept in place, http(s)).
    """
    if not isinstance(registry, dict) or not isinstance(registry.get("assets"), dict):
        raise PublishError("registry has no `assets` object; refusing to publish")
    new_assets: dict[str, dict[str, Any]] = {}
    summary: dict[str, str] = {}
    for asset_id, raw_entry in registry["assets"].items():
        if not isinstance(raw_entry, dict):
            raise PublishError(f"assets[{asset_id!r}] is not an object")
        entry = dict(raw_entry)
        url = entry.get("url")
        if is_http_url(url):
            # Pass through http(s) URLs verbatim — they're either already
            # publicly addressable or signed; no upload needed.
            new_assets[asset_id] = entry
            summary[asset_id] = "url"
            continue
        local_path = _local_path_for_entry(entry)
        if local_path is None:
            raise PublishError(
                f"assets[{asset_id!r}] has no `url` and no local `file` path; cannot upload"
            )
        if not local_path.is_file():
            raise PublishError(
                f"assets[{asset_id!r}] file not found: {local_path}"
            )
        sha = _content_sha256_from_entry(entry, local_path)
        content_type = entry.get("type")
        # entry["type"] is "video" / "audio" / "image" — translate into a
        # MIME type for the upload Content-Type header.
        mime_guess, _ = mimetypes.guess_type(str(local_path))
        ext = _ext_for(local_path, mime_guess)
        key = f"{user_id}/{timeline_id}/{sha}{ext}"
        outcome = upload_fn(
            supabase_url=supabase_url,
            user_token=user_token,
            bucket=bucket,
            key=key,
            file_path=local_path,
            content_type=mime_guess,
        )
        rewritten = dict(entry)
        rewritten["file"] = key
        rewritten["content_sha256"] = sha
        if isinstance(content_type, str) and content_type:
            rewritten["type"] = content_type
        new_assets[asset_id] = rewritten
        summary[asset_id] = outcome
    return {"assets": new_assets}, summary


# ---------------------------------------------------------------------------
# Versioning + import
# ---------------------------------------------------------------------------


def fetch_expected_version(
    supabase_url: str,
    user_token: str,
    timeline_id: str,
) -> int | None:
    """Call the `get_timeline_version` RPC (Postgres function) via PostgREST.

    Returns ``None`` if the RPC returns no row (timeline doesn't exist) or if
    the RPC isn't installed yet (404). Raises on auth failures.
    """
    url = f"{supabase_url.rstrip('/')}/rest/v1/rpc/get_timeline_version"
    headers = {
        "Authorization": f"Bearer {user_token}",
        "apikey": user_token,
        "Content-Type": "application/json",
    }
    body = json.dumps({"p_timeline_id": timeline_id}).encode("utf-8")
    resp = _request("POST", url, headers=headers, data=body)
    if resp.status == 404:
        return None
    if resp.status in (401, 403):
        raise PublishError(
            f"get_timeline_version RPC denied access ({resp.status}); the JWT "
            f"must own the timeline to read its version."
        )
    if resp.status >= 400:
        raise PublishError(
            f"get_timeline_version RPC failed ({resp.status}): {resp.text()[:200]}"
        )
    payload = resp.json()
    if payload is None:
        return None
    if isinstance(payload, list):
        if not payload:
            return None
        first = payload[0]
        if isinstance(first, dict):
            value = first.get("config_version") if "config_version" in first else first.get("get_timeline_version")
            return int(value) if isinstance(value, (int, float)) else None
        if isinstance(first, (int, float)):
            return int(first)
    if isinstance(payload, (int, float)):
        return int(payload)
    if isinstance(payload, dict):
        value = payload.get("config_version") if "config_version" in payload else payload.get("get_timeline_version")
        return int(value) if isinstance(value, (int, float)) else None
    return None


def submit_import(
    *,
    supabase_url: str,
    user_token: str,
    project_id: str,
    timeline_id: str,
    timeline_config: dict[str, Any],
    asset_registry: dict[str, Any],
    expected_version: int | None,
    create_if_missing: bool,
) -> HttpResponse:
    url = f"{supabase_url.rstrip('/')}/functions/v1/timeline-import"
    headers = {
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "project_id": project_id,
        "timeline_id": timeline_id,
        "timeline": timeline_config,
        "asset_registry": asset_registry,
        "create_if_missing": create_if_missing,
    }
    if expected_version is not None:
        payload["expected_version"] = expected_version
    body = json.dumps(payload).encode("utf-8")
    return _request("POST", url, headers=headers, data=body)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _resolve_timeline_path(args: argparse.Namespace) -> Path:
    if args.timeline_file is not None:
        return Path(args.timeline_file).expanduser().resolve()
    raise PublishError(
        "--timeline-file is required (the path to your hype.timeline.json). "
        "If you ran `tools/pipeline.py`, point at "
        "<out>/briefs/<brief>/hype.timeline.json."
    )


def _resolve_assets_path(timeline_path: Path) -> Path:
    candidate = timeline_path.parent / "hype.assets.json"
    if not candidate.is_file():
        raise PublishError(f"asset registry not found next to timeline: {candidate}")
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tools/publish.py",
        description=(
            "Publish a Banodoco-authored timeline into a Reigh project. "
            "Uploads non-HTTP assets to the timeline-assets bucket and posts "
            "the rewritten timeline to the `timeline-import` edge function."
        ),
    )
    parser.add_argument("--project-id", required=True, dest="project_id")
    parser.add_argument("--timeline-id", required=True, dest="timeline_id")
    parser.add_argument("--expected-version", type=int, dest="expected_version", default=None)
    parser.add_argument("--create-if-missing", action="store_true", dest="create_if_missing")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Skip CAS — let the edge function do fetch-then-write. The CLI "
            "omits expected_version from the payload."
        ),
    )
    parser.add_argument(
        "--timeline-file",
        dest="timeline_file",
        type=Path,
        default=None,
        help=(
            "Path to hype.timeline.json. The asset registry is loaded from "
            "hype.assets.json next to it."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except PublishError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace) -> int:
    user_token = os.environ.get("REIGH_USER_TOKEN", "").strip()
    supabase_url = os.environ.get("REIGH_SUPABASE_URL", "").strip()
    if not user_token:
        raise PublishError("REIGH_USER_TOKEN is not set in the environment")
    if not supabase_url:
        raise PublishError("REIGH_SUPABASE_URL is not set in the environment")

    user_id = assert_supabase_user_jwt(user_token)

    timeline_path = _resolve_timeline_path(args)
    assets_path = _resolve_assets_path(timeline_path)

    timeline_config = timeline.load_timeline(timeline_path)
    # Sprint 5/6 strict validation; raises ValueError on any drift.
    timeline.validate_timeline(_for_wire(timeline_config), strict=True)
    registry = timeline.load_registry(assets_path)

    new_registry, summary = upload_assets_and_rewrite(
        registry,
        supabase_url=supabase_url,
        user_token=user_token,
        user_id=user_id,
        timeline_id=args.timeline_id,
    )
    for asset_id, outcome in summary.items():
        print(f"publish: {asset_id}: {outcome}")

    expected_version: int | None
    if args.force:
        expected_version = None
    elif args.expected_version is not None:
        expected_version = args.expected_version
    else:
        expected_version = fetch_expected_version(supabase_url, user_token, args.timeline_id)
        if expected_version is None and not args.create_if_missing:
            raise PublishError(
                f"timeline {args.timeline_id} has no version on the server (returned no row); "
                "pass --create-if-missing to insert it, or --force to skip the version check."
            )

    response = submit_import(
        supabase_url=supabase_url,
        user_token=user_token,
        project_id=args.project_id,
        timeline_id=args.timeline_id,
        timeline_config=_for_wire(timeline_config),
        asset_registry=new_registry,
        expected_version=expected_version,
        create_if_missing=args.create_if_missing,
    )
    return _surface_response(response, expected_version=expected_version)


def _for_wire(timeline_config: dict[str, Any]) -> dict[str, Any]:
    """Convert in-memory `from_` back to JSON-canonical `from`."""
    payload = dict(timeline_config)
    clips = payload.get("clips")
    if isinstance(clips, list):
        rewritten: list[dict[str, Any]] = []
        for clip in clips:
            if not isinstance(clip, dict):
                rewritten.append(clip)
                continue
            normalized = dict(clip)
            if "from_" in normalized and "from" not in normalized:
                normalized["from"] = normalized.pop("from_")
            rewritten.append(normalized)
        payload["clips"] = rewritten
    return payload


def _surface_response(response: HttpResponse, *, expected_version: int | None) -> int:
    body = response.json()
    if response.status in (200, 201):
        new_version = None
        if isinstance(body, dict):
            new_version = body.get("config_version")
        if new_version is not None:
            print(f"publish: ok (config_version={new_version})")
        else:
            print("publish: ok")
        return 0
    if response.status == 409:
        current = None
        if isinstance(body, dict):
            current = body.get("current_version") or body.get("config_version")
        msg = (
            f"version mismatch (sent expected_version={expected_version}); "
            f"current is {current}. Retry with --expected-version {current} or --force."
        )
        raise PublishError(msg)
    if response.status in (401, 403):
        raise PublishError(
            f"auth failed / unauthorized ({response.status}): {response.text()[:200]}"
        )
    if response.status == 404:
        raise PublishError(
            f"timeline not found ({response.status}); pass --create-if-missing to insert."
        )
    raise PublishError(
        f"timeline-import failed with status {response.status}: {response.text()[:300]}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
