from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

# Map of bin-style script filenames (e.g. "render_remotion.py") to the
# canonical executor module that owns the behavior. Keeps callers free to use
# the legacy filename while we migrate, and makes the one name mismatch
# (render_remotion -> executors.render) explicit in one place.
_EXECUTOR_MODULE_OVERRIDES = {
    "render_remotion": "artagents.executors.render.run",
}


def executor_argv(script_name: str, python_exec: str) -> list[str]:
    """Return argv tokens that invoke an executor's canonical module entrypoint.

    `script_name` accepts either a bare step name (``"transcribe"``) or the
    legacy ``bin/`` filename (``"transcribe.py"``).
    """
    stem = script_name[:-3] if script_name.endswith(".py") else script_name
    module = _EXECUTOR_MODULE_OVERRIDES.get(stem, f"artagents.executors.{stem}.run")
    return [python_exec, "-m", module]
