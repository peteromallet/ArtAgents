import json
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from artagents.performers.banodoco_catalog import BanodocoCatalogConfig, BanodocoCatalogError, load_banodoco_catalog_performers
from artagents.performers.install import GitPerformerSource, PerformerInstallError, fetch_git_performer_manifest
from artagents.performers.registry import load_default_registry


class _UrlOpenResponse:
    def __init__(self, payload: dict) -> None:
        self._body = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "_UrlOpenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.read()


class BanodocoCatalogTest(unittest.TestCase):
    def test_default_registry_does_not_fetch_banodoco_catalog_by_default(self) -> None:
        with mock.patch("artagents.performers.banodoco_catalog.urllib.request.urlopen") as urlopen:
            registry = load_default_registry()

        self.assertIn("builtin.render", {performer.id for performer in registry.list()})
        urlopen.assert_not_called()

    def test_git_performer_manifest_requires_exactly_one_ref_and_checks_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            cache = Path(tmp) / "cache"
            repo.mkdir()
            manifest = {
                "id": "external.git_example",
                "name": "Git Example",
                "kind": "external",
                "version": "1",
                "command": {"argv": ["echo", "ok"]},
                "cache": {"mode": "none"},
            }
            (repo / "performer.json").write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "performer.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "performer"], cwd=repo, check=True, capture_output=True)
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

            loaded = fetch_git_performer_manifest(
                GitPerformerSource(
                    repo_url=str(repo),
                    manifest_path="performer.json",
                    expected_performer_id="external.git_example",
                    commit_sha=commit,
                ),
                cache_dir=cache,
            )

        self.assertEqual(loaded["id"], "external.git_example")

    def test_git_performer_manifest_rejects_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "performer.json").write_text(
                json.dumps({"id": "external.actual", "name": "Actual", "kind": "external", "version": "1"}),
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "performer.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "performer"], cwd=repo, check=True, capture_output=True)
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

            with self.assertRaisesRegex(PerformerInstallError, "identity mismatch"):
                fetch_git_performer_manifest(
                    GitPerformerSource(
                        repo_url=str(repo),
                        manifest_path="performer.json",
                        expected_performer_id="external.expected",
                        commit_sha=commit,
                    ),
                    cache_dir=Path(tmp) / "cache",
                )

    def test_banodoco_catalog_loads_default_git_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            manifest = {
                "id": "external.catalog_example",
                "name": "Catalog Example",
                "kind": "external",
                "version": "1",
                "command": {"argv": ["echo", "ok"]},
                "cache": {"mode": "none"},
            }
            (repo / "performer.json").write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "performer.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "performer"], cwd=repo, check=True, capture_output=True)
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            payload = {
                "performers": [
                    {
                        "id": "catalog-row",
                        "slug": "catalog-example",
                        "expected_manifest_id": "external.catalog_example",
                        "catalog": {"default": True, "mandatory": False},
                        "install_targets": [
                            {
                                "source_type": "git",
                                "repo_url": str(repo),
                                "manifest_path": "performer.json",
                                "expected_performer_id": "external.catalog_example",
                                "ref": {"commit_sha": commit},
                            }
                        ],
                    }
                ]
            }

            with mock.patch("artagents.performers.banodoco_catalog.urllib.request.urlopen", return_value=_UrlOpenResponse(payload)):
                performers = load_banodoco_catalog_performers(
                    BanodocoCatalogConfig(
                        enabled=True,
                        catalog_url="https://example.test/functions/v1/agent-performer-catalog",
                        cache_dir=Path(tmp) / "cache",
                    )
                )

        self.assertEqual(performers[0].id, "external.catalog_example")
        self.assertEqual(performers[0].metadata["source"], "banodoco_catalog")

    def test_banodoco_catalog_requires_url_when_enabled(self) -> None:
        with self.assertRaisesRegex(BanodocoCatalogError, "CATALOG_URL"):
            load_banodoco_catalog_performers(BanodocoCatalogConfig(enabled=True))


if __name__ == "__main__":
    unittest.main()
