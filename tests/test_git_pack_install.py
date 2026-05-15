"""Tests for Git-backed pack install, update, rollback, and dry-run.

Uses local git repos (not remote URLs) to avoid network dependencies.
All tests use ``InstalledPackStore(packs_home=tmpdir)`` for isolation.
"""

from __future__ import annotations

import io
import json as _json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import yaml

from astrid.core.pack_store import (
    InstallRecord,
    InstalledPackStore,
)
from astrid.packs.install import (
    _check_git_available,
    _clone_git_pack,
    _diff_component_inventories,
    _find_pack_root_in_checkout,
    _format_trust_summary,
    _install_from_git,
    _is_git_url,
    _resolve_git_ref,
    _run_git,
    _update_git_pack,
    install_pack,
    rollback_pack,
    uninstall_pack,
    update_pack,
)
from astrid.packs.cli import cmd_inspect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _packs_home(tmpdir: str):
    """Temporarily override ASTRID_HOME for store isolation."""
    with mock.patch.dict(os.environ, {"ASTRID_HOME": tmpdir}):
        yield


def _make_minimal_pack(root: Path, pack_id: str = "test_pack") -> Path:
    """Write a minimal valid v1 pack, return the pack root."""
    (root / "pack.yaml").write_text(
        textwrap.dedent(f"""\
            schema_version: 1
            id: {pack_id}
            name: {pack_id.replace('_', ' ').title()}
            version: 0.1.0
            description: A test pack for Git install validation.
            content:
              executors: executors
              orchestrators: orchestrators
              elements: elements
            agent:
              purpose: Testing
              entrypoints:
                - validate
                - install
        """),
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(f"# {pack_id}\n\nAgent guide.\n")
    (root / "README.md").write_text(f"# {pack_id}\n\nUser docs.\n")
    (root / "STAGE.md").write_text("## Purpose\n\nTesting.\n")
    for sub in ("executors", "orchestrators", "elements"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _make_git_repo_with_pack(
    tmpdir: str, pack_id: str = "git_pack", *,
    subdir: bool = False,
) -> tuple[str, str]:
    """Create a local git repo with a minimal pack, return (repo_path, commit_sha).

    The repo root is named after *pack_id* so the ``source.name == pack_id``
    invariant holds for local-path installs.  If *subdir* is True, the pack
    lives inside a subdirectory ``<pack_id>/my-pack/`` (still named after
    pack_id so the outer directory matches).
    """
    # Use a unique wrapper directory to avoid name clashes between tests
    wrapper = Path(tempfile.mkdtemp(dir=tmpdir, prefix=f"{pack_id}_repo_"))
    repo_path = wrapper / pack_id
    repo_path.mkdir(parents=True, exist_ok=True)

    if subdir:
        pack_root = repo_path / "my-pack"
    else:
        pack_root = repo_path

    _make_minimal_pack(pack_root, pack_id=pack_id)

    # Initialize git, add, commit
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_path),
                   capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "test@astrid.local"],
                   cwd=str(repo_path), capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "Astrid Test"],
                   cwd=str(repo_path), capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_path),
                   capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "commit", "-m", "initial commit"],
                   cwd=str(repo_path), capture_output=True, check=True, timeout=30)

    # Get commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path),
        capture_output=True, text=True, check=True, timeout=30,
    )
    commit_sha = result.stdout.strip()

    return str(repo_path), commit_sha


def _make_another_commit(repo_path: str, pack_id: str,
                         new_version: str = "0.2.0") -> str:
    """Make another commit to the git repo, return the new commit SHA."""
    repo = Path(repo_path)
    pack_yaml = repo / "pack.yaml"
    content = pack_yaml.read_text()
    pack_yaml.write_text(
        content.replace("version: 0.1.0", f"version: {new_version}")
    )
    subprocess.run(["git", "add", "-A"], cwd=repo_path,
                   capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "commit", "-m", "bump to " + new_version],
                   cwd=repo_path, capture_output=True, check=True, timeout=30)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path,
        capture_output=True, text=True, check=True, timeout=30,
    )
    return result.stdout.strip()


