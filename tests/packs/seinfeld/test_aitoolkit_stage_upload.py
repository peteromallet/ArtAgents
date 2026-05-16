"""Dataset upload staging for seinfeld.aitoolkit_stage."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from astrid.packs.seinfeld.executors.aitoolkit_stage import run as stage_run

from ._fixtures import make_dataset, make_vocab


def _arg_value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_live_stage_uploads_smoke_dataset_after_bootstrap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = make_dataset(tmp_path, n_clips=6)
    vocab = make_vocab(tmp_path)
    produces = tmp_path / "produces"
    pod_handle = tmp_path / "pod_handle.json"
    pod_handle.write_text(json.dumps({"pod_id": "pod-123"}) + "\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        calls.append(argv)
        assert cwd == stage_run.REPO_ROOT
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(stage_run.subprocess, "run", fake_run)

    rc = stage_run.main([
        "--manifest", str(manifest),
        "--vocabulary", str(vocab),
        "--produces-dir", str(produces),
        "--pod-handle", str(pod_handle),
        "--dataset-remote-path", "/workspace/custom-dataset",
        "--smoke",
    ])

    assert rc == 0
    assert len(calls) == 2

    bootstrap_call, dataset_call = calls
    assert bootstrap_call[:4] == [
        sys.executable,
        "-m",
        "astrid.packs.external.executors.runpod.run",
        "exec",
    ]
    assert _arg_value(bootstrap_call, "--remote-root") == "/workspace"
    assert _arg_value(bootstrap_call, "--remote-script") == "bash /workspace/bootstrap.sh"

    assert dataset_call[:4] == bootstrap_call[:4]
    assert _arg_value(dataset_call, "--remote-root") == "/workspace/custom-dataset"
    assert _arg_value(dataset_call, "--upload-mode") == "sftp_walk"
    assert _arg_value(dataset_call, "--pod-handle") == str(pod_handle)
    assert Path(_arg_value(dataset_call, "--local-root")).name == "_dataset_staging"
    assert _arg_value(dataset_call, "--remote-script") == "echo dataset_staged 5 clips"

    staged_files = list((produces / "_dataset_staging" / "clips").iterdir())
    assert len([p for p in staged_files if p.suffix == ".mp4"]) == 5
    assert len([p for p in staged_files if p.name.endswith(".caption.json")]) == 5

    upload = json.loads((produces / "dataset_upload.json").read_text(encoding="utf-8"))
    assert upload["strategy"] == "copy_farm"
    assert upload["clips"] == 5
    assert upload["remote_root"] == "/workspace/custom-dataset"

    cfg = yaml.safe_load((produces / "staged_config.yaml").read_text(encoding="utf-8"))
    assert cfg["config"]["process"][0]["datasets"][0]["folder_path"] == "/workspace/custom-dataset"
