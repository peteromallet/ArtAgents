"""Environment discovery for Reigh edge-function and Supabase integrations."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_FUNCTION_NAME = "reigh-data-fetch"


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        env_key, env_value = line.split("=", 1)
        if env_key.strip() == key:
            return env_value.strip().strip('"').strip("'")
    return ""


def _candidate_env_files(env_file: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(env_file)
    repo_root = Path(__file__).resolve().parents[3]
    workspace = repo_root.parent
    candidates.extend(
        [
            Path.cwd() / "this.env",
            Path.cwd() / ".env.local",
            Path.cwd() / ".env",
            repo_root / "this.env",
            repo_root / ".env.local",
            repo_root / ".env",
            workspace / "this.env",
            workspace / ".env.local",
            workspace / ".env",
            workspace / "reigh-app" / "this.env",
            workspace / "reigh-app" / ".env.local",
            workspace / "reigh-app" / ".env",
            Path.home() / "this.env",
            Path.home() / ".env.local",
            Path.home() / ".env",
            Path.home() / ".codex" / "this.env",
            Path.home() / ".codex" / ".env.local",
            Path.home() / ".codex" / ".env",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _env_first(keys: tuple[str, ...], env_file: Path | None = None) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    for candidate in _candidate_env_files(env_file):
        for key in keys:
            value = _read_env_value(candidate, key)
            if value:
                return value
    return ""


def _url_from_base(base: str, function_name: str) -> str:
    return f"{base.rstrip('/')}/functions/v1/{function_name}"


def resolve_supabase_url(
    supabase_url: str | None = None,
    env_file: Path | None = None,
) -> str:
    explicit = (supabase_url or "").strip()
    if explicit:
        return explicit.rstrip("/")
    value = _env_first(("REIGH_SUPABASE_URL", "SUPABASE_URL"), env_file)
    if value:
        return value.rstrip("/")
    raise RuntimeError("Reigh Supabase URL not found. Set REIGH_SUPABASE_URL or SUPABASE_URL.")


def resolve_api_url(api_url: str | None = None, env_file: Path | None = None) -> str:
    explicit = (api_url or "").strip()
    if explicit:
        return explicit.rstrip("/")

    direct = _env_first(("REIGH_DATA_FETCH_URL",), env_file)
    if direct:
        return direct.rstrip("/")

    base = _env_first(("REIGH_API_URL", "REIGH_SUPABASE_URL", "SUPABASE_URL"), env_file)
    if base:
        return _url_from_base(base, DEFAULT_FUNCTION_NAME)

    raise RuntimeError(
        "Reigh API URL not found. Set REIGH_DATA_FETCH_URL, REIGH_API_URL, "
        "REIGH_SUPABASE_URL, or SUPABASE_URL."
    )


def resolve_pat(pat: str | None = None, env_file: Path | None = None) -> str:
    explicit = (pat or "").strip()
    if explicit:
        return explicit
    token = _env_first(("REIGH_PAT", "REIGH_PERSONAL_ACCESS_TOKEN"), env_file)
    if token:
        return token
    raise RuntimeError("Reigh PAT not found. Set REIGH_PAT or REIGH_PERSONAL_ACCESS_TOKEN.")


def resolve_claim_url(claim_url: str | None = None, env_file: Path | None = None) -> str:
    explicit = (claim_url or "").strip()
    if explicit:
        return explicit.rstrip("/")

    direct = _env_first(("REIGH_CLAIM_NEXT_TASK_URL", "REIGH_CLAIM_URL"), env_file)
    if direct:
        return direct.rstrip("/")

    base = _env_first(
        ("ORCHESTRATOR_BASE_URL", "REIGH_ORCHESTRATOR_URL", "REIGH_SUPABASE_URL", "SUPABASE_URL"),
        env_file,
    )
    if base:
        return _url_from_base(base, "claim-next-task")

    raise RuntimeError(
        "Claim URL not found. Set REIGH_CLAIM_NEXT_TASK_URL, ORCHESTRATOR_BASE_URL, "
        "REIGH_SUPABASE_URL, or SUPABASE_URL."
    )


def resolve_task_status_update_url(
    update_url: str | None = None,
    env_file: Path | None = None,
) -> str:
    explicit = (update_url or "").strip()
    if explicit:
        return explicit.rstrip("/")

    direct = _env_first(
        ("REIGH_TASK_STATUS_UPDATE_URL", "REIGH_UPDATE_TASK_STATUS_URL"),
        env_file,
    )
    if direct:
        return direct.rstrip("/")

    base = _env_first(
        ("ORCHESTRATOR_BASE_URL", "REIGH_ORCHESTRATOR_URL", "REIGH_SUPABASE_URL", "SUPABASE_URL"),
        env_file,
    )
    if base:
        return _url_from_base(base, "update-task-status")

    raise RuntimeError(
        "Task status update URL not found. Set REIGH_TASK_STATUS_UPDATE_URL, "
        "ORCHESTRATOR_BASE_URL, REIGH_SUPABASE_URL, or SUPABASE_URL."
    )


def resolve_service_role_key(
    service_role_key: str | None = None,
    env_file: Path | None = None,
) -> str:
    explicit = (service_role_key or "").strip()
    if explicit:
        return explicit
    key = _env_first(("REIGH_SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"), env_file)
    if key:
        return key
    raise RuntimeError(
        "Reigh Supabase service-role key not found. Set REIGH_SUPABASE_SERVICE_ROLE_KEY."
    )


def resolve_jwks_url(jwks_url: str | None = None, env_file: Path | None = None) -> str:
    explicit = (jwks_url or "").strip()
    if explicit:
        return explicit.rstrip("/")

    direct = _env_first(("REIGH_SUPABASE_JWKS_URL",), env_file)
    if direct:
        return direct.rstrip("/")

    base = resolve_supabase_url(env_file=env_file)
    return f"{base}/auth/v1/.well-known/jwks.json"

