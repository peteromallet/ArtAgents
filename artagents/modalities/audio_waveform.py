"""Declarative renderer for audio artifacts in iteration videos."""

from __future__ import annotations

ID = "audio_waveform"
NAME = "Audio Waveform"
KINDS = ("audio",)
CLIP_MODES = ("waveform",)
PRODUCES_AUDIO = True
COST_HINT = "local"
FALLBACK = False


def default_clip_mode_for(shape: str | None = None, style: str | None = None) -> str:
    return "waveform"


def render_payload(artifact: dict) -> dict:
    return {
        "renderer": ID,
        "kind": artifact.get("kind"),
        "clip_mode": default_clip_mode_for(),
        "fallback": False,
    }
