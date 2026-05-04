from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent


def executor_argv(script_name: str, python_exec: str) -> list[str]:
    """Return argv tokens that invoke a builtin executor's module entrypoint.

    `script_name` accepts a bare step name (``"transcribe"``) or the legacy
    ``bin/`` filename (``"transcribe.py"``).
    """
    stem = script_name[:-3] if script_name.endswith(".py") else script_name
    return [python_exec, "-m", f"artagents.packs.builtin.{stem}.run"]