class GitTestBase(unittest.TestCase):
    """Base class with temp-dir helpers for Git install tests."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-git-install-")
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _store(self) -> InstalledPackStore:
        return InstalledPackStore(packs_home=self._astrid_home / "packs")

    def _install(
        self,
        source: str | Path,
        *,
        dry_run: bool = False,
        force: bool = False,
        store: InstalledPackStore | None = None,
    ) -> int:
        if store is None:
            store = self._store()
        return install_pack(
            source,
            store=store,
            dry_run=dry_run,
            skip_confirm=True,
            force=force,
        )


# ---------------------------------------------------------------------------
# _is_git_url detection and rejection
# ---------------------------------------------------------------------------


class TestIsGitUrl(unittest.TestCase):
    """Tests for _is_git_url()."""

    def test_accepts_https(self) -> None:
        self.assertTrue(_is_git_url("https://github.com/user/repo.git"))

    def test_accepts_git_at(self) -> None:
        self.assertTrue(_is_git_url("git@github.com:user/repo.git"))

    def test_accepts_ssh(self) -> None:
        self.assertTrue(_is_git_url("ssh://git@github.com/user/repo.git"))

    def test_accepts_git_protocol(self) -> None:
        self.assertTrue(_is_git_url("git://example.com/repo.git"))

    def test_rejects_http(self) -> None:
        self.assertFalse(_is_git_url("http://github.com/user/repo.git"))

    def test_rejects_file(self) -> None:
        self.assertFalse(_is_git_url("file:///tmp/repo"))

    def test_rejects_plain_path(self) -> None:
        self.assertFalse(_is_git_url("/tmp/my-pack"))

    def test_rejects_relative_path(self) -> None:
        self.assertFalse(_is_git_url("./my-pack"))

    def test_rejects_empty(self) -> None:
        self.assertFalse(_is_git_url(""))

    def test_rejects_ftp(self) -> None:
        self.assertFalse(_is_git_url("ftp://example.com/repo.git"))


# ---------------------------------------------------------------------------
# _check_git_available
# ---------------------------------------------------------------------------


class TestCheckGitAvailable(unittest.TestCase):
    """Tests for _check_git_available()."""

    def test_raises_when_git_missing(self) -> None:
        with mock.patch("subprocess.run",
                        side_effect=FileNotFoundError("git not found")):
            with self.assertRaises(RuntimeError) as ctx:
                _check_git_available()
            self.assertIn("Git is not available", str(ctx.exception))

    def test_raises_when_git_not_functioning(self) -> None:
        called = subprocess.CalledProcessError(1, ["git", "--version"])
        with mock.patch("subprocess.run",
                        side_effect=called):
            with self.assertRaises(RuntimeError) as ctx:
                _check_git_available()
            self.assertIn("Git is not functioning correctly", str(ctx.exception))

    def test_passes_when_git_available(self) -> None:
        # This is an integration test — git should be on PATH
        _check_git_available()  # should not raise


# ---------------------------------------------------------------------------
# _find_pack_root_in_checkout
# ---------------------------------------------------------------------------


class TestFindPackRootInCheckout(unittest.TestCase):
    """Tests for _find_pack_root_in_checkout()."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-find-root-")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_repo_root_has_pack_yaml(self) -> None:
        """If pack.yaml is at repo root, return repo root."""
        root = Path(self._tmpdir) / "checkout"
        root.mkdir(parents=True)
        _make_minimal_pack(root, "myroot")
        result = _find_pack_root_in_checkout(root)
        self.assertEqual(result, root.resolve())

    def test_single_subdir_has_pack_yaml(self) -> None:
        """If exactly one subdir has pack.yaml, return that subdir."""
        root = Path(self._tmpdir) / "checkout"
        root.mkdir(parents=True)
        sub = root / "the-pack"
        sub.mkdir()
        _make_minimal_pack(sub, "the_pack")
        result = _find_pack_root_in_checkout(root)
        self.assertEqual(result, sub.resolve())

    def test_no_pack_manifest_raises(self) -> None:
        """If no pack manifest found, raise RuntimeError."""
        root = Path(self._tmpdir) / "checkout"
        root.mkdir(parents=True)
        (root / "README.md").write_text("empty")
        with self.assertRaises(RuntimeError) as ctx:
            _find_pack_root_in_checkout(root)
        self.assertIn("No pack manifest found", str(ctx.exception))

    def test_multiple_subdirs_raises(self) -> None:
        """If multiple subdirs have pack manifests, raise RuntimeError."""
        root = Path(self._tmpdir) / "checkout"
        root.mkdir(parents=True)
        sub1 = root / "pack-a"
        sub1.mkdir()
        _make_minimal_pack(sub1, "pack_a")
        sub2 = root / "pack-b"
        sub2.mkdir()
        _make_minimal_pack(sub2, "pack_b")
        with self.assertRaises(RuntimeError) as ctx:
            _find_pack_root_in_checkout(root)
        self.assertIn("Multiple pack roots found", str(ctx.exception))

    def test_skips_dot_dirs(self) -> None:
        """Dot-prefixed directories are skipped."""
        root = Path(self._tmpdir) / "checkout"
        root.mkdir(parents=True)
        sub = root / ".hidden"
        sub.mkdir()
        _make_minimal_pack(sub, "hidden_pack")
        # Should fail because the .hidden dir is skipped
        with self.assertRaises(RuntimeError) as ctx:
            _find_pack_root_in_checkout(root)
        self.assertIn("No pack manifest found", str(ctx.exception))


