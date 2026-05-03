"""Loud fallback renderer for unsupported artifact kinds."""

from __future__ import annotations

from html import escape

ID = "generic_card"
NAME = "Generic Card"
KINDS = ("*",)
CLIP_MODES = ("card",)
PRODUCES_AUDIO = False
COST_HINT = "local"
FALLBACK = True
LOUD_FALLBACK = True


def default_clip_mode_for(shape: str | None = None, style: str | None = None) -> str:
    return "card"


def fallback_diagnostic(kind: str | None) -> str:
    return f"no renderer for kind:{kind or 'unknown'}"


def fallback_aside(kind: str | None) -> str:
    return f'<aside class="renderer-fallback">{escape(fallback_diagnostic(kind))}</aside>'


def render_payload(artifact: dict) -> dict:
    kind = artifact.get("kind")
    return {
        "renderer": ID,
        "kind": kind,
        "clip_mode": default_clip_mode_for(),
        "fallback": True,
        "diagnostic": fallback_diagnostic(kind),
        "html_aside": fallback_aside(kind),
    }
