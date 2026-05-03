"""Declarative renderer for image artifacts in iteration videos."""

from __future__ import annotations

ID = "image_grid"
NAME = "Image Grid"
KINDS = ("image",)
CLIP_MODES = ("grid",)
PRODUCES_AUDIO = False
COST_HINT = "local"
FALLBACK = False


def default_clip_mode_for(shape: str | None = None, style: str | None = None) -> str:
    return "grid"


def render_payload(artifact: dict) -> dict:
    return {
        "renderer": ID,
        "kind": artifact.get("kind"),
        "clip_mode": default_clip_mode_for(),
        "fallback": False,
    }
