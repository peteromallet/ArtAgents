"""Thin Supabase POST/RPC wrapper used by the Reigh DataProvider stack.

The ``auth`` parameter is an explicit ``(scheme, token)`` tuple where ``scheme``
is one of ``"user_jwt"``, ``"pat"``, or ``"service_role"``. The wrapper sets the
HTTP ``Authorization`` header accordingly and, for service-role calls, also
sets ``apikey`` as Supabase requires for direct PostgREST/RPC access.

The wrapper deliberately stays small: callers compose endpoint URLs (via
``astrid.core.reigh.env``) and decide which auth scheme is appropriate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Literal, Mapping, Tuple


AuthScheme = Literal["user_jwt", "pat", "service_role"]
Auth = Tuple[AuthScheme, str]


class SupabaseHTTPError(RuntimeError):
    """Raised when a Supabase POST/RPC call returns a non-2xx response."""

    def __init__(self, message: str, *, status: int, body: str) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _build_headers(auth: Auth, *, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    scheme, token = auth
    if not isinstance(token, str) or not token:
        raise ValueError("Supabase auth token must be a non-empty string")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if scheme == "service_role":
        headers["apikey"] = token
    elif scheme not in ("user_jwt", "pat"):
        raise ValueError(f"Unknown Supabase auth scheme: {scheme!r}")
    if extra:
        headers.update(extra)
    return headers


def post_json(
    url: str,
    payload: Mapping[str, Any] | None,
    *,
    auth: Auth,
    extra_headers: Mapping[str, str] | None = None,
    timeout: float = 60.0,
) -> Any:
    """POST a JSON body to ``url`` with the given auth and return parsed JSON."""

    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=_build_headers(auth, extra=extra_headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SupabaseHTTPError(
            f"Supabase POST failed: HTTP {exc.code}: {detail}",
            status=exc.code,
            body=detail,
        ) from exc
    except urllib.error.URLError as exc:
        raise SupabaseHTTPError(
            f"Supabase POST failed: {exc.reason}", status=0, body=str(exc.reason)
        ) from exc

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def rpc(
    name: str,
    params: Mapping[str, Any],
    *,
    supabase_url: str,
    auth: Auth,
    timeout: float = 60.0,
) -> Any:
    """Invoke a PostgREST RPC by name.

    Maps to ``POST {supabase_url}/rest/v1/rpc/{name}`` with the params dict as the
    JSON body.
    """

    if not isinstance(name, str) or not name:
        raise ValueError("rpc name must be a non-empty string")
    base = supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/rpc/{name}"
    return post_json(endpoint, dict(params), auth=auth, timeout=timeout)
