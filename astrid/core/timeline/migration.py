"""Library entry-point for the Sprint 2 timeline migration.

The actual rewriter lives at ``scripts/migrations/sprint-2/migrate_timelines.py``
and is the supported runnable surface (``python3 scripts/migrations/sprint-2/migrate_timelines.py --dry-run``).
This module re-exports the rewriter's public functions so callers can import
the migration as a library (e.g. for in-process upgrades or test orchestration)
without shelling out to the script.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "scripts" / "migrations" / "sprint-2" / "migrate_timelines.py"
)

_spec = importlib.util.spec_from_file_location(
    "_astrid_sprint2_migrate_timelines", _SCRIPT_PATH
)
if _spec is None or _spec.loader is None:  # pragma: no cover - import-time guard
    raise ImportError(f"could not load migration script from {_SCRIPT_PATH}")

_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

main = _module.main
audit = _module.audit

__all__ = ["main", "audit"]
