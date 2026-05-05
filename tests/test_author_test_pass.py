"""Phase 9 author-test pass: replay against the committed builtin.hype/smoke
golden and assert exit 0 with the expected ok line."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from artagents.orchestrate import cli as author_cli


def test_author_test_passes_against_committed_golden() -> None:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = author_cli.main(["test", "builtin.hype", "--fixture", "smoke"])
    assert rc == 0, f"stdout={out.getvalue()!r} stderr={err.getvalue()!r}"
    assert "ok builtin.hype --fixture smoke" in out.getvalue()
