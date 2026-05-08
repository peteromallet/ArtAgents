"""Modality renderer registry for iteration video planning."""

from __future__ import annotations

import argparse
import json
import sys
from types import ModuleType

from . import audio_waveform, generic_card, image_grid


_RENDERERS: tuple[ModuleType, ...] = (image_grid, audio_waveform, generic_card)


def renderer_ids() -> list[str]:
    return [str(renderer.ID) for renderer in _RENDERERS]


def list_renderers() -> list[dict]:
    return [_renderer_summary(renderer) for renderer in _RENDERERS]


def fallback_chain() -> list[str]:
    return renderer_ids()


def inspect_renderer(renderer_id: str) -> dict:
    for renderer in _RENDERERS:
        if renderer.ID == renderer_id:
            payload = _renderer_summary(renderer)
            payload["module"] = renderer.__name__
            payload["default_clip_mode"] = renderer.default_clip_mode_for()
            if getattr(renderer, "FALLBACK", False):
                payload["loud_fallback"] = bool(getattr(renderer, "LOUD_FALLBACK", False))
                payload["diagnostic"] = renderer.fallback_diagnostic("unknown")
                payload["html_aside"] = renderer.fallback_aside("unknown")
            return payload
    raise KeyError(renderer_id)


def resolve_renderer_for_kind(kind: str | None) -> dict:
    for renderer in _RENDERERS:
        if getattr(renderer, "FALLBACK", False):
            continue
        if kind in renderer.KINDS:
            return _resolution(renderer, kind, fallback=False)
    return _resolution(generic_card, kind, fallback=True)


def resolve_artifact(artifact: dict) -> dict:
    resolution = resolve_renderer_for_kind(artifact.get("kind"))
    renderer = _module_by_id(resolution["renderer"])
    resolution["payload"] = renderer.render_payload(artifact)
    return resolution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m astrid modalities", description="Astrid modality renderers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List registered modality renderers")
    list_parser.add_argument("--json", action="store_true", help="Print renderer declarations as JSON")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a modality renderer")
    inspect_parser.add_argument("renderer", help="Renderer id")
    inspect_parser.add_argument("--json", action="store_true", help="Print renderer declaration as JSON")

    args = parser.parse_args(argv)
    if args.command == "list":
        payload = {"renderers": list_renderers()}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for renderer in payload["renderers"]:
                fallback = " fallback" if renderer["fallback"] else ""
                kinds = ",".join(renderer["kinds"])
                print(f"{renderer['id']}\t{kinds}{fallback}")
        return 0
    if args.command == "inspect":
        try:
            payload = inspect_renderer(args.renderer)
        except KeyError:
            print(f"Unknown modality renderer: {args.renderer}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_inspect(payload)
        return 0
    parser.print_help()
    return 2


def _renderer_summary(renderer: ModuleType) -> dict:
    return {
        "id": renderer.ID,
        "name": renderer.NAME,
        "kinds": list(renderer.KINDS),
        "clip_modes": list(renderer.CLIP_MODES),
        "produces_audio": bool(renderer.PRODUCES_AUDIO),
        "cost_hint": renderer.COST_HINT,
        "fallback": bool(getattr(renderer, "FALLBACK", False)),
    }


def _resolution(renderer: ModuleType, kind: str | None, *, fallback: bool) -> dict:
    payload = {
        "kind": kind,
        "renderer": renderer.ID,
        "clip_mode": renderer.default_clip_mode_for(),
        "fallback": fallback,
    }
    if fallback:
        payload["diagnostic"] = renderer.fallback_diagnostic(kind)
        payload["html_aside"] = renderer.fallback_aside(kind)
    return payload


def _module_by_id(renderer_id: str) -> ModuleType:
    for renderer in _RENDERERS:
        if renderer.ID == renderer_id:
            return renderer
    raise KeyError(renderer_id)


def _print_inspect(payload: dict) -> None:
    print(f"id: {payload['id']}")
    print(f"name: {payload['name']}")
    print(f"kinds: {', '.join(payload['kinds'])}")
    print(f"clip_modes: {', '.join(payload['clip_modes'])}")
    print(f"produces_audio: {str(payload['produces_audio']).lower()}")
    print(f"cost_hint: {payload['cost_hint']}")
    print(f"fallback: {str(payload['fallback']).lower()}")
    if payload.get("fallback"):
        print("loud_fallback: true")
        print(f"diagnostic: {payload['diagnostic']}")


__all__ = [
    "fallback_chain",
    "inspect_renderer",
    "list_renderers",
    "main",
    "renderer_ids",
    "resolve_artifact",
    "resolve_renderer_for_kind",
]