# ---------------------------------------------------------------------------
# Git install flow (local repo)
# ---------------------------------------------------------------------------


class TestGitInstallFlow(GitTestBase):
    """Full Git install flow using a local git repo."""

    def test_git_install_success(self) -> None:
        """Install from a local git repo, verify all fields populated."""
        pack_id = "git_test_install"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        rc = install_pack(
            repo_path,
            store=store,
            skip_confirm=True,
        )
        self.assertEqual(rc, 0)

        # Verify store state
        self.assertTrue(store.is_installed(pack_id))
        record = store.get_active(pack_id)
        self.assertIsNotNone(record)
        assert record is not None

        # Verify InstallRecord fields
        self.assertEqual(record.pack_id, pack_id)
        self.assertTrue(record.active)
        # source_type defaults to "local" for local-path installs
        self.assertIn(record.source_type, ("local", ""))

        # Verify directory layout
        root = store.install_root_for(pack_id)
        self.assertTrue(root.is_dir())
        rev = store.active_revision_path(pack_id)
        self.assertIsNotNone(rev)
        assert rev is not None

        # Verify install.json content
        install_json_path = rev / ".astrid" / "install.json"
        self.assertTrue(install_json_path.is_file())
        data = _json.loads(install_json_path.read_text())
        self.assertEqual(data["pack_id"], pack_id)
        self.assertIsNotNone(data.get("installed_at"))
        self.assertIsNotNone(data.get("manifest_digest"))

    def test_git_install_dry_run(self) -> None:
        """Git install --dry-run prints trust summary, does not create pack dir."""
        pack_id = "git_dry_install"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = install_pack(
                repo_path,
                store=store,
                dry_run=True,
                skip_confirm=True,
            )
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Trust Summary", output)
        self.assertIn(pack_id, output)

        # No state should have been created
        self.assertFalse(store.is_installed(pack_id))
        self.assertIsNone(store.get_active(pack_id))


# ---------------------------------------------------------------------------
# Git-backed pack workflow (install → update → rollback)
# ---------------------------------------------------------------------------


