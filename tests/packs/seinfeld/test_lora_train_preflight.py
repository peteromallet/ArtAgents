"""Preflight fails on missing caption sidecar / clip file."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from astrid.packs.seinfeld.orchestrators.lora_train import run as lora_run

from ._fixtures import make_dataset, make_vocab


def _run_dryrun(tmp_path: Path, manifest: Path, vocab: Path) -> int:
    out = tmp_path / "out"
    return lora_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--out", str(out),
        "--dry-run",
    ])


def test_preflight_fails_on_missing_caption_sidecar(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    # Delete one caption sidecar
    (tmp_path / "clips" / "clip_000.caption.json").unlink()
    rc = _run_dryrun(tmp_path, manifest, vocab)
    assert rc != 0


def test_preflight_fails_on_missing_clip_file(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    (tmp_path / "clips" / "clip_001.mp4").unlink()
    rc = _run_dryrun(tmp_path, manifest, vocab)
    assert rc != 0


def test_preflight_passes_with_intact_dataset(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    rc = _run_dryrun(tmp_path, manifest, vocab)
    assert rc == 0
    cfg = yaml.safe_load((tmp_path / "out" / "stage" / "staged_config.yaml").read_text(encoding="utf-8"))
    assert cfg["config"]["process"][0]["model"]["name_or_path"] == "Lightricks/LTX-2.3/ltx-2.3-22b-dev.safetensors"
