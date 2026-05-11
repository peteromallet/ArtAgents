"""User + workspace config readers.

Per-user config lives at ``~/.astrid/config.json``; the per-workspace
override lives at ``<cwd>/.astrid/config.json``. Workspace wins for
defaults that overlap (per the brief). Neither auto-attaches — they only
feed the suggestion shown by ``astrid status`` when unbound.

Schema (additive; unknown keys preserved): ``{"default_project": <slug>,
"default_timeline": <slug>}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import read_json
from astrid.core.session.paths import user_config_path, workspace_config_path


class ConfigError(ValueError):
    """Raised when a config file is malformed."""


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a JSON object")
    return dict(raw)


def load_user_config() -> dict[str, Any]:
    return _load(user_config_path())


def load_workspace_config(cwd: str | Path | None = None) -> dict[str, Any]:
    return _load(workspace_config_path(cwd))


def resolve_default_project(cwd: str | Path | None = None) -> str | None:
    """Merge per-user and per-workspace defaults; workspace wins."""

    merged: dict[str, Any] = {}
    merged.update(load_user_config())
    merged.update(load_workspace_config(cwd))
    value = merged.get("default_project")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError("default_project must be a non-empty string")
    return value


def resolve_default_timeline(cwd: str | Path | None = None) -> str | None:
    merged: dict[str, Any] = {}
    merged.update(load_user_config())
    merged.update(load_workspace_config(cwd))
    value = merged.get("default_timeline")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError("default_timeline must be a non-empty string")
    return value
