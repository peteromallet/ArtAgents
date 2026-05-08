"""Reigh DataProvider: Python mirror of reigh-app's TS ``SupabaseDataProvider``.

Surface (matches the TS contract):

Required:
  * ``load_timeline(project_id, timeline_id) -> (TimelineConfig, int)``
  * ``save_timeline(timeline_id, mutator, *, service_role_key=None, auth=None,
    expected_version=None, retries=3, force=False) -> SaveResult``
  * ``load_asset_registry(project_id, timeline_id) -> AssetRegistry``
  * ``resolve_asset_url(asset_entry) -> str``

Optional:
  * ``register_asset(project_id, timeline_id, asset_id, entry)``
  * ``upload_asset(project_id, timeline_id, user_id, filename, data, content_type)``
    — writes to ``timeline-assets/${user_id}/${timeline_id}/${epoch_ms}-${filename}``
    and then calls ``register_asset``.
  * ``load_checkpoints(project_id, timeline_id)``
  * ``save_checkpoint(project_id, timeline_id, checkpoint)``
  * ``load_waveform(asset_id)`` (no ``save_waveform``)
  * ``load_asset_profile(asset_id)`` (no ``load_profile`` / ``save_profile``)

Auth scoping (FLAG-012, SD-009): ``save_timeline`` accepts an explicit ``auth``
tuple (``"user_jwt" | "pat" | "service_role"``) for non-worker callers, falling
back to ``service_role_key`` only when ``auth`` is omitted. The worker passes
``service_role_key``; the CLI / ``open_in_reigh`` should pass ``auth=("user_jwt",
token)`` or ``auth=("pat", token)`` instead.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping

from . import env as reigh_env
from . import timeline_io
from .errors import TimelineNotFoundError
from .supabase_client import Auth, SupabaseHTTPError, post_json
from .timeline_io import Mutator, SaveResult, TimelineConfig

logger = logging.getLogger(__name__)


@dataclass
class SupabaseDataProvider:
    """Python implementation of reigh-app's TS DataProvider contract.

    Construct with explicit URLs/tokens, or rely on ``from_env()`` to derive
    them from the standard ``REIGH_*`` env vars.
    """

    supabase_url: str
    fetch_url: str
    pat: str | None = None
    timeout: float = 60.0

    @classmethod
    def from_env(cls, *, env_file: Any = None, timeout: float = 60.0) -> "SupabaseDataProvider":
        return cls(
            supabase_url=reigh_env.resolve_supabase_url(env_file=env_file),
            fetch_url=reigh_env.resolve_api_url(env_file=env_file),
            pat=_optional(lambda: reigh_env.resolve_pat(env_file=env_file)),
            timeout=timeout,
        )

    # ----- read auth helper -----

    def _read_auth(self, auth: Auth | None = None) -> Auth:
        if auth is not None:
            return auth
        if self.pat:
            return ("pat", self.pat)
        raise RuntimeError(
            "SupabaseDataProvider needs an auth tuple or REIGH_PAT to read timelines"
        )

    # ----- required surface -----

    def load_timeline(
        self,
        project_id: str,
        timeline_id: str,
        *,
        auth: Auth | None = None,
    ) -> tuple[TimelineConfig, int]:
        return timeline_io.fetch_timeline(
            fetch_url=self.fetch_url,
            project_id=project_id,
            timeline_id=timeline_id,
            auth=self._read_auth(auth),
            timeout=self.timeout,
        )

    def save_timeline(
        self,
        timeline_id: str,
        mutator: Mutator,
        *,
        project_id: str,
        service_role_key: str | None = None,
        auth: Auth | None = None,
        expected_version: int | None = None,
        retries: int = 3,
        force: bool = False,
        read_auth: Auth | None = None,
    ) -> SaveResult:
        write_auth = self._resolve_write_auth(auth, service_role_key)
        return timeline_io.save_timeline(
            timeline_id=timeline_id,
            project_id=project_id,
            mutator=mutator,
            fetch_url=self.fetch_url,
            supabase_url=self.supabase_url,
            read_auth=self._read_auth(read_auth),
            write_auth=write_auth,
            expected_version=expected_version,
            retries=retries,
            force=force,
            timeout=self.timeout,
        )

    def load_asset_registry(
        self,
        project_id: str,
        timeline_id: str,
        *,
        auth: Auth | None = None,
    ) -> dict[str, Any]:
        payload = post_json(
            self.fetch_url,
            {"project_id": project_id, "timeline_id": timeline_id},
            auth=self._read_auth(auth),
            timeout=self.timeout,
        )
        if not isinstance(payload, dict):
            raise TimelineNotFoundError("reigh-data-fetch returned non-object payload")
        timelines = payload.get("timelines")
        if isinstance(timelines, list):
            for entry in timelines:
                if isinstance(entry, dict) and entry.get("id") == timeline_id:
                    registry = entry.get("asset_registry")
                    if isinstance(registry, dict):
                        return dict(registry)
        return {"assets": {}}

    def resolve_asset_url(self, asset_entry: Mapping[str, Any]) -> str:
        for key in ("url", "file"):
            value = asset_entry.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("asset entry has no resolvable url/file field")

    # ----- optional surface -----

    def register_asset(
        self,
        *,
        project_id: str,
        timeline_id: str,
        asset_id: str,
        entry: Mapping[str, Any],
        service_role_key: str | None = None,
        auth: Auth | None = None,
    ) -> dict[str, Any]:
        write_auth = self._resolve_write_auth(auth, service_role_key)
        endpoint = f"{self.supabase_url.rstrip('/')}/functions/v1/timeline-import"
        payload = {
            "project_id": project_id,
            "timeline_id": timeline_id,
            "asset_registry_patch": {asset_id: dict(entry)},
        }
        result = post_json(endpoint, payload, auth=write_auth, timeout=self.timeout)
        return result if isinstance(result, dict) else {"ok": True}

    def upload_asset(
        self,
        *,
        project_id: str,
        timeline_id: str,
        user_id: str,
        asset_id: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        service_role_key: str | None = None,
        auth: Auth | None = None,
    ) -> dict[str, Any]:
        """Upload to ``timeline-assets/{user_id}/{timeline_id}/{epoch_ms}-{filename}``
        then call ``register_asset`` with a registry entry pointing at it."""

        write_auth = self._resolve_write_auth(auth, service_role_key)
        epoch_ms = int(time.time() * 1000)
        safe_name = urllib.parse.quote(filename, safe="._-")
        object_path = f"{user_id}/{timeline_id}/{epoch_ms}-{safe_name}"
        bucket = "timeline-assets"
        endpoint = (
            f"{self.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/"
            + urllib.parse.quote(object_path, safe="/._-")
        )
        scheme, token = write_auth
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        if scheme == "service_role":
            headers["apikey"] = token
        import urllib.request as _request
        request = _request.Request(endpoint, data=data, headers=headers, method="POST")
        with _request.urlopen(request, timeout=self.timeout) as _:
            pass
        registry_entry = {
            "file": f"{bucket}/{object_path}",
            "type": content_type,
        }
        self.register_asset(
            project_id=project_id,
            timeline_id=timeline_id,
            asset_id=asset_id,
            entry=registry_entry,
            auth=write_auth,
        )
        return {"object_path": object_path, "bucket": bucket, "entry": registry_entry}

    def load_checkpoints(
        self,
        project_id: str,
        timeline_id: str,
        *,
        auth: Auth | None = None,
    ) -> list[dict[str, Any]]:
        payload = post_json(
            self.fetch_url,
            {
                "project_id": project_id,
                "timeline_id": timeline_id,
                "include": ["checkpoints"],
            },
            auth=self._read_auth(auth),
            timeout=self.timeout,
        )
        if isinstance(payload, dict):
            checkpoints = payload.get("checkpoints")
            if isinstance(checkpoints, list):
                return [dict(item) for item in checkpoints if isinstance(item, dict)]
        return []

    def save_checkpoint(
        self,
        *,
        project_id: str,
        timeline_id: str,
        checkpoint: Mapping[str, Any],
        service_role_key: str | None = None,
        auth: Auth | None = None,
    ) -> dict[str, Any]:
        write_auth = self._resolve_write_auth(auth, service_role_key)
        endpoint = f"{self.supabase_url.rstrip('/')}/functions/v1/timeline-import"
        payload = {
            "project_id": project_id,
            "timeline_id": timeline_id,
            "checkpoint": dict(checkpoint),
        }
        result = post_json(endpoint, payload, auth=write_auth, timeout=self.timeout)
        return result if isinstance(result, dict) else {"ok": True}

    def load_waveform(
        self,
        asset_id: str,
        *,
        auth: Auth | None = None,
    ) -> dict[str, Any] | None:
        endpoint = f"{self.fetch_url.rstrip('/')}"
        payload = post_json(
            endpoint,
            {"asset_id": asset_id, "include": ["waveform"]},
            auth=self._read_auth(auth),
            timeout=self.timeout,
        )
        if isinstance(payload, dict):
            waveform = payload.get("waveform")
            if isinstance(waveform, dict):
                return dict(waveform)
        return None

    def load_asset_profile(
        self,
        asset_id: str,
        *,
        auth: Auth | None = None,
    ) -> dict[str, Any] | None:
        endpoint = f"{self.fetch_url.rstrip('/')}"
        payload = post_json(
            endpoint,
            {"asset_id": asset_id, "include": ["profile"]},
            auth=self._read_auth(auth),
            timeout=self.timeout,
        )
        if isinstance(payload, dict):
            profile = payload.get("profile")
            if isinstance(profile, dict):
                return dict(profile)
        return None

    # ----- internals -----

    def _resolve_write_auth(
        self,
        auth: Auth | None,
        service_role_key: str | None,
    ) -> Auth:
        if auth is not None:
            return auth
        if service_role_key:
            return ("service_role", service_role_key)
        raise RuntimeError(
            "SupabaseDataProvider write requires either auth=(scheme, token) "
            "or service_role_key (worker-only)"
        )


def _optional(thunk: Any) -> Any:
    try:
        return thunk()
    except RuntimeError:
        return None
