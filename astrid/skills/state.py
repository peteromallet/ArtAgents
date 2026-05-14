"""Install-state JSON for the skills layer.

State path: ``$XDG_STATE_HOME/astrid/skills.json`` if XDG_STATE_HOME is set,
else ``~/.local/state/astrid/skills.json``. This single location works on
macOS and Linux; the user can override with ``ASTRID_STATE_HOME`` for
testing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_VERSION = 1
HARNESSES = ("claude", "codex", "hermes")


def state_path() -> Path:
    override = os.environ.get("ASTRID_STATE_HOME")
    if override:
        return Path(override) / "astrid" / "skills.json"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "astrid" / "skills.json"


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "installs": {harness: {} for harness in HARNESSES},
        "nudge": {harness: {"last_shown_at": None} for harness in HARNESSES},
    }


def load(path: Path | None = None) -> dict[str, Any]:
    target = path or state_path()
    if not target.exists():
        return _empty_state()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    # Defensive: backfill missing top-level keys for forward-compat.
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault("version", STATE_VERSION)
    installs = data.setdefault("installs", {})
    nudge = data.setdefault("nudge", {})
    for harness in HARNESSES:
        installs.setdefault(harness, {})
        nudge.setdefault(harness, {"last_shown_at": None})
    return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_install(
    state: dict[str, Any],
    harness: str,
    pack_id: str,
    *,
    target: str,
    mechanism: str,
) -> None:
    state["installs"].setdefault(harness, {})[pack_id] = {
        "target": target,
        "installed_at": now_iso(),
        "mechanism": mechanism,
    }


def record_uninstall(state: dict[str, Any], harness: str, pack_id: str) -> None:
    state["installs"].setdefault(harness, {}).pop(pack_id, None)


def record_nudge(state: dict[str, Any], harness: str) -> None:
    state["nudge"].setdefault(harness, {})["last_shown_at"] = now_iso()


__all__ = [
    "HARNESSES",
    "STATE_VERSION",
    "load",
    "now_iso",
    "record_install",
    "record_nudge",
    "record_uninstall",
    "save",
    "state_path",
]
