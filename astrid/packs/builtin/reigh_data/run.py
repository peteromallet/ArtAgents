#!/usr/bin/env python3
"""Fetch canonical Reigh project data through the reigh-app Edge Function."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from astrid.core.reigh.env import (
    DEFAULT_FUNCTION_NAME,
    _candidate_env_files,
    _env_first,
    resolve_api_url,
    resolve_claim_url,
    resolve_jwks_url,
    resolve_pat,
    resolve_service_role_key,
    resolve_supabase_url,
    resolve_task_status_update_url,
)


def fetch_reigh_data(
    *,
    project_id: str,
    shot_id: str | None = None,
    task_id: str | None = None,
    timeline_id: str | None = None,
    api_url: str | None = None,
    pat: str | None = None,
    env_file: Path | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    endpoint = resolve_api_url(api_url, env_file)
    token = resolve_pat(pat, env_file)
    payload = {
        "project_id": project_id,
        **({"shot_id": shot_id} if shot_id else {}),
        **({"task_id": task_id} if task_id else {}),
        **({"timeline_id": timeline_id} if timeline_id else {}),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Reigh data fetch failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Reigh data fetch failed: {exc.reason}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch canonical Reigh project data through the reigh-data-fetch Edge Function."
    )
    parser.add_argument("--project-id", required=True, help="Reigh project UUID.")
    parser.add_argument("--shot-id", help="Optional shot UUID; response stays project-scoped.")
    parser.add_argument("--task-id", help="Optional task UUID; response stays project-scoped.")
    parser.add_argument("--timeline-id", help="Optional timeline UUID; response stays project-scoped.")
    parser.add_argument("--api-url", help="Full Edge Function URL. Defaults to env-derived reigh-data-fetch URL.")
    parser.add_argument("--pat", help="Personal Access Token. Prefer REIGH_PAT / REIGH_PERSONAL_ACCESS_TOKEN.")
    parser.add_argument("--env-file", type=Path, help="Optional env file for URL/PAT lookup.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out", type=Path, help="Write JSON response to this path.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of pretty JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = fetch_reigh_data(
            project_id=args.project_id,
            shot_id=args.shot_id,
            task_id=args.task_id,
            timeline_id=args.timeline_id,
            api_url=args.api_url,
            pat=args.pat,
            env_file=args.env_file,
            timeout=args.timeout,
        )
    except RuntimeError as exc:
        print(f"reigh-data: {exc}", file=sys.stderr)
        return 2

    indent = None if args.compact else 2
    text = json.dumps(data, indent=indent, sort_keys=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
