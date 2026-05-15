"""CLI tests for packs validate, packs new, executors new, and orchestrators new.

Proves:
1. packs validate examples/packs/minimal exits 0
2. A deliberately broken pack fixture fails with file-specific error and non-zero exit
3. packs new + executors new + orchestrators new creates a pack that passes validate
4. Scaffolds reject invalid ids, missing targets, and overwrites
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from astrid.packs import cli as packs_cli
from astrid.packs.validate import validate_pack


_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_MINIMAL = _REPO_ROOT / "examples" / "packs" / "minimal"


def _chdir_context(path: Path):
    """Context manager to temporarily change CWD. Returns the original CWD."""
    return _ChdirContext(path)


class _ChdirContext:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._original: str | None = None

    def __enter__(self) -> Path:
        self._original = os.getcwd()
        os.chdir(str(self._path))
        return self._path

    def __exit__(self, *args: object) -> None:
        if self._original is not None:
            os.chdir(self._original)


class ScratchPackFixture:
    """Provides a temporary directory that gets cleaned up after the test."""

    def __init__(self, test_case: unittest.TestCase) -> None:
        self._test_case = test_case
        self._tmp: str | None = None
        self._path: Path | None = None

    def __enter__(self) -> Path:
        self._tmp = tempfile.mkdtemp(prefix="test-packs-cli-")
        self._path = Path(self._tmp)
        return self._path

    def __exit__(self, *args: object) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)


def _astrid_env() -> dict:
    """Return an environment dict with PYTHONPATH set so astrid is importable."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    repo = str(_REPO_ROOT)
    env["PYTHONPATH"] = f"{repo}{os.pathsep}{existing}" if existing else repo
    return env


def _scaffold_pack_in_static(tmp: Path, pack_id: str) -> Path:
    """Scaffold a pack in tmp and return the pack root directory."""
    with _chdir_context(tmp):
        rc = packs_cli.cmd_new([pack_id])
        if rc != 0:
            raise RuntimeError(f"cmd_new({pack_id}) failed with exit code {rc}")
    return tmp / pack_id


