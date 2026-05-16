"""Skip the external.runpod test files when the optional runpod_lifecycle peer package is not importable.

The external.runpod pack depends on the sibling `runpod-lifecycle` repo, which is
not a published PyPI dependency and not installed in every Astrid test environment.
When it is missing, every test in this directory fails at import-time with
ModuleNotFoundError. Skip cleanly via ``collect_ignore`` so collection succeeds.
"""

from __future__ import annotations

import importlib.util


_RUNPOD_AVAILABLE = importlib.util.find_spec("runpod_lifecycle") is not None

if not _RUNPOD_AVAILABLE:
    # Skip every test file that touches runpod_lifecycle. test_doctor_integration
    # does not, so leave it collectable.
    collect_ignore = [
        "test_ensure_storage.py",
        "test_pack_executors.py",
        "test_provision_ports.py",
        "test_session_oom_breadcrumb.py",
        "test_sweeper.py",
    ]