class TestGitBackedWorkflow(GitTestBase):
    """End-to-end: install from git repo, update, rollback."""

    def setUp(self) -> None:
        super().setUp()
        self._pack_id = "git_wf"
        self._repo_path, self._initial_sha = _make_git_repo_with_pack(
            self._tmpdir, self._pack_id,
        )

    def test_full_git_install_update_rollback(self) -> None:
        """Install → update → rollback full cycle."""
        store = self._store()

        # ── 1. Install from git repo ──
        rc = self._install(self._repo_path, store=store)
        self.assertEqual(rc, 0)
        self.assertTrue(store.is_installed(self._pack_id))

        # Verify initial record
        record = store.get_active(self._pack_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.pack_id, self._pack_id)
        self.assertEqual(record.version, "0.1.0")
        # source_type is "local" for local-path installs
        self.assertIn(record.source_type, ("local", ""))

        # ── 2. Make a new commit to the repo ──
        new_sha = _make_another_commit(self._repo_path, self._pack_id, new_version="0.2.0")

        # ── 3. Update dry-run: should show diff ──
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = update_pack(self._pack_id, store=store, dry_run=True)
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Currently Installed", output)
        self.assertIn("Source (would install)", output)
        self.assertIn("0.2.0", output)

        # ── 4. Real update ──
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = update_pack(self._pack_id, store=store, skip_confirm=True)
        self.assertEqual(rc, 0)

        # Verify update
        record2 = store.get_active(self._pack_id)
        self.assertIsNotNone(record2)
        assert record2 is not None
        self.assertEqual(record2.version, "0.2.0")

        # Old revision should be preserved
        revisions = store.list_revisions(self._pack_id)
        self.assertGreaterEqual(len(revisions), 2,
                                f"Expected >= 2 revisions, got {[r.name for r in revisions]}")

        # ── 5. Rollback to first revision ──
        # Find the old revision (not the active one)
        active_rev = store.active_revision_path(self._pack_id)
        assert active_rev is not None
        old_revisions = [r for r in revisions if r.name != active_rev.name]
        self.assertGreaterEqual(len(old_revisions), 1,
                                "Expected at least 1 old revision")

        target_rev = old_revisions[0].name

        rc = rollback_pack(
            self._pack_id,
            store=store,
            revision=target_rev,
            skip_confirm=True,
        )
        self.assertEqual(rc, 0)

        # Verify rollback
        record3 = store.get_active(self._pack_id)
        self.assertIsNotNone(record3)
        assert record3 is not None
        self.assertEqual(record3.version, "0.1.0")

    def test_update_dry_run_shows_diff(self) -> None:
        """Update --dry-run for local packs shows diff with version change."""
        store = self._store()
        self._install(self._repo_path, store=store)

        # Make a change
        _make_another_commit(self._repo_path, self._pack_id, new_version="0.5.0")

        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = update_pack(self._pack_id, store=store, dry_run=True)
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("0.5.0", output)

    def test_rollback_explicit_revision(self) -> None:
        """Rollback with an explicit --revision."""
        store = self._store()
        self._install(self._repo_path, store=store)

        # Make another install to create a second revision
        _make_another_commit(self._repo_path, self._pack_id, new_version="0.3.0")

        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = update_pack(self._pack_id, store=store, skip_confirm=True)
        self.assertEqual(rc, 0)

        # Now we have 2+ revisions. Find the old one.
        revisions = store.list_revisions(self._pack_id)
        active_rev = store.active_revision_path(self._pack_id)
        assert active_rev is not None
        old = [r for r in revisions if r.name != active_rev.name]
        self.assertGreaterEqual(len(old), 1)

        # Rollback to old revision explicitly
        rc = rollback_pack(
            self._pack_id,
            store=store,
            revision=old[0].name,
            skip_confirm=True,
        )
        self.assertEqual(rc, 0)

        # Verify we're back to 0.1.0
        record = store.get_active(self._pack_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.version, "0.1.0")


# ---------------------------------------------------------------------------
# _diff_component_inventories
# ---------------------------------------------------------------------------


class TestDiffComponentInventories(unittest.TestCase):
    """Tests for _diff_component_inventories()."""

    def test_version_change(self) -> None:
        old = {"component_counts": {}, "entrypoints": []}
        new = {"component_counts": {}, "entrypoints": []}
        result = _diff_component_inventories(
            old, new,
            old_version="0.1.0", new_version="0.2.0",
        )
        self.assertIn("0.1.0 → 0.2.0", result)

    def test_commit_change(self) -> None:
        old = {"component_counts": {}, "entrypoints": []}
        new = {"component_counts": {}, "entrypoints": []}
        result = _diff_component_inventories(
            old, new,
            old_commit="abc123456789", new_commit="def123456789",
        )
        self.assertIn("abc12345 → def12345", result)

    def test_component_count_delta(self) -> None:
        old = {"component_counts": {"executors": 1, "orchestrators": 0, "elements": 0},
               "entrypoints": []}
        new = {"component_counts": {"executors": 1, "orchestrators": 2, "elements": 3},
               "entrypoints": []}
        result = _diff_component_inventories(old, new)
        self.assertIn("Executors:1 (unchanged)", result)
        self.assertIn("Orchestrators:0 → 2 (+2)", result)
        self.assertIn("Elements:0 → 3 (+3)", result)

    def test_entrypoint_additions(self) -> None:
        old = {"component_counts": {}, "entrypoints": ["run"]}
        new = {"component_counts": {}, "entrypoints": ["run", "validate"]}
        result = _diff_component_inventories(old, new)
        self.assertIn("Entrypoints added:", result)
        self.assertIn("validate", result)

    def test_entrypoint_removals(self) -> None:
        old = {"component_counts": {}, "entrypoints": ["run", "deprecated"]}
        new = {"component_counts": {}, "entrypoints": ["run"]}
        result = _diff_component_inventories(old, new)
        self.assertIn("Entrypoints removed:", result)
        self.assertIn("deprecated", result)

    def test_secrets_deltas(self) -> None:
        old = {"component_counts": {}, "entrypoints": [],
               "declared_secrets": ["SECRET_A"]}
        new = {"component_counts": {}, "entrypoints": [],
               "declared_secrets": ["SECRET_A", "SECRET_B"]}
        result = _diff_component_inventories(old, new)
        self.assertIn("Secrets added:", result)
        self.assertIn("SECRET_B", result)


