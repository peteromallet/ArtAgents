#!/usr/bin/env python3
"""Read workspace-level and active-theme Remotion primitive folders."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from ._paths import REPO_ROOT, WORKSPACE_ROOT

TOOLS_DIR = REPO_ROOT
THEMES_ROOT = WORKSPACE_ROOT / "themes"


def _initial_active_theme() -> Path | None:
    """Pick up an active theme from the HYPE_ACTIVE_THEME env var on import.

    Each pipeline script (pool_merge, arrange, cut, validate, render_remotion)
    runs in its own subprocess and re-imports this module; the env var lets
    pipeline.py thread the active theme through without each script having to
    call set_active_theme() from its own --theme arg.
    """
    raw = os.environ.get("HYPE_ACTIVE_THEME")
    if not raw:
        return None
    return _resolve_theme_dir(raw)


_ACTIVE_THEME_DIR: Path | None = None  # initialized after _resolve_theme_dir is defined

PrimitiveKind = Literal["effects", "animations", "transitions"]
REQUIRED_PLUGIN_FILES = ("component.tsx", "schema.json", "defaults.json", "meta.json")


def effects_root() -> Path:
    return primitive_root("effects")


def animations_root() -> Path:
    return primitive_root("animations")


def transitions_root() -> Path:
    return primitive_root("transitions")


def primitive_root(kind: PrimitiveKind) -> Path:
    _validate_kind(kind)
    return WORKSPACE_ROOT / kind


def _validate_kind(kind: str) -> None:
    if kind not in {"effects", "animations", "transitions"}:
        raise ValueError(f"Invalid primitive kind {kind!r}")


def _singular(kind: PrimitiveKind) -> str:
    return kind[:-1]


def _resolve_theme_dir(theme: str | Path | None) -> Path | None:
    if theme is None:
        return None
    candidate = Path(theme)
    if candidate.name == "theme.json":
        return candidate.parent.resolve()
    if candidate.exists():
        return (candidate if candidate.is_dir() else candidate.parent).resolve()
    return (THEMES_ROOT / str(theme)).resolve()


def set_active_theme(theme: str | Path | None) -> None:
    global _ACTIVE_THEME_DIR
    _ACTIVE_THEME_DIR = _resolve_theme_dir(theme)


_ACTIVE_THEME_DIR = _initial_active_theme()


def _active_theme_dir(theme: str | Path | None = None) -> Path | None:
    return _resolve_theme_dir(theme) if theme is not None else _ACTIVE_THEME_DIR


def _is_valid_plugin_dir(root: Path) -> bool:
    return all((root / filename).is_file() for filename in REQUIRED_PLUGIN_FILES)


def _scan_primitive_ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        if _is_valid_plugin_dir(child):
            ids.append(child.name)
    return ids


def _validate_primitive_id(primitive_id: str, *, kind: PrimitiveKind) -> None:
    if "/" in primitive_id or "\\" in primitive_id or primitive_id in {"", ".", ".."}:
        raise ValueError(f"Invalid {_singular(kind)} id {primitive_id!r}")


def _primitive_dir(
    primitive_id: str,
    *,
    kind: PrimitiveKind,
    theme: str | Path | None = None,
) -> Path:
    _validate_kind(kind)
    _validate_primitive_id(primitive_id, kind=kind)
    theme_dir = _active_theme_dir(theme)
    if theme_dir is not None:
        themed = theme_dir / kind / primitive_id
        if _is_valid_plugin_dir(themed):
            return themed
    return primitive_root(kind) / primitive_id


def _read_json(
    primitive_id: str,
    filename: str,
    *,
    kind: PrimitiveKind,
    theme: str | Path | None = None,
) -> dict[str, Any]:
    path = _primitive_dir(primitive_id, kind=kind, theme=theme) / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def list_primitive_ids(kind: PrimitiveKind, theme: str | Path | None = None) -> list[str]:
    _validate_kind(kind)
    primitive_ids = set(_scan_primitive_ids(primitive_root(kind)))
    theme_dir = _active_theme_dir(theme)
    if theme_dir is not None:
        theme_ids = _scan_primitive_ids(theme_dir / kind)
        singular = _singular(kind)
        for primitive_id in theme_ids:
            if primitive_id in primitive_ids:
                print(
                    f"WARN theme '{theme_dir.name}' overrides workspace {singular} '{primitive_id}'",
                    file=sys.stderr,
                )
            primitive_ids.add(primitive_id)
    return sorted(primitive_ids)


def read_primitive_schema(
    primitive_id: str,
    *,
    kind: PrimitiveKind,
    theme: str | Path | None = None,
) -> dict[str, Any]:
    return _read_json(primitive_id, "schema.json", kind=kind, theme=theme)


def read_primitive_meta(
    primitive_id: str,
    *,
    kind: PrimitiveKind,
    theme: str | Path | None = None,
) -> dict[str, Any]:
    return _read_json(primitive_id, "meta.json", kind=kind, theme=theme)


def read_primitive_defaults(
    primitive_id: str,
    *,
    kind: PrimitiveKind,
    theme: str | Path | None = None,
) -> dict[str, Any]:
    return _read_json(primitive_id, "defaults.json", kind=kind, theme=theme)


def list_effect_ids(theme: str | Path | None = None) -> list[str]:
    return list_primitive_ids("effects", theme=theme)


def read_effect_schema(effect_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_schema(effect_id, kind="effects", theme=theme)


def read_effect_meta(effect_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_meta(effect_id, kind="effects", theme=theme)


def read_effect_defaults(effect_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_defaults(effect_id, kind="effects", theme=theme)


def list_animation_ids(theme: str | Path | None = None) -> list[str]:
    return list_primitive_ids("animations", theme=theme)


def read_animation_schema(animation_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_schema(animation_id, kind="animations", theme=theme)


def read_animation_meta(animation_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_meta(animation_id, kind="animations", theme=theme)


def read_animation_defaults(animation_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_defaults(animation_id, kind="animations", theme=theme)


def list_transition_ids(theme: str | Path | None = None) -> list[str]:
    return list_primitive_ids("transitions", theme=theme)


def read_transition_schema(transition_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_schema(transition_id, kind="transitions", theme=theme)


def read_transition_meta(transition_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_meta(transition_id, kind="transitions", theme=theme)


def read_transition_defaults(transition_id: str, theme: str | Path | None = None) -> dict[str, Any]:
    return read_primitive_defaults(transition_id, kind="transitions", theme=theme)
