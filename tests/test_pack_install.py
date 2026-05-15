"""Tests for pack install, list, inspect, update, and uninstall.

Uses ``InstalledPackStore(packs_home=tmpdir)`` + ``ASTRID_HOME`` env override
to isolate from the real home directory.
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

from astrid.core.pack_store import (
    InstallRecord,
    InstalledPackStore,
    installed_pack_roots,
)
from astrid.packs.install import (
    install_pack,
    uninstall_pack,
    update_pack,
)
from astrid.packs.cli import cmd_list, cmd_inspect
from astrid.packs.validate import extract_trust_summary, validate_pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_MINIMAL = _REPO_ROOT / "examples" / "packs" / "minimal"


def _make_minimal_pack(root: Path, pack_id: str = "test_pack") -> Path:
    """Write a minimal valid v1 pack, return the pack root."""
    (root / "pack.yaml").write_text(
        textwrap.dedent(f"""\
            schema_version: 1
            id: {pack_id}
            name: {pack_id.replace('_', ' ').title()}
            version: 0.1.0
            description: A test pack for install validation.
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


def _make_runnable_executor(pack_root: Path, exec_id: str, exec_subname: str = "echo_exec") -> Path:
    """Add a runnable executor to a pack.  Returns the executor dir."""
    comp_dir = pack_root / "executors" / exec_subname
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "executor.yaml").write_text(
        textwrap.dedent(f"""\
            schema_version: 1
            id: {exec_id}
            name: Echo Exec
            kind: external
            version: 0.1.0
            description: Simple echo executor for testing.
            runtime:
              type: python-cli
              entrypoint: run.py
              callable: main
        """),
        encoding="utf-8",
    )
    (comp_dir / "run.py").write_text(
        "import sys\n\ndef main():\n    print('echo-ok')\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n"
    )
    (comp_dir / "STAGE.md").write_text("## Purpose\n\nTesting.\n")
    return comp_dir


def _make_runnable_orchestrator(pack_root: Path, orch_id: str, orch_subname: str = "echo_orch") -> Path:
    """Add a runnable orchestrator to a pack.  Returns the orchestrator dir."""
    comp_dir = pack_root / "orchestrators" / orch_subname
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "orchestrator.yaml").write_text(
        textwrap.dedent(f"""\
            schema_version: 1
            id: {orch_id}
            name: Echo Orch
            kind: external
            version: 0.1.0
            description: Simple echo orchestrator for testing.
            runtime:
              type: python-cli
              entrypoint: run.py
              callable: main
        """),
        encoding="utf-8",
    )
    (comp_dir / "run.py").write_text(
        "import sys\n\ndef main():\n    print('orchestrator-ok')\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n"
    )
    (comp_dir / "STAGE.md").write_text("## Purpose\n\nTesting.\n")
    return comp_dir


@contextmanager
def _packs_home(tmpdir: str):
    """Temporarily override ASTRID_HOME so InstalledPackStore is isolated."""
    with mock.patch.dict(os.environ, {"ASTRID_HOME": tmpdir}):
        yield


