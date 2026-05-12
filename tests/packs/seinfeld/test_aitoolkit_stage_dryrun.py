"""Dry-run produces a parseable YAML with hivemind keys."""

from __future__ import annotations

from pathlib import Path

import yaml

from astrid.packs.seinfeld.aitoolkit_stage import run as stage_run

from ._fixtures import make_dataset, make_vocab


def test_dry_run_writes_parseable_yaml_with_hivemind_keys(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    produces = tmp_path / "produces"
    rc = stage_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--produces-dir", str(produces),
        "--dry-run",
    ])
    assert rc == 0

    staged = produces / "staged_config.yaml"
    bootstrap = produces / "bootstrap.sh"
    assert staged.is_file()
    assert bootstrap.is_file()

    cfg = yaml.safe_load(staged.read_text(encoding="utf-8"))
    proc = cfg["config"]["process"][0]

    assert proc["trigger_word"] == "seinfeld scene"
    assert proc["network"]["linear"] == 32
    assert proc["network"]["linear_alpha"] == 32
    assert proc["save"]["save_every"] == 250
    assert proc["sample"]["sample_every"] == 250
    assert proc["datasets"][0]["resolution"] == [512]
    assert proc["datasets"][0]["num_frames"] == 97
    assert proc["datasets"][0]["fps"] == 24
    assert proc["datasets"][0]["bucketing"] is True
    assert proc["train"]["steps"] == 2000
    assert proc["train"]["batch_size"] == 1
    assert proc["train"]["gradient_accumulation_steps"] == 4
    assert proc["train"]["lr"] == 2.0e-5
    assert proc["train"]["seed"] == 42
    assert proc["model"]["is_ltx"] is True
    assert proc["model"]["name_or_path"] == "Lightricks/LTX-2.3"
    assert proc["sample"]["width"] == 512
    assert proc["sample"]["height"] == 768
    assert len(proc["sample"]["prompts"]) >= 3

    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    assert "/proc/1/environ" in bootstrap_text
    assert '$TOOLKIT_ROOT/.env' in bootstrap_text
    assert "hf_test_token" not in bootstrap_text


def test_dry_run_smoke_overrides_steps_to_100(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    produces = tmp_path / "produces"
    rc = stage_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--produces-dir", str(produces),
        "--dry-run",
        "--smoke",
    ])
    assert rc == 0
    cfg = yaml.safe_load((produces / "staged_config.yaml").read_text(encoding="utf-8"))
    assert cfg["config"]["process"][0]["train"]["steps"] == 100
