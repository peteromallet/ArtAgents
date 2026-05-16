from __future__ import annotations

import pytest

from astrid.core.orchestrator.schema import (
    OrchestratorValidationError,
    validate_orchestrator_definition,
)


def test_orchestrator_definition_legacy_python_runtime_validates() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "python", "module": "astrid.packs.builtin.orchestrators.hype", "function": "run"},
    }
    orchestrator = validate_orchestrator_definition(raw)
    assert orchestrator.runtime.kind == "python"


def test_orchestrator_definition_legacy_command_runtime_validates() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "command", "command": {"argv": ["echo", "ok"]}},
    }
    orchestrator = validate_orchestrator_definition(raw)
    assert orchestrator.runtime.kind == "command"


def test_orchestrator_definition_rejects_code_runtime_kind() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "code", "module": "x", "function": "y"},
    }
    with pytest.raises(OrchestratorValidationError, match="runtime.kind"):
        validate_orchestrator_definition(raw)