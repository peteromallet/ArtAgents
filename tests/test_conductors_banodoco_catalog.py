import json
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from artagents.conductors.registry import load_default_registry
from artagents.conductors.banodoco_catalog import (
    BanodocoCatalogConfig,
    BanodocoCatalogError,
    GitConductorSource,
    fetch_git_conductor_manifest,
    load_banodoco_catalog_conductors,
)
from artagents.performers.install import PerformerInstallError


class _UrlOpenResponse:
    def __init__(self, payload: dict) -> None:
        self._body = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "_UrlOpenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.read()


def _init_manifest_repo(root: Path, name: str, manifest: dict) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    (repo / name).write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "conductor"], cwd=repo, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    return repo, commit


def _conductor_manifest(conductor_id: str) -> dict:
    return {
        "id": conductor_id,
        "name": "Catalog Conductor",
        "kind": "external",
        "version": "1",
        "runtime": {"kind": "command", "command": {"argv": ["echo", "ok"]}},
        "cache": {"mode": "none"},
    }


class BanodocoConductorCatalogTest(unittest.TestCase):
    def test_default_registry_does_not_fetch_banodoco_catalog_by_default(self) -> None:
        with mock.patch("artagents.performers.banodoco_catalog.urllib.request.urlopen") as urlopen:
            registry = load_default_registry()

        self.assertIn("builtin.hype", {conductor.id for conductor in registry.list()})
        urlopen.assert_not_called()

    def test_git_conductor_manifest_requires_exactly_one_ref_and_checks_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _init_manifest_repo(root, "conductor.json", _conductor_manifest("external.git_conductor"))

            loaded = fetch_git_conductor_manifest(
                GitConductorSource(
                    repo_url=str(repo),
                    manifest_path="conductor.json",
                    expected_conductor_id="external.git_conductor",
                    commit_sha=commit,
                ),
                cache_dir=root / "cache",
            )

        self.assertEqual(loaded["id"], "external.git_conductor")

    def test_git_conductor_manifest_rejects_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _init_manifest_repo(root, "conductor.json", _conductor_manifest("external.actual"))

            with self.assertRaisesRegex(PerformerInstallError, "identity mismatch"):
                fetch_git_conductor_manifest(
                    GitConductorSource(
                        repo_url=str(repo),
                        manifest_path="conductor.json",
                        expected_conductor_id="external.expected",
                        commit_sha=commit,
                    ),
                    cache_dir=root / "cache",
                )

    def test_banodoco_catalog_loads_default_git_conductor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _init_manifest_repo(root, "conductor.json", _conductor_manifest("external.catalog_conductor"))
            payload = {
                "conductors": [
                    {
                        "id": "catalog-row",
                        "slug": "catalog-conductor",
                        "expected_manifest_id": "external.catalog_conductor",
                        "catalog": {"default": True, "mandatory": False},
                        "install_targets": [
                            {
                                "source_type": "git",
                                "repo_url": str(repo),
                                "manifest_path": "conductor.json",
                                "expected_conductor_id": "external.catalog_conductor",
                                "ref": {"commit_sha": commit},
                            }
                        ],
                    }
                ]
            }

            with mock.patch("artagents.performers.banodoco_catalog.urllib.request.urlopen", return_value=_UrlOpenResponse(payload)):
                conductors = load_banodoco_catalog_conductors(
                    BanodocoCatalogConfig(
                        enabled=True,
                        catalog_url="https://example.test/functions/v1/agent-catalog",
                        cache_dir=root / "cache",
                    )
                )

        self.assertEqual(conductors[0].id, "external.catalog_conductor")
        self.assertEqual(conductors[0].metadata["source"], "banodoco_catalog")

    def test_banodoco_catalog_requires_url_when_enabled(self) -> None:
        with self.assertRaisesRegex(BanodocoCatalogError, "CATALOG_URL"):
            load_banodoco_catalog_conductors(BanodocoCatalogConfig(enabled=True))


if __name__ == "__main__":
    unittest.main()
