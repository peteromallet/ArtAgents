"""Default --image is ostris/aitoolkit:latest and lands in last_run.json on dry-run."""

from __future__ import annotations

import json
from pathlib import Path

from astrid.packs.seinfeld.orchestrators.lora_train import run as lora_run

from ._fixtures import make_dataset, make_vocab


def test_default_image_is_pinned_in_dry_run_last_run(tmp_path: Path) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    out = tmp_path / "out"
    rc = lora_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--out", str(out),
        "--dry-run",
    ])
    assert rc == 0
    state = json.loads((out / "last_run.json").read_text(encoding="utf-8"))
    assert state["image"] == "ostris/aitoolkit:latest"
    assert lora_run.DEFAULT_IMAGE == "ostris/aitoolkit:latest"