def _run_packs(*args: str, cwd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a packs subcommand in the given CWD with astrid importable."""
    return subprocess.run(
        [sys.executable, "-m", "astrid", "packs", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_astrid_env(),
        check=check,
    )


def _run_executors(*args: str, cwd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run an executors subcommand in the given CWD with astrid importable."""
    return subprocess.run(
        [sys.executable, "-m", "astrid", "executors", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_astrid_env(),
        check=check,
    )


def _run_orchestrators(*args: str, cwd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run an orchestrators subcommand in the given CWD with astrid importable."""
    return subprocess.run(
        [sys.executable, "-m", "astrid", "orchestrators", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_astrid_env(),
        check=check,
    )


def _run_elements(*args: str, cwd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run an elements subcommand in the given CWD with astrid importable."""
    return subprocess.run(
        [sys.executable, "-m", "astrid", "elements", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_astrid_env(),
        check=check,
    )


class TestPacksValidateCLI(unittest.TestCase):
    """Prove: packs validate examples/packs/minimal exits 0."""

    def test_validate_minimal_example_exits_zero(self) -> None:
        self.assertTrue(
            _EXAMPLES_MINIMAL.is_dir(),
            f"examples/packs/minimal must exist at {_EXAMPLES_MINIMAL}",
        )
        result = _run_packs("validate", str(_EXAMPLES_MINIMAL), cwd=str(_REPO_ROOT))
        self.assertEqual(
            result.returncode, 0,
            f"validate should exit 0 but got {result.returncode}; stderr: {result.stderr!r}",
        )
        self.assertIn("valid:", result.stdout)

    def test_validate_minimal_example_with_warnings_flag_exits_zero(self) -> None:
        result = _run_packs(
            "validate", str(_EXAMPLES_MINIMAL), "--warnings",
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)

    def test_validate_defaults_to_current_directory(self) -> None:
        """When no path is given, validate defaults to '.'."""
        with ScratchPackFixture(self) as tmp:
            self._write_minimal_valid_pack(tmp)
            result = _run_packs("validate", cwd=str(tmp))
            self.assertEqual(
                result.returncode, 0,
                f"validate should exit 0; stderr: {result.stderr!r}",
            )
            self.assertIn("valid:", result.stdout)

    def test_validate_nonexistent_path_exits_nonzero(self) -> None:
        result = _run_packs(
            "validate", "/nonexistent/path/12345",
            cwd=str(_REPO_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_validate_non_directory_exits_nonzero(self) -> None:
        with ScratchPackFixture(self) as tmp:
            some_file = tmp / "not_a_dir.txt"
            some_file.write_text("hello")
            result = _run_packs("validate", str(some_file), cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)

    def _write_minimal_valid_pack(self, root: Path) -> None:
        (root / "pack.yaml").write_text(
            textwrap.dedent("""\
                schema_version: 1
                id: test_pack
                name: Test Pack
                version: 0.1.0
                description: A test pack.
                content:
                  executors: executors
                  orchestrators: orchestrators
                agent:
                  purpose: Testing
            """),
            encoding="utf-8",
        )
        (root / "AGENTS.md").write_text("# Test Pack\n\nAgent guide.\n")
        (root / "README.md").write_text("# Test Pack\n\nUser docs.\n")
        (root / "STAGE.md").write_text("## Purpose\n\nTesting.\n")
        (root / "executors").mkdir(parents=True, exist_ok=True)
        (root / "orchestrators").mkdir(parents=True, exist_ok=True)


class TestPacksValidateBrokenPack(unittest.TestCase):
    """Prove: a deliberately broken pack fixture fails with file-specific error and non-zero exit."""

    def test_broken_pack_missing_schema_version_reports_file_specific_error(self) -> None:
        with ScratchPackFixture(self) as tmp:
            (tmp / "pack.yaml").write_text(
                "id: broken_pack\nname: Broken\nversion: 0.1.0\nagent:\n  purpose: Test\n",
                encoding="utf-8",
            )
            (tmp / "AGENTS.md").write_text("# Broken\n")
            (tmp / "README.md").write_text("# Broken\n")
            result = _run_packs("validate", str(tmp), cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack.yaml", result.stderr)
            self.assertIn("schema_version", result.stderr.lower())

    def test_broken_pack_invalid_yaml_reports_file_specific_error(self) -> None:
        with ScratchPackFixture(self) as tmp:
            (tmp / "pack.yaml").write_text(
                "schema_version: 1\nid: broken\n  name: Bad Indent\n",
                encoding="utf-8",
            )
            result = _run_packs("validate", str(tmp), cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack.yaml", result.stderr)
            self.assertIn("YAML", result.stderr)

    def test_broken_pack_missing_entrypoint_file_reports_error(self) -> None:
        with ScratchPackFixture(self) as tmp:
            (tmp / "pack.yaml").write_text(
                textwrap.dedent("""\
                    schema_version: 1
                    id: broken
                    name: Broken
                    version: 0.1.0
                    agent:
                      purpose: Test
                    content:
                      executors: executors
                """),
                encoding="utf-8",
            )
            (tmp / "AGENTS.md").write_text("# Broken\n")
            (tmp / "README.md").write_text("# Broken\n")
            (tmp / "STAGE.md").write_text("## Purpose\n\nBroken.\n")
            (tmp / "executors").mkdir(parents=True)
            exec_dir = tmp / "executors" / "no_run"
            exec_dir.mkdir(parents=True)
            (exec_dir / "executor.yaml").write_text(
                textwrap.dedent("""\
                    schema_version: 1
                    id: broken.no_run
                    name: No Run
                    version: 0.1.0
                    runtime:
                      type: python-cli
                      entrypoint: run.py
                """),
                encoding="utf-8",
            )
            (exec_dir / "STAGE.md").write_text("# No Run\n")
            result = _run_packs("validate", str(tmp), cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("executors/no_run", result.stderr)
            self.assertIn("entrypoint", result.stderr.lower())

    def test_broken_pack_executor_missing_runtime_field_reports_error(self) -> None:
        with ScratchPackFixture(self) as tmp:
            (tmp / "pack.yaml").write_text(
                textwrap.dedent("""\
                    schema_version: 1
                    id: broken
                    name: Broken
                    version: 0.1.0
                    agent:
                      purpose: Test
                    content:
                      executors: executors
                """),
                encoding="utf-8",
            )
            (tmp / "AGENTS.md").write_text("# Broken\n")
            (tmp / "README.md").write_text("# Broken\n")
            (tmp / "STAGE.md").write_text("## Purpose\n\nBroken.\n")
            (tmp / "executors").mkdir(parents=True)
            exec_dir = tmp / "executors" / "bad_exec"
            exec_dir.mkdir(parents=True)
            (exec_dir / "executor.yaml").write_text(
                textwrap.dedent("""\
                    schema_version: 1
                    id: broken.bad_exec
                    name: Bad Exec
                    version: 0.1.0
                """),
                encoding="utf-8",
            )
            (exec_dir / "run.py").write_text("print('ok')\n")
            (exec_dir / "STAGE.md").write_text("# Bad Exec\n")
            result = _run_packs("validate", str(tmp), cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("executor.yaml", result.stderr)
            self.assertIn("runtime", result.stderr.lower())


class TestScaffoldAndValidateRoundTrip(unittest.TestCase):
    """Prove: packs new + executors new + orchestrators new creates a valid pack."""

    def test_full_scaffold_round_trip_via_subprocess(self) -> None:
        with ScratchPackFixture(self) as tmp:
            cwd = str(tmp)

            # 1. packs new — creates in CWD
            result = _run_packs("new", "my_pack", cwd=cwd)
            self.assertEqual(
                result.returncode, 0,
                f"packs new failed: stderr={result.stderr!r}",
            )
            pack_root = tmp / "my_pack"
            self.assertTrue(pack_root.is_dir(), f"Expected {pack_root} to exist")
            self.assertTrue((pack_root / "pack.yaml").is_file())
            self.assertTrue((pack_root / "AGENTS.md").is_file())
            self.assertTrue((pack_root / "README.md").is_file())
            self.assertTrue((pack_root / "STAGE.md").is_file())
            self.assertTrue((pack_root / "executors").is_dir())
            self.assertTrue((pack_root / "orchestrators").is_dir())
            self.assertTrue((pack_root / "elements").is_dir())

            # 2. executors new (must be run from the pack root to find pack.yaml)
            result = _run_executors(
                "new", "my_pack.ingest_assets",
                cwd=str(pack_root),
            )
            self.assertEqual(
                result.returncode, 0,
                f"executors new failed: stderr={result.stderr!r}",
            )
            exec_dir = pack_root / "executors" / "ingest_assets"
            self.assertTrue(exec_dir.is_dir())
            self.assertTrue((exec_dir / "executor.yaml").is_file())
            self.assertTrue((exec_dir / "run.py").is_file())
            self.assertTrue((exec_dir / "STAGE.md").is_file())

            # 3. orchestrators new
            result = _run_orchestrators(
                "new", "my_pack.make_trailer",
                cwd=str(pack_root),
            )
            self.assertEqual(
                result.returncode, 0,
                f"orchestrators new failed: stderr={result.stderr!r}",
            )
            orch_dir = pack_root / "orchestrators" / "make_trailer"
            self.assertTrue(orch_dir.is_dir())
            self.assertTrue((orch_dir / "orchestrator.yaml").is_file())
            self.assertTrue((orch_dir / "run.py").is_file())
            self.assertTrue((orch_dir / "STAGE.md").is_file())

            # 4. Validate the fully scaffolded pack
            errors, warnings = validate_pack(pack_root)
            self.assertEqual(
                errors, [],
                f"Scaffolded pack should have zero validation errors, got: {errors}",
            )

            # 5. CLI validate subprocess also exits 0
            result = _run_packs("validate", str(pack_root), cwd=str(pack_root))
            self.assertEqual(
                result.returncode, 0,
                f"CLI validate should exit 0; stderr: {result.stderr!r}",
            )
            self.assertIn("valid:", result.stdout)

    def test_scaffold_pack_then_add_executor_and_orchestrator_programmatic(self) -> None:
        """Use the CLI modules directly (not subprocess) to test the internal API."""
        with ScratchPackFixture(self) as tmp:
            # cmd_new uses Path.cwd() to determine target, so chdir into tmp
            with _chdir_context(tmp):
                rc = packs_cli.cmd_new(["test_pack"])
                self.assertEqual(
                    rc, 0,
                    f"cmd_new should return 0, got {rc}",
                )

            pack_dir = tmp / "test_pack"
            self.assertTrue(pack_dir.is_dir(), f"Expected {pack_dir} to exist")

            # Scaffold executor and orchestrator from pack_dir
            result = _run_executors("new", "test_pack.my_exec", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0, f"executors new: {result.stderr}")

            result = _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0, f"orchestrators new: {result.stderr}")

            # Validate the result
            errors, warnings = validate_pack(pack_dir)
            self.assertEqual(errors, [], f"Scaffolded pack should validate cleanly: {errors}")

    def test_full_scaffold_round_trip_with_elements(self) -> None:
        """Prove: packs new → elements new effects → packs validate exits 0."""
        with ScratchPackFixture(self) as tmp:
            cwd = str(tmp)

            # 1. packs new
            result = _run_packs("new", "my_pack", cwd=cwd)
            self.assertEqual(result.returncode, 0, f"packs new failed: {result.stderr!r}")
            pack_root = tmp / "my_pack"
            self.assertTrue(pack_root.is_dir())

            # 2. elements new effects
            result = _run_elements(
                "new", "effects", "my_pack.my_effect",
                cwd=str(pack_root),
            )
            self.assertEqual(
                result.returncode, 0,
                f"elements new failed: stderr={result.stderr!r}",
            )
            elem_dir = pack_root / "elements" / "effects" / "my_effect"
            self.assertTrue(elem_dir.is_dir())
            self.assertTrue((elem_dir / "element.yaml").is_file())
            self.assertTrue((elem_dir / "component.tsx").is_file())
            self.assertTrue((elem_dir / "STAGE.md").is_file())

            # 3. Validate
            result = _run_packs("validate", str(pack_root), cwd=str(pack_root))
            self.assertEqual(result.returncode, 0,
                           f"CLI validate should exit 0; stderr: {result.stderr!r}")
            self.assertIn("valid:", result.stdout)

    def test_zero_touch_round_trip_with_elements(self) -> None:
        """Prove: packs new → executors new → orchestrators new → elements new → validate all passes."""
        with ScratchPackFixture(self) as tmp:
            cwd = str(tmp)

            # 1. packs new
            result = _run_packs("new", "my_pack", cwd=cwd)
            self.assertEqual(result.returncode, 0, f"packs new failed: {result.stderr!r}")
            pack_root = tmp / "my_pack"

            # 2. executors new
            result = _run_executors("new", "my_pack.my_exec", cwd=str(pack_root))
            self.assertEqual(result.returncode, 0, f"executors new failed: {result.stderr!r}")

            # 3. orchestrators new
            result = _run_orchestrators("new", "my_pack.my_orch", cwd=str(pack_root))
            self.assertEqual(result.returncode, 0, f"orchestrators new failed: {result.stderr!r}")

            # 4. elements new effects
            result = _run_elements("new", "effects", "my_pack.my_effect", cwd=str(pack_root))
            self.assertEqual(result.returncode, 0, f"elements new failed: {result.stderr!r}")

            # 5. Validate all
            errors, warnings = validate_pack(pack_root)
            self.assertEqual(errors, [],
                           f"Zero-touch scaffolded pack should validate cleanly: {errors}")


class TestScaffoldRejections(unittest.TestCase):
    """Prove: scaffolds reject invalid ids, missing targets, and overwrites."""

    def _scaffold_pack(self, tmp: Path, pack_id: str) -> Path:
        """Scaffold a pack in tmp and return the pack root directory."""
        with _chdir_context(tmp):
            rc = packs_cli.cmd_new([pack_id])
            if rc != 0:
                raise RuntimeError(f"cmd_new({pack_id}) failed with exit code {rc}")
        return tmp / pack_id

    def test_packs_new_rejects_invalid_id(self) -> None:
        with ScratchPackFixture(self) as tmp:
            result = _run_packs("new", "Invalid-Id", cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid pack id", result.stderr.lower())

    def test_packs_new_rejects_id_with_special_chars(self) -> None:
        with ScratchPackFixture(self) as tmp:
            for bad_id in ("123abc", "my_pack!", "UPPERCASE", "dot.name"):
                with self.subTest(bad_id=bad_id):
                    result = _run_packs("new", bad_id, cwd=str(tmp))
                    self.assertNotEqual(result.returncode, 0)

    def test_packs_new_rejects_existing_directory(self) -> None:
        with ScratchPackFixture(self) as tmp:
            existing = tmp / "my_pack"
            existing.mkdir()
            result = _run_packs("new", "my_pack", cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr.lower())

    def test_executors_new_rejects_invalid_qualified_id(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_executors("new", "bad-id", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be", result.stderr.lower())

    def test_executors_new_rejects_missing_pack(self) -> None:
        with ScratchPackFixture(self) as tmp:
            result = _run_executors("new", "nonexistent.my_exec", cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack.yaml not found", result.stderr)

    def test_executors_new_rejects_pack_id_mismatch(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_executors("new", "other_pack.my_exec", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack id mismatch", result.stderr.lower())

    def test_executors_new_rejects_overwrite(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")

            # First scaffold succeeds
            result = _run_executors("new", "my_pack.my_exec", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0)

            # Second scaffold to same target fails
            result = _run_executors("new", "my_pack.my_exec", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr.lower())

    def test_orchestrators_new_rejects_invalid_qualified_id(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_orchestrators("new", "bad-id", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be", result.stderr.lower())

    def test_orchestrators_new_rejects_missing_pack(self) -> None:
        with ScratchPackFixture(self) as tmp:
            result = _run_orchestrators("new", "nonexistent.my_orch", cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack.yaml not found", result.stderr)

    def test_orchestrators_new_rejects_overwrite(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")

            # First scaffold succeeds
            result = _run_orchestrators("new", "my_pack.my_orch", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0)

            # Second scaffold fails
            result = _run_orchestrators("new", "my_pack.my_orch", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr.lower())

    # ------------------------------------------------------------------
    # Elements rejection tests
    # ------------------------------------------------------------------

    def test_elements_new_rejects_invalid_qualified_id_bad_id(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_elements("new", "effects", "bad-id", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be", result.stderr.lower())

    def test_elements_new_rejects_invalid_qualified_id_dot_name(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            # dot.name matches _QID_RE so it reaches the pack-id-mismatch check
            result = _run_elements("new", "effects", "dot.name", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack id mismatch", result.stderr.lower())

    def test_elements_new_rejects_missing_pack(self) -> None:
        with ScratchPackFixture(self) as tmp:
            result = _run_elements("new", "effects", "nonexistent.my_effect", cwd=str(tmp))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack.yaml not found", result.stderr)

    def test_elements_new_rejects_pack_id_mismatch(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_elements("new", "effects", "other_pack.my_effect", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack id mismatch", result.stderr.lower())

    def test_elements_new_rejects_overwrite(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")

            # First scaffold succeeds
            result = _run_elements("new", "effects", "my_pack.my_effect", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0)

            # Second scaffold fails
            result = _run_elements("new", "effects", "my_pack.my_effect", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr.lower())

    def test_elements_new_rejects_invalid_kind(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack(tmp, "my_pack")
            result = _run_elements("new", "nonexistent_kind", "my_pack.my_slug", cwd=str(pack_dir))
            self.assertNotEqual(result.returncode, 0)


class TestScaffoldFixture(unittest.TestCase):
    """Fixture that builds a temp pack via scaffolds, validates it, and checks created file list."""

    EXPECTED_PACK_FILES = {
        "pack.yaml",
        "AGENTS.md",
        "README.md",
        "STAGE.md",
    }
    EXPECTED_PACK_DIRS = {
        "executors",
        "orchestrators",
        "elements",
    }
    EXPECTED_EXECUTOR_FILES = {
        "executor.yaml",
        "run.py",
        "STAGE.md",
    }
    EXPECTED_ORCHESTRATOR_FILES = {
        "orchestrator.yaml",
        "run.py",
        "STAGE.md",
    }
    EXPECTED_ELEMENT_FILES = {
        "element.yaml",
        "component.tsx",
        "STAGE.md",
    }

    def _scaffold_pack_in(self, tmp: Path, pack_id: str) -> Path:
        """Scaffold a pack and return its root."""
        with _chdir_context(tmp):
            rc = packs_cli.cmd_new([pack_id])
            if rc != 0:
                raise RuntimeError(f"cmd_new({pack_id}) failed with {rc}")
        return tmp / pack_id

    def test_scaffolded_pack_has_expected_file_list(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack_in(tmp, "test_pack")

            # Check expected files exist
            for fname in self.EXPECTED_PACK_FILES:
                path = pack_dir / fname
                self.assertTrue(
                    path.is_file(),
                    f"Expected {fname} to exist in scaffolded pack",
                )

            # Check expected directories exist
            for dname in self.EXPECTED_PACK_DIRS:
                path = pack_dir / dname
                self.assertTrue(
                    path.is_dir(),
                    f"Expected {dname}/ directory to exist in scaffolded pack",
                )

    def test_scaffold_add_executor_then_add_orchestrator_and_validate(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack_in(tmp, "test_pack")

            # Add executor
            result = _run_executors("new", "test_pack.my_exec", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0, f"executors new: {result.stderr}")

            # Add orchestrator
            result = _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir))
            self.assertEqual(result.returncode, 0, f"orchestrators new: {result.stderr}")

            # Check executor files
            exec_dir = pack_dir / "executors" / "my_exec"
            for fname in self.EXPECTED_EXECUTOR_FILES:
                path = exec_dir / fname
                self.assertTrue(
                    path.is_file(),
                    f"Expected {fname} in executors/my_exec/",
                )

            # Check orchestrator files
            orch_dir = pack_dir / "orchestrators" / "my_orch"
            for fname in self.EXPECTED_ORCHESTRATOR_FILES:
                path = orch_dir / fname
                self.assertTrue(
                    path.is_file(),
                    f"Expected {fname} in orchestrators/my_orch/",
                )

            # Validate
            errors, warnings = validate_pack(pack_dir)
            self.assertEqual(
                errors, [],
                f"Validation should pass; got errors: {errors}",
            )

    def test_scaffold_creates_valid_pack_without_manual_edits(self) -> None:
        """The scaffold round-trip must produce a valid pack zero-touch."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack_in(tmp, "test_pack")

            _run_executors("new", "test_pack.ingest", cwd=str(pack_dir), check=True)
            _run_orchestrators("new", "test_pack.assemble", cwd=str(pack_dir), check=True)

            # No manual edits — just validate
            errors, warnings = validate_pack(pack_dir)
            self.assertEqual(
                errors, [],
                f"Zero-touch scaffolded pack should validate cleanly: {errors}",
            )

    def test_element_manifest_field_correctness(self) -> None:
        """Verify scaffolded element.yaml has id=slug, kind=singular, pack_id=pack name."""
        import yaml as _yaml

        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack_in(tmp, "test_pack")

            _run_elements("new", "effects", "test_pack.my_effect", cwd=str(pack_dir), check=True)

            elem_yaml = pack_dir / "elements" / "effects" / "my_effect" / "element.yaml"
            self.assertTrue(elem_yaml.is_file(), "element.yaml should exist")

            doc = _yaml.safe_load(elem_yaml.read_text(encoding="utf-8"))
            self.assertIsInstance(doc, dict)
            self.assertEqual(doc.get("id"), "my_effect",
                           "id must be slug-only, not qualified")
            self.assertEqual(doc.get("kind"), "effect",
                           "kind must be singular 'effect'")
            self.assertEqual(doc.get("pack_id"), "test_pack",
                           "pack_id must be the pack name")

    def test_all_three_element_kinds_work(self) -> None:
        """Test effects, animations, and transitions all produce valid output."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = self._scaffold_pack_in(tmp, "test_pack")

            for kind in ("effects", "animations", "transitions"):
                slug = f"my_{kind[:-1]}"  # my_effect, my_animation, my_transition
                result = _run_elements("new", kind, f"test_pack.{slug}", cwd=str(pack_dir))
                self.assertEqual(
                    result.returncode, 0,
                    f"elements new {kind} should succeed: {result.stderr!r}",
                )
                elem_dir = pack_dir / "elements" / kind / slug
                for fname in self.EXPECTED_ELEMENT_FILES:
                    path = elem_dir / fname
                    self.assertTrue(
                        path.is_file(),
                        f"Expected {fname} in elements/{kind}/{slug}/",
                    )

            # Validate the pack with all three element kinds
            errors, warnings = validate_pack(pack_dir)
            self.assertEqual(
                errors, [],
                f"Pack with all three element kinds should validate cleanly: {errors}",
            )


class TestScaffoldResolverIntegration(unittest.TestCase):
    """Prove scaffolded components can be inspected and resolved through the
    same resolver-backed path as shipped and --pack-root pack components."""

    def test_scaffolded_executor_inspectable_via_pack_root(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_executors("new", "test_pack.my_exec", cwd=str(pack_dir), check=True)

            # Inspect through --pack-root (must come BEFORE subcommand)
            result = _run_executors(
                "--pack-root", str(pack_dir),
                "inspect", "test_pack.my_exec",
                cwd=str(tmp),
            )
            self.assertEqual(
                result.returncode, 0,
                f"executors inspect with --pack-root should exit 0; stderr: {result.stderr!r}",
            )
            self.assertIn("test_pack.my_exec", result.stdout)

    def test_scaffolded_orchestrator_inspectable_via_pack_root(self) -> None:
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir), check=True)

            # Inspect through --pack-root (must come BEFORE subcommand)
            result = _run_orchestrators(
                "--pack-root", str(pack_dir),
                "inspect", "test_pack.my_orch",
                cwd=str(tmp),
            )
            self.assertEqual(
                result.returncode, 0,
                f"orchestrators inspect with --pack-root should exit 0; stderr: {result.stderr!r}",
            )
            self.assertIn("test_pack.my_orch", result.stdout)

    def test_scaffolded_orchestrator_resolves_through_canonical_runtime(self) -> None:
        """resolve_orchestrator_runtime must resolve scaffolded orchestrators."""
        import sys as _sys
        from astrid.core.orchestrator.runtime import resolve_orchestrator_runtime

        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir), check=True)

            # The temp dir must be on sys.path for module resolution
            tmp_str = str(tmp)
            if tmp_str not in _sys.path:
                _sys.path.insert(0, tmp_str)
            try:
                module_path, entrypoint = resolve_orchestrator_runtime(
                    "test_pack.my_orch",
                    extra_pack_roots=(str(pack_dir),),
                )
                self.assertTrue(module_path, f"Should resolve to a module path: {module_path}")
                self.assertEqual(entrypoint, "main")
                self.assertIn("test_pack", module_path)
                self.assertIn("my_orch", module_path)
            finally:
                if tmp_str in _sys.path:
                    _sys.path.remove(tmp_str)

    def test_scaffolded_pack_validate_via_resolver_integration(self) -> None:
        """Scaffolded pack validates clean through the pack validation system."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_executors("new", "test_pack.my_exec", cwd=str(pack_dir), check=True)
            _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir), check=True)

            # Validate via CLI (which uses the static validator)
            result = _run_packs("validate", str(pack_dir), cwd=str(tmp))
            self.assertEqual(result.returncode, 0,
                           f"Scaffolded pack should validate cleanly: {result.stderr!r}")

    def test_scaffolded_pack_listable_via_pack_root(self) -> None:
        """Scaffolded executors/orchestrators appear in list via --pack-root."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_executors("new", "test_pack.my_exec", cwd=str(pack_dir), check=True)
            _run_orchestrators("new", "test_pack.my_orch", cwd=str(pack_dir), check=True)

            result = _run_executors(
                "--pack-root", str(pack_dir),
                "list",
                cwd=str(tmp),
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("test_pack.my_exec", result.stdout)

            result = _run_orchestrators(
                "--pack-root", str(pack_dir),
                "list",
                cwd=str(tmp),
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("test_pack.my_orch", result.stdout)

    def test_scaffolded_element_listable_via_pack_root(self) -> None:
        """Scaffolded elements appear in list via --pack-root."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_elements("new", "effects", "test_pack.my_effect", cwd=str(pack_dir), check=True)

            result = _run_elements(
                "--pack-root", str(pack_dir),
                "list",
                cwd=str(tmp),
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("my_effect", result.stdout)

    def test_scaffolded_element_inspectable_via_pack_root(self) -> None:
        """Scaffolded elements are inspectable via --pack-root."""
        with ScratchPackFixture(self) as tmp:
            pack_dir = _scaffold_pack_in_static(tmp, "test_pack")
            _run_elements("new", "effects", "test_pack.my_effect", cwd=str(pack_dir), check=True)

            result = _run_elements(
                "--pack-root", str(pack_dir),
                "inspect", "effects", "my_effect",
                cwd=str(tmp),
            )
            self.assertEqual(
                result.returncode, 0,
                f"elements inspect with --pack-root should exit 0; stderr: {result.stderr!r}",
            )
            self.assertIn("my_effect", result.stdout)


class TestCLIBackwardCompat(unittest.TestCase):
    """Ensure the CLI modules' internal APIs don't break."""

    def test_packs_cli_main_importable(self) -> None:
        self.assertTrue(callable(packs_cli.main))

    def test_packs_cli_build_parser_works(self) -> None:
        parser = packs_cli.build_parser()
        self.assertIsNotNone(parser)

        # Parse validate
        args = parser.parse_args(["validate", str(_EXAMPLES_MINIMAL)])
        self.assertEqual(args.command, "validate")

        # Parse new
        args = parser.parse_args(["new", "test_pack"])
        self.assertEqual(args.command, "new")
        self.assertEqual(args.pack_id, "test_pack")

    def test_packs_cli_main_validate_returns_zero(self) -> None:
        exit_code = packs_cli.main(["validate", str(_EXAMPLES_MINIMAL)])
        self.assertEqual(exit_code, 0)

    def test_packs_cli_main_new_rejects_bad_id(self) -> None:
        exit_code = packs_cli.main(["new", "BAD"])
        self.assertNotEqual(exit_code, 0)


class TestAgentIndexCLI(unittest.TestCase):
    """Prove: packs agent-index --json returns valid structured output."""

    def test_agent_index_json_returns_valid_json_with_packs_array(self) -> None:
        """``packs agent-index --json`` returns valid JSON with top-level packs array."""
        result = _run_packs("agent-index", "--json", cwd=str(_REPO_ROOT))
        self.assertEqual(
            result.returncode, 0,
            f"agent-index --json should exit 0; stderr: {result.stderr!r}",
        )
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            self.fail(f"agent-index --json output is not valid JSON: {e}")
        self.assertIn("packs", data, "Top-level key 'packs' missing")
        self.assertIsInstance(data["packs"], list, "'packs' should be an array")
        self.assertGreater(len(data["packs"]), 0, "Expected at least one pack in index")

    def test_agent_index_pack_id_filter(self) -> None:
        """``packs agent-index --json --pack-id builtin`` returns single pack."""
        result = _run_packs("agent-index", "--json", "--pack-id", "builtin", cwd=str(_REPO_ROOT))
        self.assertEqual(result.returncode, 0)
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            self.fail(f"agent-index --json with --pack-id output is not valid JSON: {e}")
        # When filtering by pack_id, result is a single pack dict (not wrapped in packs array)
        self.assertIsInstance(data, dict, "Expected a single pack dict for --pack-id filter")
        self.assertEqual(data.get("pack_id"), "builtin")
        self.assertIn("name", data)
        self.assertIn("version", data)
        self.assertIn("components", data)

    def test_agent_index_output_includes_new_fields(self) -> None:
        """agent-index output includes normal_entrypoints, do_not_use_for,
        required_context, secrets, dependencies, keywords, capabilities."""
        result = _run_packs("agent-index", "--json", cwd=str(_REPO_ROOT))
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        packs = data.get("packs", [])
        self.assertGreater(len(packs), 0)
        first = packs[0]
        # Check new structured fields exist
        for field in (
            "normal_entrypoints", "do_not_use_for", "required_context",
            "secrets", "dependencies", "keywords", "capabilities",
            "component_counts", "components",
        ):
            self.assertIn(field, first, f"pack entry missing field: {field}")
        # Check components have required sub-fields
        components = first.get("components", [])
        if components:
            comp = components[0]
            for field in ("id", "name", "kind", "description", "runtime",
                          "is_entrypoint", "docs_paths", "stage_excerpt"):
                self.assertIn(field, comp, f"component missing field: {field}")

    def test_agent_index_handles_missing_pack_gracefully(self) -> None:
        """``packs agent-index --json --pack-id nonexistent`` returns null/empty."""
        result = _run_packs("agent-index", "--json", "--pack-id", "nonexistent_pack_xyz", cwd=str(_REPO_ROOT))
        # Should still exit 0 but return null
        self.assertEqual(result.returncode, 0)
        # null is valid JSON
        data = json.loads(result.stdout)
        self.assertIsNone(data, f"Expected null for missing pack, got: {data!r}")

    def test_agent_index_is_deterministic(self) -> None:
        """Two runs of agent-index --json produce identical output."""
        result1 = _run_packs("agent-index", "--json", cwd=str(_REPO_ROOT))
        result2 = _run_packs("agent-index", "--json", cwd=str(_REPO_ROOT))
        self.assertEqual(result1.returncode, 0)
        self.assertEqual(result2.returncode, 0)
        self.assertEqual(
            json.loads(result1.stdout), json.loads(result2.stdout),
            "agent-index output should be deterministic",
        )


class TestInspectJSON(unittest.TestCase):
    """Prove: packs inspect --json includes new structured fields."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-inspect-json-")
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_installable_pack(self, pack_id: str) -> Path:
        """Create a temp pack with an executor and orchestrator, return source root."""
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True)
        (src / "pack.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}
                name: {pack_id.replace('_', ' ').title()}
                version: 0.1.0
                description: Test pack for inspect --json.
                content:
                  executors: executors
                  orchestrators: orchestrators
                agent:
                  purpose: Test inspect --json output
                  entrypoints:
                    - validate
                  normal_entrypoints:
                    - main_workflow
                  do_not_use_for: Production critical paths
                  required_context:
                    - API key
                    - workspace path
                secrets:
                  - name: API_TOKEN
                    required: true
                    description: API authentication token
                dependencies:
                  python:
                    - requests>=2.28
                  system:
                    - ffmpeg
                keywords:
                  - testing
                  - json
                capabilities:
                  - inspect
                  - validate
                astrid_version: ">=0.1"
            """),
            encoding="utf-8",
        )
        (src / "AGENTS.md").write_text(f"# {pack_id}\n\nAgent guide.\n")
        (src / "README.md").write_text(f"# {pack_id}\n\nUser docs.\n")
        (src / "STAGE.md").write_text("## Purpose\n\nTesting inspect --json.\n")
        (src / "executors").mkdir(parents=True)
        (src / "orchestrators").mkdir(parents=True)

        # Add an executor
        exec_dir = src / "executors" / "my_exec"
        exec_dir.mkdir()
        (exec_dir / "executor.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}.my_exec
                name: My Exec
                kind: external
                version: 0.1.0
                description: Test executor for inspect.
                runtime:
                  type: python-cli
                  entrypoint: run.py
                  callable: main
            """),
        )
        (exec_dir / "run.py").write_text("def main():\\n    print('ok')\\n    return 0\\n")
        (exec_dir / "STAGE.md").write_text("## Stage\n\nFirst stage.\n## Section2\n\nMore content.\n")

        # Add an orchestrator
        orch_dir = src / "orchestrators" / "my_orch"
        orch_dir.mkdir()
        (orch_dir / "orchestrator.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}.my_orch
                name: My Orch
                kind: external
                version: 0.1.0
                description: Test orchestrator for inspect.
                runtime:
                  type: python-cli
                  entrypoint: run.py
                  callable: main
            """),
        )
        (orch_dir / "run.py").write_text("def main():\\n    print('ok')\\n    return 0\\n")
        (orch_dir / "STAGE.md").write_text("## Stage\n\nOrch stage excerpt.\n")

        return src

    def _install_pack(self, src: Path, pack_id: str) -> None:
        """Install a pack using subprocess to our isolated ASTRID_HOME."""
        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "install", str(src), "--yes"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        if result.returncode != 0:
            raise RuntimeError(f"Install failed: {result.stderr}")

    def test_inspect_json_includes_new_fields(self) -> None:
        """``packs inspect <pack_id> --json`` includes normal_entrypoints,
        do_not_use_for, required_context, structured secrets, dependencies,
        keywords, capabilities, and components."""
        src = self._make_installable_pack("inspect_json_test")
        self._install_pack(src, "inspect_json_test")

        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "inspect", "inspect_json_test", "--json"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        self.assertEqual(result.returncode, 0, f"inspect --json failed: {result.stderr}")
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            self.fail(f"inspect --json output is not valid JSON: {e}")

        # Check new structured fields
        self.assertIn("normal_entrypoints", data)
        self.assertEqual(data["normal_entrypoints"], ["main_workflow"])
        self.assertEqual(data.get("do_not_use_for"), "Production critical paths")
        self.assertIn("required_context", data)
        self.assertIn("API key", data["required_context"])
        self.assertIn("keywords", data)
        self.assertEqual(data["keywords"], ["testing", "json"])
        self.assertIn("capabilities", data)
        self.assertEqual(data["capabilities"], ["inspect", "validate"])

        # Check structured secrets
        self.assertIn("secrets", data)
        secrets = data["secrets"]
        self.assertIsInstance(secrets, list)
        self.assertGreater(len(secrets), 0)
        self.assertEqual(secrets[0]["name"], "API_TOKEN")
        self.assertTrue(secrets[0]["required"])

        # Check structured dependencies
        self.assertIn("dependencies_struct", data)
        deps_struct = data["dependencies_struct"]
        self.assertIsInstance(deps_struct, dict)

        # Check components
        self.assertIn("components", data)
        components = data["components"]
        self.assertIsInstance(components, list)
        self.assertGreater(len(components), 0)
        comp_ids = [c["id"] for c in components]
        self.assertIn("inspect_json_test.my_exec", comp_ids)
        self.assertIn("inspect_json_test.my_orch", comp_ids)

        # Verify component sub-fields
        for comp in components:
            self.assertIn("id", comp)
            self.assertIn("name", comp)
            self.assertIn("kind", comp)
            self.assertIn("description", comp)
            self.assertIn("runtime", comp)
            self.assertIn("is_entrypoint", comp)
            self.assertIn("docs_paths", comp)
            self.assertIn("stage_excerpt", comp)
            # stage_excerpt should be bounded to first ## heading
            excerpt = comp.get("stage_excerpt", "")
            self.assertIsInstance(excerpt, str)

    def test_inspect_json_components_have_stage_excerpts(self) -> None:
        """Components in inspect --json have non-empty stage_excerpt from STAGE.md."""
        src = self._make_installable_pack("stage_excerpt_test")
        self._install_pack(src, "stage_excerpt_test")

        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "inspect", "stage_excerpt_test", "--json"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        components = data.get("components", [])
        self.assertGreater(len(components), 0)
        for comp in components:
            excerpt = comp.get("stage_excerpt", "")
            self.assertIsInstance(excerpt, str)
            self.assertGreater(len(excerpt), 0,
                f"Component {comp['id']} should have non-empty stage_excerpt")


class TestElementScanningInAgentIndex(unittest.TestCase):
    """Prove elements appear in agent-index and inspect output."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-elem-scan-")
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_pack_with_elements(self, pack_id: str) -> Path:
        """Create a temp pack with executors, orchestrators, and elements."""
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True)
        (src / "pack.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}
                name: {pack_id.replace('_', ' ').title()}
                version: 0.1.0
                description: Test pack with elements.
                content:
                  executors: executors
                  orchestrators: orchestrators
                  elements: elements
                agent:
                  purpose: Test element scanning
            """),
            encoding="utf-8",
        )
        (src / "AGENTS.md").write_text(f"# {pack_id}\n\nAgent guide.\n")
        (src / "README.md").write_text(f"# {pack_id}\n\nUser docs.\n")
        (src / "STAGE.md").write_text("## Purpose\n\nTesting element scanning.\n")
        (src / "executors").mkdir(parents=True)
        (src / "orchestrators").mkdir(parents=True)
        (src / "elements" / "effects").mkdir(parents=True)

        # Add an executor
        exec_dir = src / "executors" / "my_exec"
        exec_dir.mkdir()
        (exec_dir / "executor.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}.my_exec
                name: My Exec
                version: 0.1.0
                description: Test executor.
                runtime:
                  type: python-cli
                  entrypoint: run.py
            """),
        )
        (exec_dir / "run.py").write_text("print('hello')\n")
        (exec_dir / "STAGE.md").write_text("## Stage\n\nExec stage.\n")

        # Add an element
        elem_dir = src / "elements" / "effects" / "my_effect"
        elem_dir.mkdir()
        (elem_dir / "element.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}.my_effect
                kind: effect
                pack_id: {pack_id}
                metadata:
                  label: My Effect
                schema:
                  title: string
                defaults:
                  title: Default
                dependencies: {{}}
            """),
        )
        (elem_dir / "component.tsx").write_text(
            "export default function MyEffect() { return null; }\n"
        )
        (elem_dir / "STAGE.md").write_text("## Stage\n\nEffect stage.\n")

        return src

    def test_elements_appear_in_build_agent_index(self) -> None:
        """Elements appear in build_agent_index output via API."""
        from astrid.packs.agent_index import build_agent_index
        from astrid.core.pack import PackResolver

        src = self._make_pack_with_elements("elem_scan_test")
        resolver = PackResolver(str(src.parent))
        index = build_agent_index(resolver=resolver, pack_id="elem_scan_test")
        self.assertIsNotNone(index, "build_agent_index should return pack dict")
        self.assertIsInstance(index, dict)
        components = index.get("components", [])
        # Should have at least the executor and the element
        comp_ids = [c["id"] for c in components]
        self.assertIn("elem_scan_test.my_exec", comp_ids,
                      f"Executor should be in components, got: {comp_ids}")
        self.assertIn("elem_scan_test.my_effect", comp_ids,
                      f"Element should be in components, got: {comp_ids}")
        # Verify element fields
        elem = next(c for c in components if c["id"] == "elem_scan_test.my_effect")
        self.assertEqual(elem["kind"], "effect")
        self.assertEqual(elem["name"], "My Effect")
        self.assertIsNone(elem["runtime"], "Elements should have no runtime")
        self.assertFalse(elem["is_entrypoint"], "Elements should not be entrypoints")

    def test_elements_appear_in_inspect_json(self) -> None:
        """Elements appear in packs inspect --json output."""
        src = self._make_pack_with_elements("inspect_elem_test")

        # Install the pack
        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "install", str(src), "--yes"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        self.assertEqual(result.returncode, 0,
                         f"Install failed: {result.stderr}")

        # Inspect
        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "inspect", "inspect_elem_test", "--json"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env={**os.environ, "ASTRID_HOME": str(self._astrid_home)},
        )
        self.assertEqual(result.returncode, 0,
                         f"inspect --json failed: {result.stderr}")
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            self.fail(f"inspect --json output is not valid JSON: {e}")

        components = data.get("components", [])
        comp_ids = [c["id"] for c in components]
        self.assertIn("inspect_elem_test.my_exec", comp_ids,
                      f"Executor should be in inspect components, got: {comp_ids}")
        self.assertIn("inspect_elem_test.my_effect", comp_ids,
                      f"Element should be in inspect components, got: {comp_ids}")
        # Verify element fields
        elem = next(c for c in components if c["id"] == "inspect_elem_test.my_effect")
        self.assertEqual(elem["kind"], "effect")
        self.assertIsNone(elem["runtime"], "Elements should have no runtime")
        self.assertFalse(elem["is_entrypoint"], "Elements should not be entrypoints")


class TestFullPathRegression(unittest.TestCase):
    """Full validate→install→list→inspect→agent-index→run pipeline
    plus element-specific failure-path tests with clear error messages."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-fullpath-")
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _env(self) -> dict:
        """Environment with isolated ASTRID_HOME and PYTHONPATH set."""
        env = os.environ.copy()
        env["ASTRID_HOME"] = str(self._astrid_home)
        existing = env.get("PYTHONPATH", "")
        repo = str(_REPO_ROOT)
        env["PYTHONPATH"] = f"{repo}{os.pathsep}{existing}" if existing else repo
        return env

    def _run_packs_env(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "astrid", "packs", *args],
            capture_output=True, text=True,
            cwd=cwd or str(_REPO_ROOT),
            env=self._env(),
        )

    # ------------------------------------------------------------------
    # (a) Full pipeline: validate → install → list → inspect → agent-index → run
    # ------------------------------------------------------------------

    def test_full_pipeline_media_pack(self) -> None:
        """End-to-end pipeline on the rich media example pack."""
        media_pack = _REPO_ROOT / "examples" / "packs" / "media"

        # ── 1. Validate ──────────────────────────────────────────────
        val = self._run_packs_env("validate", str(media_pack))
        self.assertEqual(val.returncode, 0,
                         f"validate media pack should exit 0, got {val.returncode}; "
                         f"stderr: {val.stderr!r}")
        self.assertIn("valid:", val.stdout)

        # ── 2. Install ──────────────────────────────────────────────
        inst = self._run_packs_env("install", str(media_pack), "--yes")
        self.assertEqual(inst.returncode, 0,
                         f"install media pack should exit 0, got {inst.returncode}; "
                         f"stdout: {inst.stdout!r}\nstderr: {inst.stderr!r}")

        # ── 3. List ─────────────────────────────────────────────────
        lst = self._run_packs_env("list")
        self.assertEqual(lst.returncode, 0,
                         f"list should exit 0, got {lst.returncode}; "
                         f"stderr: {lst.stderr!r}")
        self.assertIn("media", lst.stdout,
                      f"list should mention 'media' pack; stdout: {lst.stdout!r}")

        # ── 4. Inspect --json ───────────────────────────────────────
        insp = self._run_packs_env("inspect", "media", "--json")
        self.assertEqual(insp.returncode, 0,
                         f"inspect --json should exit 0, got {insp.returncode}; "
                         f"stderr: {insp.stderr!r}")
        try:
            insp_data = json.loads(insp.stdout)
        except Exception as e:
            self.fail(f"inspect --json output is not valid JSON: {e}")

        # Check executors, orchestrators, elements in components
        components = insp_data.get("components", [])
        comp_ids = [c["id"] for c in components]
        self.assertIn("media.ingest_assets", comp_ids,
                      f"Should have executor media.ingest_assets; got {comp_ids}")
        self.assertIn("media.make_trailer", comp_ids,
                      f"Should have orchestrator media.make_trailer; got {comp_ids}")
        self.assertIn("project-title-card", comp_ids,
                      f"Should have element project-title-card; got {comp_ids}")

        # Verify element fields
        elem = next(c for c in components if c["id"] == "project-title-card")
        self.assertEqual(elem["kind"], "effect")
        self.assertIsNone(elem["runtime"], "Elements should have no runtime")
        self.assertFalse(elem["is_entrypoint"], "Elements should not be entrypoints")

        # ── 5. Inspect --agent ──────────────────────────────────────
        insp_agent = self._run_packs_env("inspect", "media", "--agent")
        self.assertEqual(insp_agent.returncode, 0,
                         f"inspect --agent should exit 0, got {insp_agent.returncode}; "
                         f"stderr: {insp_agent.stderr!r}")
        self.assertIn("Agent View", insp_agent.stdout,
                      "inspect --agent should show Agent View header")
        self.assertIn("media", insp_agent.stdout,
                      "inspect --agent should mention pack id 'media'")
        self.assertIn("Purpose:", insp_agent.stdout,
                      "inspect --agent should show Purpose line")

        # ── 6. Agent Index (via build_agent_index API) ──────────────
        from astrid.packs.agent_index import build_agent_index

        # Use InstalledPackStore; build_agent_index will find the
        # installed pack via active_revision_path().
        from astrid.core.pack_store import InstalledPackStore
        store = InstalledPackStore(str(self._astrid_home / "packs"))
        rev_dir = store.active_revision_path("media")
        self.assertIsNotNone(rev_dir, "Active revision directory should exist after install")

        # Use the store-based lookup: build_agent_index handles
        # installed packs via store.list_installed() and
        # store.active_revision_path() internally.
        index = build_agent_index(store=store, pack_id="media")
        self.assertIsNotNone(index, "build_agent_index should return a pack dict")
        self.assertIsInstance(index, dict)
        idx_components = index.get("components", [])
        idx_comp_ids = [c["id"] for c in idx_components]
        self.assertIn("media.ingest_assets", idx_comp_ids,
                      f"Agent index should include executor; got {idx_comp_ids}")
        self.assertIn("project-title-card", idx_comp_ids,
                      f"Agent index should include element; got {idx_comp_ids}")

        # ── 7. Run installed executor's run.py ──────────────────────
        exec_dir = rev_dir / "executors" / "ingest_assets"
        run_py = exec_dir / "run.py"
        self.assertTrue(run_py.is_file(),
                        f"Installed executor run.py should exist at {run_py}")
        run_result = subprocess.run(
            [sys.executable, str(run_py)],
            capture_output=True, text=True,
            cwd=str(exec_dir),
            env=self._env(),
        )
        self.assertEqual(run_result.returncode, 0,
                         f"Installed executor run.py should exit 0, got "
                         f"{run_result.returncode}; stderr: {run_result.stderr!r}")
        self.assertIn("ingest_assets:", run_result.stdout,
                      "run.py output should mention ingest_assets")

    # ------------------------------------------------------------------
    # (b) Element-specific failure-path tests
    # ------------------------------------------------------------------

    def _write_broken_element_pack(
        self, pack_id: str, *, element_yaml: str,
        include_component_tsx: bool = True,
    ) -> Path:
        """Create a temporary pack with a single element under elements/effects/."""
        src = Path(self._tmpdir) / "sources" / pack_id
        src.mkdir(parents=True)
        (src / "pack.yaml").write_text(
            textwrap.dedent(f"""\
                schema_version: 1
                id: {pack_id}
                name: {pack_id.replace('_', ' ').title()}
                version: 0.1.0
                description: Test pack for failure paths.
                content:
                  elements: elements
                agent:
                  purpose: Test element failure paths
            """),
            encoding="utf-8",
        )
        (src / "AGENTS.md").write_text(f"# {pack_id}\n\nAgent guide.\n")
        (src / "README.md").write_text(f"# {pack_id}\n\nUser docs.\n")
        (src / "STAGE.md").write_text("## Purpose\n\nTest.\n")
        elem_dir = src / "elements" / "effects" / "broken_elem"
        elem_dir.mkdir(parents=True)
        (elem_dir / "element.yaml").write_text(element_yaml, encoding="utf-8")
        if include_component_tsx:
            (elem_dir / "component.tsx").write_text(
                "export default function Broken() { return null; }\n"
            )
        (elem_dir / "STAGE.md").write_text("## Stage\n\nBroken element stage.\n")
        return src

    def test_element_missing_metadata_label_reports_error(self) -> None:
        """Element manifest missing metadata.label → clear error message."""
        yaml_content = textwrap.dedent("""\
            schema_version: 1
            id: broken-elem
            kind: effect
            pack_id: fail_pack_label
            metadata:
              description: Missing the required label field
            schema:
              title: string
            defaults: {}
            dependencies: {}
        """)
        src = self._write_broken_element_pack(
            "fail_pack_label", element_yaml=yaml_content,
        )
        result = self._run_packs_env("validate", str(src))
        self.assertNotEqual(result.returncode, 0,
                            f"Validate should fail; got exit {result.returncode}")
        combined = result.stdout + result.stderr
        self.assertIn("elements/effects/broken_elem", combined,
                      f"Error should reference element path; output: {combined!r}")
        self.assertTrue(
            "label" in combined.lower() or "metadata" in combined.lower(),
            f"Error should mention missing label/metadata field; output: {combined!r}"
        )

    def test_element_missing_kind_reports_error(self) -> None:
        """Element manifest missing 'kind' → clear error message."""
        yaml_content = textwrap.dedent("""\
            schema_version: 1
            id: broken-elem
            pack_id: fail_pack_kind
            metadata:
              label: No Kind Element
            schema:
              title: string
            defaults: {}
            dependencies: {}
        """)
        src = self._write_broken_element_pack(
            "fail_pack_kind", element_yaml=yaml_content,
        )
        result = self._run_packs_env("validate", str(src))
        self.assertNotEqual(result.returncode, 0,
                            f"Validate should fail; got exit {result.returncode}")
        combined = result.stdout + result.stderr
        self.assertIn("elements/effects/broken_elem", combined,
                      f"Error should reference element path; output: {combined!r}")
        self.assertTrue(
            "kind" in combined.lower(),
            f"Error should mention missing 'kind' field; output: {combined!r}"
        )

    def test_element_missing_schema_reports_error(self) -> None:
        """Element manifest missing 'schema' → clear error message."""
        yaml_content = textwrap.dedent("""\
            schema_version: 1
            id: broken-elem
            kind: effect
            pack_id: fail_pack_schema
            metadata:
              label: No Schema Element
            defaults: {}
            dependencies: {}
        """)
        src = self._write_broken_element_pack(
            "fail_pack_schema", element_yaml=yaml_content,
        )
        result = self._run_packs_env("validate", str(src))
        self.assertNotEqual(result.returncode, 0,
                            f"Validate should fail; got exit {result.returncode}")
        combined = result.stdout + result.stderr
        self.assertIn("elements/effects/broken_elem", combined,
                      f"Error should reference element path; output: {combined!r}")
        self.assertTrue(
            "schema" in combined.lower(),
            f"Error should mention missing 'schema' field; output: {combined!r}"
        )

    def test_element_missing_component_tsx_reports_error(self) -> None:
        """Element missing component.tsx → clear error message."""
        yaml_content = textwrap.dedent("""\
            schema_version: 1
            id: broken-tsx
            kind: effect
            pack_id: fail_pack_tsx
            metadata:
              label: Missing TSX Element
            schema:
              title: string
            defaults: {}
            dependencies: {}
        """)
        src = self._write_broken_element_pack(
            "fail_pack_tsx", element_yaml=yaml_content,
            include_component_tsx=False,
        )
        result = self._run_packs_env("validate", str(src))
        self.assertNotEqual(result.returncode, 0,
                            f"Validate should fail; got exit {result.returncode}")
        combined = result.stdout + result.stderr
        self.assertIn("elements/effects/broken_elem", combined,
                      f"Error should reference element path; output: {combined!r}")
        self.assertIn("component.tsx", combined,
                      f"Error should mention missing component.tsx; output: {combined!r}")

    def test_element_pack_id_mismatch_reports_error(self) -> None:
        """Element pack_id differs from owning pack id → clear error message."""
        yaml_content = textwrap.dedent("""\
            schema_version: 1
            id: broken-mismatch
            kind: effect
            pack_id: WRONG_PACK
            metadata:
              label: Mismatched Pack Element
            schema:
              title: string
            defaults: {}
            dependencies: {}
        """)
        src = self._write_broken_element_pack(
            "fail_pack_mismatch", element_yaml=yaml_content,
        )
        result = self._run_packs_env("validate", str(src))
        self.assertNotEqual(result.returncode, 0,
                            f"Validate should fail; got exit {result.returncode}")
        combined = result.stdout + result.stderr
        self.assertIn("elements/effects/broken_elem", combined,
                      f"Error should reference element path; output: {combined!r}")
        self.assertIn("pack_id", combined.lower(),
                      f"Error should mention pack_id mismatch; output: {combined!r}")


if __name__ == "__main__":
    unittest.main()