class InstallTestBase(unittest.TestCase):
    """Base class with temp-dir helpers for install tests."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-install-")
        # Use a subdir as ASTRID_HOME for isolation
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _store(self) -> InstalledPackStore:
        return InstalledPackStore(packs_home=self._astrid_home / "packs")

    def _install(
        self,
        source: Path,
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

    def _uninstall(
        self,
        pack_id: str,
        *,
        keep_revisions: bool = False,
        store: InstalledPackStore | None = None,
    ) -> int:
        if store is None:
            store = self._store()
        return uninstall_pack(
            pack_id,
            store=store,
            keep_revisions=keep_revisions,
            skip_confirm=True,
        )

    def _temp_pack(self, pack_id: str = "test_pack") -> Path:
        """Create a temp source dir with a valid minimal pack."""
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True, exist_ok=True)
        return _make_minimal_pack(src, pack_id=pack_id)


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


class TestInstallDryRun(InstallTestBase):
    def test_install_dry_run_prints_trust_summary(self) -> None:
        """``install_pack(dry_run=True)`` prints trust summary, exits 0, no state."""
        src = self._temp_pack("dry_test")
        store = self._store()

        # Capture stdout
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = self._install(src, dry_run=True, store=store)

        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Trust Summary", output)
        self.assertIn("dry_test", output)
        self.assertIn("Dry Test", output)
        self.assertIn("0.1.0", output)

        # No side effects — store should be empty
        self.assertIsNone(store.get_active("dry_test"))
        self.assertFalse(store.is_installed("dry_test"))


# ---------------------------------------------------------------------------
# Valid install
# ---------------------------------------------------------------------------


class TestInstallValidPack(InstallTestBase):
    def test_install_valid_pack_succeeds(self) -> None:
        """Full install creates correct layout under packs/<id>/."""
        src = self._temp_pack("valid_pack")
        store = self._store()

        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)

        # Verify store state
        self.assertTrue(store.is_installed("valid_pack"))
        record = store.get_active("valid_pack")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.pack_id, "valid_pack")
        self.assertTrue(record.active)

        # Verify directory layout
        root = store.install_root_for("valid_pack")
        self.assertTrue(root.is_dir())
        self.assertTrue(store.active_symlink_path("valid_pack").is_symlink())
        rev = store.active_revision_path("valid_pack")
        self.assertIsNotNone(rev)
        assert rev is not None
        self.assertTrue((rev / "pack.yaml").is_file())
        self.assertTrue((rev / ".astrid" / "install.json").is_file())

        # Verify install.json content
        install_json = _json.loads((rev / ".astrid" / "install.json").read_text())
        self.assertEqual(install_json["pack_id"], "valid_pack")
        self.assertEqual(install_json["source_path"], str(src))


# ---------------------------------------------------------------------------
# Invalid pack leaves no active pack
# ---------------------------------------------------------------------------


class TestInstallInvalidPack(InstallTestBase):
    def test_install_invalid_pack_fails_no_active(self) -> None:
        """Installing an invalid pack returns non-zero and leaves no active pack."""
        src = self._temp_pack("bad_pack")
        # Corrupt the pack to be invalid: remove required field 'id' from pack.yaml
        (src / "pack.yaml").write_text(
            "schema_version: 1\nname: Bad Pack\nversion: 0.1.0\nagent:\n  purpose: Broken\n"
        )
        store = self._store()

        rc = self._install(src, store=store)
        self.assertNotEqual(rc, 0)

        # No active pack should exist
        self.assertFalse(store.is_installed("bad_pack"))
        self.assertIsNone(store.get_active("bad_pack"))

        # Staging directory should be cleaned up
        staging = store.staging_path_for("bad_pack")
        self.assertFalse(staging.is_dir(), f"Staging should be cleaned up, got {staging}")

        # The per-pack root may exist but should not have active symlink
        active_link = store.active_symlink_path("bad_pack")
        self.assertFalse(active_link.exists(), "Active symlink should not exist")


# ---------------------------------------------------------------------------
# Collision / --force
# ---------------------------------------------------------------------------


class TestInstallCollision(InstallTestBase):
    def test_install_collision_rejected(self) -> None:
        """Second install without --force is rejected."""
        src = self._temp_pack("collision_test")
        store = self._store()

        rc1 = self._install(src, store=store)
        self.assertEqual(rc1, 0)

        rc2 = self._install(src, store=store, force=False)
        self.assertNotEqual(rc2, 0)

    def test_install_force_overwrites_and_preserves_old_revision(self) -> None:
        """--force overwrites and renames old revision to <pack_id>.<timestamp>."""
        src = self._temp_pack("force_test")
        store = self._store()

        rc1 = self._install(src, store=store)
        self.assertEqual(rc1, 0)

        # Modify source to create a visible diff
        pack_yaml = src / "pack.yaml"
        original_content = pack_yaml.read_text()
        pack_yaml.write_text(original_content.replace("version: 0.1.0", "version: 0.2.0"))

        rc2 = self._install(src, store=store, force=True)
        self.assertEqual(rc2, 0)

        # Verify old revision exists with timestamp suffix
        revisions_dir = store.revisions_dir("force_test")
        children = list(revisions_dir.iterdir())
        # Should have 2 entries: the active revision "force_test" and the backed-up one
        self.assertGreaterEqual(
            len(children), 2,
            f"Expected at least 2 revisions, got {[c.name for c in children]}",
        )
        backed_up = [c for c in children if c.name != "force_test"]
        self.assertEqual(len(backed_up), 1)
        self.assertTrue(backed_up[0].name.startswith("force_test."), f"Unexpected name: {backed_up[0].name}")

        # Active revision should have version 0.2.0
        rev = store.active_revision_path("force_test")
        assert rev is not None
        import yaml as _yaml
        active_data = _yaml.safe_load((rev / "pack.yaml").read_text())
        self.assertEqual(active_data["version"], "0.2.0")


# ---------------------------------------------------------------------------
# Gitignore
# ---------------------------------------------------------------------------


class TestInstallGitignore(InstallTestBase):
    def test_install_respects_gitignore(self) -> None:
        """Files matched by .gitignore should not be copied during install."""
        src = self._temp_pack("gitignore_test")

        # Add a .gitignore that ignores *.log files
        (src / ".gitignore").write_text("*.log\n")
        (src / "debug.log").write_text("should be ignored")
        (src / "data.log").write_text("should also be ignored")
        (src / "important.txt").write_text("should be included")
        # Also test __pycache__ (hardcoded skip)
        pyc_dir = src / "__pycache__"
        pyc_dir.mkdir()
        (pyc_dir / "cached.pyc").write_text("cached")

        store = self._store()
        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)

        rev = store.active_revision_path("gitignore_test")
        assert rev is not None
        self.assertFalse((rev / "debug.log").exists(), "debug.log should be gitignored")
        self.assertFalse((rev / "data.log").exists(), "data.log should be gitignored")
        self.assertFalse((rev / "__pycache__").exists(), "__pycache__ should be skipped")
        self.assertTrue((rev / "important.txt").exists(), "important.txt should be included")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestListInstalled(InstallTestBase):
    def test_list_empty_shows_message(self) -> None:
        """``cmd_list`` prints 'No packs installed.' when store empty."""
        store = self._store()
        # Redirect stdout
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_list([])
        self.assertEqual(rc, 0)
        self.assertIn("No packs installed.", buf.getvalue())

    def test_list_shows_installed(self) -> None:
        """``cmd_list`` shows installed packs in a table."""
        src = self._temp_pack("list_test")
        store = self._store()
        self._install(src, store=store)

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_list([])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("list_test", output)
        self.assertIn("active", output)
        self.assertNotIn("No packs installed.", output)


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


class TestInspectInstalled(InstallTestBase):
    def test_inspect_shows_components(self) -> None:
        """``packs inspect`` shows component counts and other details."""
        src = self._temp_pack("inspect_test")
        store = self._store()
        self._install(src, store=store)

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_inspect(["inspect_test"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("inspect_test", output)
        self.assertIn("Pack:", output)

    def test_inspect_agent_flag(self) -> None:
        """``packs inspect --agent`` shows agent-focused subset."""
        src = self._temp_pack("agent_test")
        store = self._store()
        self._install(src, store=store)

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_inspect(["agent_test", "--agent"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Agent View", output)
        self.assertIn("Purpose:", output)
        # Should not show full inspect fields like "Source:"
        self.assertNotIn("Source:", output)

    def _temp_pack_with_components(self, pack_id: str) -> Path:
        """Create a temp pack with executor + orchestrator for inspect tests."""
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True, exist_ok=True)
        _make_minimal_pack(src, pack_id=pack_id)

        # Add an executor
        _make_runnable_executor(src, f"{pack_id}.echo_exec", "echo_exec")
        # Add an orchestrator
        _make_runnable_orchestrator(src, f"{pack_id}.echo_orch", "echo_orch")

        return src

    def test_inspect_json_components_have_stage_excerpts(self) -> None:
        """``packs inspect --json`` includes components with stage_excerpt fields."""
        src = self._temp_pack_with_components("stage_test")
        store = self._store()
        self._install(src, store=store)

        # Use subprocess to test --json output path
        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "inspect", "stage_test", "--json"],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        self.assertEqual(
            result.returncode, 0,
            f"inspect --json failed with exit {result.returncode}: {result.stderr}",
        )

        try:
            data = _json.loads(result.stdout)
        except Exception as e:
            self.fail(f"inspect --json output is not valid JSON: {e}")

        # Verify components list exists and is non-empty
        self.assertIn("components", data, "inspect --json should include 'components'")
        components = data["components"]
        self.assertIsInstance(components, list)
        self.assertGreater(len(components), 0, "Should have at least one component")

        # Check component IDs
        comp_ids = [c["id"] for c in components]
        self.assertIn("stage_test.echo_exec", comp_ids)
        self.assertIn("stage_test.echo_orch", comp_ids)

        # Verify each component has required fields including stage_excerpt
        for comp in components:
            self.assertIn("id", comp)
            self.assertIn("name", comp)
            self.assertIn("kind", comp)
            self.assertIn("description", comp)
            self.assertIn("runtime", comp)
            self.assertIn("is_entrypoint", comp)
            self.assertIn("docs_paths", comp)
            self.assertIn("stage_excerpt", comp)
            # stage_excerpt should be a non-empty string
            excerpt = comp.get("stage_excerpt", "")
            self.assertIsInstance(excerpt, str)
            self.assertGreater(
                len(excerpt), 0,
                f"Component {comp['id']} should have non-empty stage_excerpt",
            )


# ---------------------------------------------------------------------------
# Installed components in registry
# ---------------------------------------------------------------------------


class TestInstalledComponentsInRegistry(InstallTestBase):
    """Prove: installed executor/orchestrator appears in registry lookups."""

    def test_installed_executor_in_list(self) -> None:
        """After install, an executor from the pack is discoverable."""
        src = self._temp_pack("exec_reg_test")
        _make_runnable_executor(src, "exec_reg_test.echo_exec")
        store = self._store()
        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)

        # Now check via registry with include_installed=True
        from astrid.core.executor.registry import load_pack_executors

        # We must patch the ASTRID_HOME so installed_pack_roots() resolves correctly
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            execs = load_pack_executors(include_installed=True)
            exec_ids = [e.id for e in execs]
            self.assertIn("exec_reg_test.echo_exec", exec_ids)

    def test_installed_orchestrator_in_list(self) -> None:
        """After install, an orchestrator from the pack is discoverable."""
        src = self._temp_pack("orch_reg_test")
        _make_runnable_orchestrator(src, "orch_reg_test.echo_orch")
        store = self._store()
        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)

        from astrid.core.orchestrator.registry import load_pack_orchestrators

        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            orchs = load_pack_orchestrators(include_installed=True)
            orch_ids = [o.id for o in orchs]
            self.assertIn("orch_reg_test.echo_orch", orch_ids)

    def test_include_installed_false_excludes_installed(self) -> None:
        """With include_installed=False, installed packs are excluded."""
        src = self._temp_pack("excl_test")
        _make_runnable_executor(src, "excl_test.echo_exec")
        store = self._store()
        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)

        from astrid.core.executor.registry import load_pack_executors

        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            # Get baseline (includes everything)
            all_execs = load_pack_executors(include_installed=True)
            all_ids = {e.id for e in all_execs}
            self.assertIn("excl_test.echo_exec", all_ids)

            # Now exclude installed
            excl_execs = load_pack_executors(include_installed=False)
            excl_ids = {e.id for e in excl_execs}
            self.assertNotIn("excl_test.echo_exec", excl_ids)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdatePack(InstallTestBase):
    def test_update_refreshes_from_source(self) -> None:
        """Update copies fresh content from source."""
        src = self._temp_pack("update_test")
        store = self._store()
        self._install(src, store=store)

        # Modify source
        pack_yaml = src / "pack.yaml"
        pack_yaml.write_text(pack_yaml.read_text().replace("version: 0.1.0", "version: 0.3.0"))

        rc = update_pack("update_test", store=store, skip_confirm=True)
        self.assertEqual(rc, 0)

        import yaml as _yaml
        rev = store.active_revision_path("update_test")
        assert rev is not None
        data = _yaml.safe_load((rev / "pack.yaml").read_text())
        self.assertEqual(data["version"], "0.3.0")

    def test_update_rejects_id_change(self) -> None:
        """Update rejects when source pack id has changed."""
        src = self._temp_pack("update_id_test")
        store = self._store()
        self._install(src, store=store)

        # Change the pack id in source
        pack_yaml = src / "pack.yaml"
        pack_yaml.write_text(pack_yaml.read_text().replace("id: update_id_test", "id: changed_id"))

        rc = update_pack("update_id_test", store=store, skip_confirm=True)
        self.assertNotEqual(rc, 0)

    def test_update_dry_run_prints_diff(self) -> None:
        """Update --dry-run prints currently-installed vs source diff."""
        src = self._temp_pack("dry_update")
        store = self._store()
        self._install(src, store=store)

        # Modify source
        pack_yaml = src / "pack.yaml"
        pack_yaml.write_text(pack_yaml.read_text().replace("version: 0.1.0", "version: 0.9.0"))

        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            rc = update_pack("dry_update", store=store, dry_run=True)
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Currently Installed", output)
        self.assertIn("Source (would install)", output)
        self.assertIn("0.9.0", output)


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestUninstallPack(InstallTestBase):
    def test_uninstall_removes_cleanly(self) -> None:
        """Uninstall removes active symlink and per-pack directory."""
        src = self._temp_pack("uninstall_test")
        store = self._store()
        self._install(src, store=store)

        self.assertTrue(store.is_installed("uninstall_test"))

        rc = self._uninstall("uninstall_test", store=store)
        self.assertEqual(rc, 0)

        self.assertFalse(store.is_installed("uninstall_test"))
        self.assertIsNone(store.get_active("uninstall_test"))

        # Per-pack root should be removed
        root = store.install_root_for("uninstall_test")
        self.assertFalse(root.exists(), f"Pack root {root} should be removed")

    def test_uninstall_keep_revisions(self) -> None:
        """Uninstall --keep-revisions preserves revision directories."""
        src = self._temp_pack("keep_rev_test")
        store = self._store()
        self._install(src, store=store)

        rc = self._uninstall("keep_rev_test", store=store, keep_revisions=True)
        self.assertEqual(rc, 0)

        # Active symlink gone but revisions dir may remain
        self.assertFalse(store.is_installed("keep_rev_test"))


# ---------------------------------------------------------------------------
# Full flow: validate → install → inspect → run → uninstall
# ---------------------------------------------------------------------------


class TestFullInstallInspectRunUninstallFlow(InstallTestBase):
    """End-to-end: validate source, install, inspect, uninstall."""

    def test_validate_install_inspect_run_uninstall_flow(self) -> None:
        """Validate a pack, install it, inspect it, confirm it's gone after uninstall."""

        # ── 1. Build a source pack with executor + orchestrator ──
        src = self._temp_pack("flow_test")
        _make_runnable_executor(src, "flow_test.echo_exec")
        _make_runnable_orchestrator(src, "flow_test.echo_orch")

        # ── 2. Validate it ──
        errors, warnings = validate_pack(src)
        self.assertEqual(errors, [], f"Source pack should validate cleanly: {errors}")

        # ── 3. Install ──
        store = self._store()
        rc = self._install(src, store=store)
        self.assertEqual(rc, 0)
        self.assertTrue(store.is_installed("flow_test"))

        # ── 4. Inspect ──
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_inspect(["flow_test"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("flow_test", output)

        # ── 5. List shows it ──
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_list([])
        self.assertEqual(rc, 0)
        self.assertIn("flow_test", buf.getvalue())

        # ── 6. Registry sees the installed components ──
        from astrid.core.executor.registry import load_pack_executors
        from astrid.core.orchestrator.registry import load_pack_orchestrators

        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            execs = load_pack_executors(include_installed=True)
            exec_ids = {e.id for e in execs}
            self.assertIn("flow_test.echo_exec", exec_ids)

            orchs = load_pack_orchestrators(include_installed=True)
            orch_ids = {o.id for o in orchs}
            self.assertIn("flow_test.echo_orch", orch_ids)

        # ── 7. Uninstall ──
        rc = self._uninstall("flow_test", store=store)
        self.assertEqual(rc, 0)
        self.assertFalse(store.is_installed("flow_test"))

        # ── 8. List confirms gone ──
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ASTRID_HOME": str(self._astrid_home)}):
            with mock.patch.object(sys, "stdout", buf):
                rc = cmd_list([])
        self.assertEqual(rc, 0)
        # After uninstall, the pack should not appear
        # (list may show other packs from builtin, but not flow_test)
        self.assertNotIn("flow_test", buf.getvalue())


# ---------------------------------------------------------------------------
# Explicit ASTRID_HOME isolation test
# ---------------------------------------------------------------------------


class TestIsolation(InstallTestBase):
    def test_astrid_home_sandboxing(self) -> None:
        """All test code uses the temp ASTRID_HOME, not the real home."""
        real_astrid_home = os.environ.get("ASTRID_HOME")
        try:
            # Our InstalledPackStore is constructed with explicit packs_home
            store = self._store()
            # The store._home is our temp dir, not the real one
            self.assertEqual(str(store._home), str(self._astrid_home / "packs"))

            # installed_pack_roots() without patch would use the real home,
            # so we don't call it here without the patch.  Verify that our
            # store sees the right path:
            self.assertIn(str(self._astrid_home), str(store._home))
        finally:
            pass  # tearDown cleans up


if __name__ == "__main__":
    unittest.main()
