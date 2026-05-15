"""Phase 9 author-test pass: replay against the committed builtin.hype/smoke
golden and assert exit 0 with the expected ok line.

Sprint 2 (T9): the legacy DSL fixture for builtin.hype was moved to
tests/fixtures/legacy_hype.py.  This test sets up a temporary packs root
so ``compile.resolve_orchestrator`` can find it via the legacy
``<pack>/<name>.py`` convention.
"""

from __future__ import annotations

import io
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from astrid.orchestrate import cli as author_cli

_REPO_PACKS = Path(__file__).resolve().parents[1] / "astrid" / "packs"
_LEGACY_HYPE = Path(__file__).resolve().parent / "fixtures" / "legacy_hype.py"


def test_author_test_passes_against_committed_golden(tmp_path: Path) -> None:
    # Build a temporary packs root that includes the manifest-backed
    # builtin/hype/ directory (from the repo) AND the legacy DSL fixture
    # hype.py placed alongside it.
    packs = tmp_path / "packs"
    shutil.copytree(_REPO_PACKS, packs)
    shutil.copy2(_LEGACY_HYPE, packs / "builtin" / "hype.py")

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = author_cli.main(
            ["test", "builtin.hype", "--fixture", "smoke"],
            packs_root=packs,
        )
    assert rc == 0, f"stdout={out.getvalue()!r} stderr={err.getvalue()!r}"
    assert "ok builtin.hype --fixture smoke" in out.getvalue()
