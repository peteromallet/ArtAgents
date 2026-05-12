"""Shared fixtures for seinfeld pack tests."""

from __future__ import annotations

import json
from pathlib import Path

VOCAB_YAML = """\
version: 0.0.0-draft
scenes:
  jerrys_apt: "Jerry's apartment"
  monks_diner: "Monk's coffee shop"
characters:
  jerry: {description: "Mid-30s male"}
  george: {description: "Short stocky"}
shot_types:
  wide: "Wide framing"
  medium: "Medium two-shot"
"""


def make_dataset(root: Path, n_clips: int = 6) -> Path:
    """Create a fake dataset with n clips + caption sidecars.

    Returns the manifest path.
    """
    clips_dir = root / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for i in range(n_clips):
        clip_id = f"clip_{i:03d}"
        clip_file = clips_dir / f"{clip_id}.mp4"
        clip_file.write_bytes(b"\x00")  # placeholder
        cap = clips_dir / f"{clip_id}.caption.json"
        cap.write_text(
            json.dumps({"caption": "seinfeld scene, jerry talking in jerrys_apt"}) + "\n",
            encoding="utf-8",
        )
        clips.append({"clip_id": clip_id, "clip_file": str(clip_file)})
    manifest = root / "provisional.manifest.json"
    manifest.write_text(json.dumps({"clips": clips}) + "\n", encoding="utf-8")
    return manifest


def make_vocab(root: Path) -> Path:
    vp = root / "vocabulary.yaml"
    vp.write_text(VOCAB_YAML, encoding="utf-8")
    return vp
