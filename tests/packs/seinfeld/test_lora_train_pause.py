"""Post-eval pipeline writes last_run.json with status=PAUSED and exits 0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.packs.seinfeld.orchestrators.lora_train import run as lora_run

from ._fixtures import make_dataset, make_vocab


def test_pause_after_eval_exits_zero_with_paused_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = make_dataset(tmp_path)
    vocab = make_vocab(tmp_path)
    out = tmp_path / "out"

    monkeypatch.setenv("RUNPOD_API_KEY", "test-key-rpa_dummy")

    # Stub repo_setup invocation
    monkeypatch.setattr(lora_run, "_invoke_repo_setup", lambda out_dir: 0)

    # Stub provision: create a fake pod_handle.json
    def fake_provision(args, out_dir):
        prov = out_dir / "provision"
        prov.mkdir(parents=True, exist_ok=True)
        handle = prov / "pod_handle.json"
        handle.write_text(json.dumps({"pod_id": "fake-pod"}) + "\n")
        return 0, handle

    monkeypatch.setattr(lora_run, "_provision", fake_provision)

    def fake_stage(args, out_dir, pod_handle):
        stage = out_dir / "stage"
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "staged_config.yaml").write_text("name: fake\n")
        (stage / "ui_url.txt").write_text("https://fake-pod-8675.proxy.runpod.net\n")
        return 0

    monkeypatch.setattr(lora_run, "_stage", fake_stage)

    def fake_train(args, out_dir, pod_handle):
        train = out_dir / "train"
        train.mkdir(parents=True, exist_ok=True)
        (train / "checkpoint_manifest.json").write_text(json.dumps({
            "checkpoints": [
                {"step": 500, "remote_path": "/workspace/output/step_500.safetensors"},
                {"step": 1000, "remote_path": "/workspace/output/step_1000.safetensors"},
            ],
            "status": "ok",
        }))
        return 0

    monkeypatch.setattr(lora_run, "_train", fake_train)

    def fake_eval(args, out_dir, pod_handle, cm, sc):
        eg = out_dir / "eval_grid"
        eg.mkdir(parents=True, exist_ok=True)
        (eg / "index.html").write_text("<html></html>")
        return 0

    monkeypatch.setattr(lora_run, "_eval_grid", fake_eval)

    rc = lora_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--out", str(out),
    ])
    assert rc == 0

    last = json.loads((out / "last_run.json").read_text(encoding="utf-8"))
    assert last["status"] == "PAUSED"
    for key in ("pod_handle", "staged_config", "checkpoint_manifest", "eval_grid_index", "vocabulary", "out"):
        assert key in last
        # Absolute paths
        assert Path(last[key]).is_absolute()
