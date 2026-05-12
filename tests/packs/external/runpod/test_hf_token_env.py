"""HF_TOKEN is threaded into RunPod config without serializing the secret."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from astrid.packs.external.runpod import run as runpod_run


def test_host_hf_token_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert runpod_run._host_hf_token_env_vars() == {}

    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    assert runpod_run._host_hf_token_env_vars() == {"HF_TOKEN": "hf_test_token"}


def test_load_handle_and_config_rehydrates_hf_token(monkeypatch, tmp_path: Path) -> None:
    class FakeRunPodConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.env_vars = kwargs.get("env_vars")

    fake_module = types.ModuleType("runpod_lifecycle")
    fake_module.RunPodConfig = FakeRunPodConfig
    monkeypatch.setitem(sys.modules, "runpod_lifecycle", fake_module)
    monkeypatch.setenv("RUNPOD_API_KEY", "rp_test_key")
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")

    handle_path = tmp_path / "pod_handle.json"
    handle_path.write_text(
        json.dumps(
            {
                "pod_id": "pod-test",
                "gpu_type": "NVIDIA A40",
                "config_snapshot": {
                    "api_key_ref": "RUNPOD_API_KEY",
                    "container_disk_in_gb": 200,
                },
            }
        ),
        encoding="utf-8",
    )

    handle, config = runpod_run._load_handle_and_config(handle_path)

    assert handle["pod_id"] == "pod-test"
    assert config.env_vars == {"HF_TOKEN": "hf_test_token"}
    assert "hf_test_token" not in handle_path.read_text(encoding="utf-8")