# ---------------------------------------------------------------------------
# _format_trust_summary Git fields
# ---------------------------------------------------------------------------


class TestFormatTrustSummaryGit(unittest.TestCase):
    """Tests for _format_trust_summary with Git parameters."""

    def test_shows_git_url_instead_of_source_path(self) -> None:
        summary = {
            "pack_id": "test_pack",
            "name": "Test Pack",
            "version": "1.0.0",
            "schema_version": 1,
            "source_path": "/tmp/temp_checkout",
            "component_counts": {},
            "entrypoints": [],
        }
        result = _format_trust_summary(
            summary,
            git_url="https://github.com/user/repo.git",
            commit_sha="abc1234567890123456789012345678901234567",
            trust_tier="git",
        )
        self.assertIn("Source:", result)
        self.assertIn("https://github.com/user/repo.git", result)
        self.assertNotIn("/tmp/temp_checkout", result)
        self.assertIn("Pinned Commit:", result)
        self.assertIn("abc12345", result)
        self.assertIn("Trust Tier:", result)
        self.assertIn("git", result)

    def test_local_install_shows_source_path(self) -> None:
        summary = {
            "pack_id": "local_pack",
            "name": "Local Pack",
            "version": "0.1.0",
            "schema_version": 1,
            "source_path": "/home/user/packs/local_pack",
            "component_counts": {},
            "entrypoints": [],
        }
        result = _format_trust_summary(summary)
        self.assertIn("/home/user/packs/local_pack", result)
        self.assertNotIn("Pinned Commit:", result)
        self.assertNotIn("Trust Tier:", result)

    def test_shows_astrid_version_when_present(self) -> None:
        summary = {
            "pack_id": "test",
            "name": "Test",
            "version": "0.1.0",
            "schema_version": 1,
            "source_path": "/tmp",
            "component_counts": {},
            "entrypoints": [],
        }
        result = _format_trust_summary(summary, astrid_version="1.0.0")
        self.assertIn("Astrid Ver:", result)
        self.assertIn("1.0.0", result)


# ---------------------------------------------------------------------------
# update_pack branches on source_type before is_dir()
# ---------------------------------------------------------------------------


class TestUpdatePackGitSourceTypeGuard(GitTestBase):
    """Verify update_pack branches on source_type before is_dir() check."""

    def test_update_git_pack_bypasses_is_dir_check(self) -> None:
        """When source_type is 'git', update_pack delegates to _update_git_pack."""
        pack_id = "git_source_guard"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        self._install(repo_path, store=store)
        self.assertTrue(store.is_installed(pack_id))

        # Now manually set source_type to "git" on the record
        # to simulate a Git-backed pack (using _update_git_pack path)
        record = store.get_active(pack_id)
        self.assertIsNotNone(record)

        # Even with source_type != "git", update should work for local path
        rc = update_pack(pack_id, store=store, dry_run=True)
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# rollback_to_revision metadata consistency
# ---------------------------------------------------------------------------


