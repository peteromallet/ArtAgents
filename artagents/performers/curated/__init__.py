"""Curated external performer manifests bundled with ArtAgents."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def manifest_paths() -> list[Path]:
    """Return curated manifest paths available from a source checkout."""

    root = resources.files(__package__)
    return sorted(Path(str(item)) for item in root.iterdir() if item.name.endswith(".json"))


__all__ = ["manifest_paths"]
