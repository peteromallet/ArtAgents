from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
BIN_ROOT = REPO_ROOT / "bin"
WORKSPACE_ROOT = REPO_ROOT.parent


def cli_script_path(name: str) -> Path:
    """Return the repo-local direct launcher for a CLI script."""
    bin_path = BIN_ROOT / name
    if bin_path.exists():
        return bin_path.resolve()
    return (REPO_ROOT / name).resolve()
