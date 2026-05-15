"""Filesystem path helpers for the session layer.

``ASTRID_HOME`` env var overrides the default ``~/.astrid`` root so tests can
sandbox session/identity state without touching the real home directory.
"""

from __future__ import annotations

import os
from pathlib import Path

ASTRID_HOME_ENV = "ASTRID_HOME"
_DEFAULT_ASTRID_HOME = Path("~/.astrid")

SESSIONS_DIRNAME = "sessions"
IDENTITY_FILENAME = "identity.json"
USER_CONFIG_FILENAME = "config.json"
WORKSPACE_CONFIG_DIRNAME = ".astrid"
WORKSPACE_CONFIG_FILENAME = "config.json"
PACKS_DIRNAME = "packs"


def astrid_home() -> Path:
    """Return the per-user Astrid state directory (honors ``ASTRID_HOME``)."""

    raw = os.environ.get(ASTRID_HOME_ENV)
    base = Path(raw) if raw else _DEFAULT_ASTRID_HOME
    return base.expanduser().resolve()


def sessions_dir() -> Path:
    return astrid_home() / SESSIONS_DIRNAME


def session_path(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.json"


def identity_path() -> Path:
    return astrid_home() / IDENTITY_FILENAME


def user_config_path() -> Path:
    return astrid_home() / USER_CONFIG_FILENAME


def workspace_config_path(cwd: str | Path | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / WORKSPACE_CONFIG_DIRNAME / WORKSPACE_CONFIG_FILENAME


def installed_packs_root() -> Path:
    """Return the per-user installed packs directory (honors ``ASTRID_HOME``)."""
    return astrid_home() / PACKS_DIRNAME
