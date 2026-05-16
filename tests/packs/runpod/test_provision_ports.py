"""--ports flows into pod_handle.json config_snapshot; default preserved when omitted."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def produces_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mock_pod() -> MagicMock:
    pod = MagicMock()
    pod.id = "pod-ports-test"
    pod.name = "astrid-ports-test"
    pod._storage_volume = None
    pod.wait_ready = AsyncMock()
    pod._ensure_ssh_details = AsyncMock(return_value={"ip": "1.2.3.4", "port": 2222})
    return pod


def _run_provision(produces: Path, ports: str | None, mock_pod: MagicMock) -> dict:
    mock_launch = AsyncMock(return_value=mock_pod)
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"
    try:
        with patch("runpod_lifecycle.launch", mock_launch), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_provision

            class Args:
                gpu_type = "NVIDIA GeForce RTX 4090"
                storage_name = None
                max_runtime_seconds = None
                name_prefix = None
                image = None
                container_disk_gb = None
                datacenter_id = None
                produces_dir = produces
            args = Args()
            args.ports = ports
            rc = cmd_provision(args, produces)
            assert rc == 0
            return json.loads((produces / "pod_handle.json").read_text())
    finally:
        os.environ.pop("RUNPOD_API_KEY", None)


def test_ports_flag_appears_in_snapshot(produces_dir: Path, mock_pod: MagicMock) -> None:
    handle = _run_provision(produces_dir, "8675/http,22/tcp", mock_pod)
    assert "8675/http" in handle["config_snapshot"]["ports"]
    assert handle["config_snapshot"]["ports"] == "8675/http,22/tcp"


def test_ports_default_unchanged_when_omitted(produces_dir: Path, mock_pod: MagicMock) -> None:
    handle = _run_provision(produces_dir, None, mock_pod)
    assert handle["config_snapshot"]["ports"] == "8888/http,22/tcp"
