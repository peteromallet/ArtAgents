"""Unit tests for astrid/packs/validate.py.

Covers:
- valid/invalid pack manifests (schema_version present/missing/unknown,
  required fields, malformed YAML)
- missing docs/runtime files
- undeclared content roots
- file-specific error formatting
- validation does NOT import or execute run.py (static safety)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from astrid.packs.validate import PackValidator, ValidationError, validate_pack


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class MinimalPackTestCase(unittest.TestCase):
    """Shared helpers for pack test cases."""

    def make_pack_root(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="test-validate-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def write_valid_pack(self, root: Path, pack_id: str = "test_pack") -> None:
        """Write a minimal valid v1 pack."""
        _write(
            root / "pack.yaml",
            f"""schema_version: 1
id: {pack_id}
name: Test Pack
version: 0.1.0
description: A test pack.
content:
  executors: executors
  orchestrators: orchestrators
agent:
  purpose: Testing
""",
        )
        _write(root / "AGENTS.md", "# Test Pack\n\nAgent guide.")
        _write(root / "README.md", "# Test Pack\n\nUser docs.")
        _write(root / "STAGE.md", "## Purpose\n\nTesting.")
        (root / "executors").mkdir(parents=True, exist_ok=True)
        (root / "orchestrators").mkdir(parents=True, exist_ok=True)

    def write_valid_executor(
        self, root: Path, exec_path: str = "executors/test_exec", exec_id: str = "test_pack.test_exec"
    ) -> None:
        """Write a valid executor manifest and supporting files."""
        comp_dir = root / exec_path
        _write(
            comp_dir / "executor.yaml",
            f"""schema_version: 1
id: {exec_id}
name: Test Executor
version: 0.1.0
description: A test executor.
runtime:
  type: python-cli
  entrypoint: run.py
""",
        )
        _write(comp_dir / "run.py", "# Test executor\nprint('hello')\n")
        _write(comp_dir / "STAGE.md", "# Test Executor\n\nPurpose: Testing.\n")


class TestValidPack(MinimalPackTestCase):
    """Valid pack manifests should pass validation."""

    def test_valid_minimal_pack(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")

    def test_valid_pack_with_executor(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        self.write_valid_executor(root)
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")

    def test_valid_pack_no_content_roots_warns(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        _write(root / "AGENTS.md", "# Test")
        _write(root / "README.md", "# Test")
        errors, warnings = validate_pack(root)
        # Missing content roots should only produce warnings, not errors
        # (content roots are optional in the schema)
        self.assertEqual(errors, [])

    def test_valid_pack_schema_version_float(self) -> None:
        """schema_version: 1 (float in YAML) should be accepted."""
        root = self.make_pack_root()
        self.write_valid_pack(root)
        # YAML safe_load parses `1` as int by default, but let's also
        # verify that a float 1.0 works
        _write(
            root / "pack.yaml",
            """schema_version: 1.0
id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, warnings = validate_pack(root)
        # 1.0 should be accepted as it equals int 1
        self.assertEqual(errors, [])