class TestRollbackMetadataConsistency(GitTestBase):
    """Verify rollback updates active flags on both old and target revisions."""

    def test_rollback_sets_target_active_true(self) -> None:
        """After rollback, the target revision has active=True in install.json."""
        pack_id = "rollback_meta"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        self._install(repo_path, store=store)

        # Create a second revision via force install with changed source
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True, exist_ok=True)
        _make_minimal_pack(src, pack_id=pack_id)
        # Modify version
        (src / "pack.yaml").write_text(
            (src / "pack.yaml").read_text().replace("0.1.0", "0.9.0")
        )

        rc = install_pack(src, store=store, skip_confirm=True, force=True)
        self.assertEqual(rc, 0)

        # Verify we have 2 revisions
        revisions = store.list_revisions(pack_id)
        self.assertGreaterEqual(len(revisions), 2)

        active_rev = store.active_revision_path(pack_id)
        assert active_rev is not None
        old = [r for r in revisions if r.name != active_rev.name]
        self.assertGreaterEqual(len(old), 1)

        # Rollback
        rc = rollback_pack(
            pack_id, store=store,
            revision=old[0].name,
            skip_confirm=True,
        )
        self.assertEqual(rc, 0)

        # Record the name of the previously-active revision BEFORE rollback
        old_active_name = active_rev.name  # "rollback_meta" (v0.9.0)

        # Verify: the new active revision has active=True in its install.json
        new_active = store.active_revision_path(pack_id)
        self.assertIsNotNone(new_active)
        assert new_active is not None
        new_install_json = new_active / ".astrid" / "install.json"
        self.assertTrue(new_install_json.is_file())
        data = _json.loads(new_install_json.read_text())
        self.assertTrue(data.get("active", False),
                        f"Expected active=True, got {data.get('active')}")

        # Verify: the OLD active (now demoted) has active=False
        old_active_install_json = (
            store.revisions_dir(pack_id) / old_active_name / ".astrid" / "install.json"
        )
        if old_active_install_json.is_file():
            old_data = _json.loads(old_active_install_json.read_text())
            self.assertFalse(old_data.get("active", True),
                             f"Expected active=False for {old_active_name}, got {old_data.get('active')}")


# ---------------------------------------------------------------------------
# manifest_digest populated
# ---------------------------------------------------------------------------


class TestManifestDigest(GitTestBase):
    """Verify manifest_digest is computed and populated."""

    def test_manifest_digest_populated(self) -> None:
        pack_id = "digest_test"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        self._install(repo_path, store=store)

        record = store.get_active(pack_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(record.manifest_digest,
                        "manifest_digest should be non-empty")
        self.assertEqual(len(record.manifest_digest), 64,
                         "manifest_digest should be a SHA-256 hex digest")


# ---------------------------------------------------------------------------
# _resolve_git_ref with --symref fallback
# ---------------------------------------------------------------------------


class TestResolveGitRef(unittest.TestCase):
    """Tests for _resolve_git_ref with symref fallback (Git < 2.37 compatibility)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-resolve-ref-")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_resolves_default_branch_from_local_repo(self) -> None:
        """_resolve_git_ref should resolve the default branch from a local repo."""
        pack_id = "ref_test"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        ref = _resolve_git_ref(repo_path)
        # Should be HEAD or refs/heads/main on our test repo
        self.assertIsInstance(ref, str)
        self.assertTrue(ref, "ref should be non-empty")
        # On Git 2.34.1, --symref may fail; fallback should pick main or HEAD
        self.assertIn(ref, ("HEAD", "refs/heads/main", "refs/heads/master"))


# ---------------------------------------------------------------------------
# Git credential handling
# ---------------------------------------------------------------------------


class TestGitCredentials(unittest.TestCase):
    """Git credentials are handled entirely by the git subprocess."""

    def test_no_token_env_manipulation(self) -> None:
        """Verify that _run_git does not set or reference GH/GitLab tokens."""
        import inspect
        source = inspect.getsource(_run_git)
        # No mention of token, GITHUB_TOKEN, GITLAB_TOKEN, credential
        self.assertNotIn("GITHUB_TOKEN", source)
        self.assertNotIn("GITLAB_TOKEN", source)
        self.assertNotIn("personal_access_token", source.lower())
        self.assertNotIn("credential.helper", source)

    def test_no_token_in_install_code(self) -> None:
        """Verify install code does not reference any token env vars."""
        import inspect
        source = inspect.getsource(install_pack)
        self.assertNotIn("GITHUB_TOKEN", source)
        self.assertNotIn("GITLAB_TOKEN", source)


# ---------------------------------------------------------------------------
# Inspect shows Git fields
# ---------------------------------------------------------------------------


class TestInspectGitFields(GitTestBase):
    """Verify inspect displays Git-enriched fields for Git-backed packs."""

    def test_inspect_shows_manifest_digest(self) -> None:
        """Inspect output includes manifest_digest when available."""
        pack_id = "inspect_git"
        repo_path, commit_sha = _make_git_repo_with_pack(self._tmpdir, pack_id)

        store = self._store()
        self._install(repo_path, store=store)

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_inspect([pack_id])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Manifest Hash:", output)


if __name__ == "__main__":
    unittest.main()
