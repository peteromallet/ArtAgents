"""lora_register writes registered_lora.json with the required schema."""

from __future__ import annotations

import json
from pathlib import Path

from astrid.packs.seinfeld.executors.lora_register import run as reg_run

from ._fixtures import make_vocab


REQUIRED_KEYS = {
    "lora_id", "checkpoint_step", "lora_file", "config_used",
    "base_model", "vocabulary_hash", "trained_at", "human_pick_notes",
}


def test_register_writes_full_schema(tmp_path: Path) -> None:
    vocab = make_vocab(tmp_path)
    lora_src = tmp_path / "step_1500.safetensors"
    lora_src.write_bytes(b"\x00\x01\x02")
    staged_config = tmp_path / "staged_config.yaml"
    staged_config.write_text("name: fake\n")

    chosen = tmp_path / "chosen.json"
    chosen.write_text(json.dumps({"step": 1500, "notes": "best identity"}))

    produces = tmp_path / "produces"
    rc = reg_run.main([
        "--chosen-checkpoint", str(chosen),
        "--lora-source", str(lora_src),
        "--staged-config", str(staged_config),
        "--vocabulary", str(vocab),
        "--produces-dir", str(produces),
        "--base-model", "ltx-2.3",
        "--lora-id", "seinfeld-scene-v1",
    ])
    assert rc == 0

    record = json.loads((produces / "registered_lora.json").read_text(encoding="utf-8"))
    assert REQUIRED_KEYS.issubset(record.keys())
    assert record["checkpoint_step"] == 1500
    assert record["base_model"] == "ltx-2.3"
    assert record["lora_id"] == "seinfeld-scene-v1"
    assert record["human_pick_notes"] == "best identity"
    assert len(record["vocabulary_hash"]) == 64  # SHA-256 hex
    assert (produces / "registered" / "seinfeld-scene-v1.safetensors").is_file()