class TestSchemaVersionErrors(MinimalPackTestCase):
    """Schema version validation edge cases."""

    def test_missing_schema_version(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertEqual(len(errors), 1)
        self.assertIn("missing required field schema_version", errors[0])
        self.assertIn("pack.yaml", errors[0])

    def test_unknown_schema_version(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 99
id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown schema_version 99", errors[0])
        self.assertIn("pack.yaml", errors[0])

    def test_schema_version_string(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: "1"
id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("schema_version" in e for e in errors),
            f"No error mentions schema_version: {errors}",
        )

    def test_schema_version_null(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: null
id: test_pack
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("schema_version" in e.lower() for e in errors),
            f"No error mentions schema_version: {errors}",
        )


class TestMissingRequiredFields(MinimalPackTestCase):
    """Validation should catch missing required fields."""

    def test_missing_pack_id(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
name: Test Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("id" in e.lower() and "missing" in e.lower() for e in errors),
            f"Expected missing id error, got: {errors}",
        )

    def test_missing_pack_name(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: test_pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("name" in e.lower() and "missing" in e.lower() for e in errors),
            f"Expected missing name error, got: {errors}",
        )

    def test_executor_missing_runtime(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        _write(
            root / "executors" / "bad_exec" / "executor.yaml",
            """schema_version: 1
id: test_pack.bad_exec
name: Bad Executor
version: 0.1.0
""",
        )
        _write(root / "executors" / "bad_exec" / "run.py", "# side effect\n")
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("runtime" in e.lower() for e in errors),
            f"Expected missing runtime error, got: {errors}",
        )

    def test_executor_missing_runtime_entrypoint(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        _write(
            root / "executors" / "bad_exec" / "executor.yaml",
            """schema_version: 1
id: test_pack.bad_exec
name: Bad Executor
version: 0.1.0
runtime:
  type: python-cli
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        # The "oneOf" on runtime reports "not valid under any of the given schemas"
        # because python-cli requires entrypoint. The error still correctly
        # identifies the runtime field as the problem.
        error_text = " ".join(errors)
        self.assertTrue(
            "runtime" in error_text.lower() and "not valid" in error_text.lower(),
            f"Expected runtime validation error, got: {errors}",
        )


class TestMalformedYaml(MinimalPackTestCase):
    """Malformed YAML should produce clear error messages."""

    def test_invalid_yaml_syntax(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: test_pack
  name: Test Pack  # bad indentation
version: 0.1.0
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertIn("invalid YAML", errors[0])
        self.assertIn("pack.yaml", errors[0])

    def test_yaml_not_a_mapping(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            "- item1\n- item2\n",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("mapping" in e.lower() for e in errors),
            f"Expected mapping error, got: {errors}",
        )

    def test_empty_yaml(self) -> None:
        root = self.make_pack_root()
        _write(root / "pack.yaml", "")
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertIn("empty YAML", errors[0])

    def test_yaml_null_document(self) -> None:
        root = self.make_pack_root()
        _write(root / "pack.yaml", "---\n...\n")
        errors, _ = validate_pack(root)
        # This parses to None/null
        self.assertGreater(len(errors), 0)


class TestMissingDocsAndFiles(MinimalPackTestCase):
    """Missing docs, STAGE.md, and runtime files should be flagged."""

    def test_missing_agents_md_warns(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        (root / "AGENTS.md").unlink()
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertTrue(
            any("AGENTS.md" in w for w in warnings),
            f"Expected AGENTS.md warning, got: {warnings}",
        )

    def test_missing_readme_md_warns(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        (root / "README.md").unlink()
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertTrue(
            any("README.md" in w for w in warnings),
            f"Expected README.md warning, got: {warnings}",
        )

    def test_missing_runtime_entrypoint_file(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        self.write_valid_executor(root)
        (root / "executors" / "test_exec" / "run.py").unlink()
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("entrypoint" in e.lower() and "not found" in e.lower() for e in errors),
            f"Expected entrypoint not found error, got: {errors}",
        )

    def test_missing_stage_md_warns(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        self.write_valid_executor(root)
        (root / "executors" / "test_exec" / "STAGE.md").unlink()
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertTrue(
            any("STAGE.md" in w for w in warnings),
            f"Expected STAGE.md warning, got: {warnings}",
        )

    def test_missing_pack_yaml(self) -> None:
        root = self.make_pack_root()
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertIn("pack manifest not found", errors[0])


class TestUndeclaredContentRoots(MinimalPackTestCase):
    """Undeclared content roots should produce warnings."""

    def test_undeclared_content_root_warns(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: test_pack
name: Test Pack
version: 0.1.0
content:
  executors: nonexistent_executors
agent:
  purpose: Testing
""",
        )
        _write(root / "AGENTS.md", "# Test")
        _write(root / "README.md", "# Test")
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertTrue(
            any("nonexistent_executors" in w for w in warnings),
            f"Expected content root warning, got: {warnings}",
        )


class TestFileSpecificErrors(MinimalPackTestCase):
    """Errors should reference the specific file path."""

    def test_pack_yaml_error_mentions_file(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: test_pack
name: Test Pack
version: 0.1.0
unknown_field: value
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertIn("pack.yaml", errors[0])

    def test_executor_yaml_error_mentions_file(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        _write(
            root / "executors" / "bad_exec" / "executor.yaml",
            """schema_version: 1
id: test_pack.bad_exec
name: Bad Executor
version: 0.1.0
runtime:
  type: python-cli
  entrypoint: run.py
bad_field: true
""",
        )
        _write(root / "executors" / "bad_exec" / "run.py", "print('ok')")
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        error_text = " ".join(errors)
        self.assertIn("executor.yaml", error_text)

    def test_executor_yaml_path_includes_component_dir(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        self.write_valid_executor(root, "executors/my_exec", "test_pack.my_exec")
        # Corrupt the executor.yaml
        _write(
            root / "executors" / "my_exec" / "executor.yaml",
            """schema_version: 1
id: test_pack.my_exec
name: My Exec
version: 0.1.0
runtime:
  type: python-cli
  entrypoint: run.py
illegal: yes
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        error_text = " ".join(errors)
        self.assertIn("executors/my_exec/executor.yaml", error_text)


class TestNoExecutionSafety(MinimalPackTestCase):
    """Validation must NOT import or execute run.py files."""

    def test_validate_does_not_execute_run_py(self) -> None:
        """A run.py with side effects must NOT be triggered during validation."""
        root = self.make_pack_root()
        self.write_valid_pack(root)

        # Write a run.py that would create a sentinel file if executed
        sentinel = root / "SENTINEL_WAS_EXECUTED"
        _write(
            root / "executors" / "side_effect_exec" / "executor.yaml",
            """schema_version: 1
id: test_pack.side_effect_exec
name: Side Effect Executor
version: 0.1.0
runtime:
  type: python-cli
  entrypoint: run.py
""",
        )
        _write(
            root / "executors" / "side_effect_exec" / "run.py",
            f"""# This file has side effects that MUST NOT run during validation
import os
# Write a sentinel file to prove we were executed
with open({sentinel!r}, 'w') as f:
    f.write('EXECUTED')
# Potentially dangerous operation (won't actually run)
print('THIS SHOULD NOT PRINT')
""",
        )
        _write(
            root / "executors" / "side_effect_exec" / "STAGE.md",
            "# Side Effect Executor\n\nPurpose: testing.\n",
        )

        # Reset any pre-existing sentinel
        if sentinel.exists():
            sentinel.unlink()

        errors, warnings = validate_pack(root)

        # Validation should succeed (valid pack)
        self.assertEqual(errors, [], f"Unexpected validation errors: {errors}")

        # The sentinel MUST NOT exist — run.py was NOT imported or executed
        self.assertFalse(
            sentinel.exists(),
            "SENTINEL: run.py was EXECUTED during validation! "
            "Validation must be static and never import run.py.",
        )

    def test_validate_does_not_import_run_py_module(self) -> None:
        """A run.py with import-time side effects must NOT trigger."""
        root = self.make_pack_root()
        self.write_valid_pack(root)

        sentinel = root / "IMPORT_SENTINEL"
        # Use a less obvious approach — write a file that sys.modules
        # would record if imported
        _write(
            root / "executors" / "import_test" / "executor.yaml",
            """schema_version: 1
id: test_pack.import_test
name: Import Test
version: 0.1.0
runtime:
  type: python-cli
  entrypoint: run.py
""",
        )
        _write(
            root / "executors" / "import_test" / "run.py",
            f"""import sys
# If this module gets imported, this file should appear in sys.modules
# But let's create a sentinel for certainty
from pathlib import Path
Path({sentinel!r}).write_text('imported')
""",
        )
        _write(
            root / "executors" / "import_test" / "STAGE.md",
            "# Import Test\n\nPurpose: testing.\n",
        )

        if sentinel.exists():
            sentinel.unlink()

        errors, _ = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertFalse(
            sentinel.exists(),
            "IMPORT SENTINEL: run.py was IMPORTED during validation!",
        )

    def test_validate_handles_unreadable_run_py(self) -> None:
        """Even if run.py exists but can't be read, validation shouldn't crash."""
        # This is just confirming we only do existence check, not reading
        root = self.make_pack_root()
        self.write_valid_pack(root)
        self.write_valid_executor(root, "executors/test_exec", "test_pack.test_exec")
        # Make run.py unreadable
        run_py = root / "executors" / "test_exec" / "run.py"
        run_py.chmod(0o000)
        self.addCleanup(run_py.chmod, 0o644)

        # Validation should succeed because we only check existence
        errors, _ = validate_pack(root)
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")


class TestPackValidatorClass(MinimalPackTestCase):
    """Direct tests of the PackValidator class API."""

    def test_validator_returns_errors_and_warnings(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        validator = PackValidator(root)
        errors = validator.validate()
        self.assertEqual(errors, [])
        self.assertIsInstance(validator.warnings, list)

    def test_validator_with_missing_pack_yaml(self) -> None:
        root = self.make_pack_root()
        validator = PackValidator(root)
        errors = validator.validate()
        self.assertGreater(len(errors), 0)
        self.assertIn("pack manifest not found", errors[0])

    def test_validate_pack_function(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        errors, warnings = validate_pack(root)
        self.assertEqual(errors, [])
        self.assertIsInstance(warnings, list)

    def test_validate_pack_function_invalid(self) -> None:
        root = self.make_pack_root()
        errors, warnings = validate_pack("/nonexistent/path")
        self.assertGreater(len(errors), 0)


class TestInvalidPackIdPattern(MinimalPackTestCase):
    """Invalid pack ids should fail schema validation."""

    def test_pack_id_with_hyphens(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: my-pack
name: My Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        # Hyphens are not allowed in pack_id pattern
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("pattern" in e.lower() or "my-pack" in e for e in errors),
            f"Expected pattern error for id 'my-pack', got: {errors}",
        )

    def test_pack_id_with_uppercase(self) -> None:
        root = self.make_pack_root()
        _write(
            root / "pack.yaml",
            """schema_version: 1
id: MyPack
name: My Pack
version: 0.1.0
agent:
  purpose: Testing
""",
        )
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("MyPack" in e or "pattern" in e.lower() for e in errors),
            f"Expected pattern error for id 'MyPack', got: {errors}",
        )


class TestExecutorIdMustBeQualified(MinimalPackTestCase):
    """Executor ids must be qualified (<pack>.<slug>)."""

    def test_unqualified_executor_id(self) -> None:
        root = self.make_pack_root()
        self.write_valid_pack(root)
        _write(
            root / "executors" / "bad_exec" / "executor.yaml",
            """schema_version: 1
id: bad_exec
name: Bad Executor
version: 0.1.0
runtime:
  type: python-cli
  entrypoint: run.py
""",
        )
        _write(root / "executors" / "bad_exec" / "run.py", "print('ok')")
        errors, _ = validate_pack(root)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("pattern" in e.lower() or "bad_exec" in e for e in errors),
            f"Expected pattern/qualified error for 'bad_exec', got: {errors}",
        )


if __name__ == "__main__":
    unittest.main()
