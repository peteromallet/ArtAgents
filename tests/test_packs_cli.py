"""CLI tests for packs validate, packs new, executors new, and orchestrators new.

Proves:
1. packs validate examples/packs/minimal exits 0
2. A deliberately broken pack fixture fails with file-specific error and non-zero exit
3. packs new + executors new + orchestrators new creates a pack that passes validate
4. Scaffolds reject invalid ids, missing targets, and overwrites
"""

from __future__ import annotations

import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
