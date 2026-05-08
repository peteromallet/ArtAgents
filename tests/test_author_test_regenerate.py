"""Phase 9 author-test --regenerate: copy packs to tmp, truncate the golden,
rerun with --regenerate, assert rc==0, golden non-empty and byte-equal to the
committed golden."""

from __future__ import annotations

import io
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from astrid.orchestrate import cli as author_cli


_REPO_PACKS = Path(__file__).resolve().parents[1] / "astrid" / "packs"


def test_author_test_regenerate_rewrites_golden(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    shutil.copytree(_REPO_PACKS, packs)

    committed_bytes = (_REPO_PACKS / "builtin" / "golden" / "smoke.events.jsonl").read_bytes()
    golden = packs / "builtin" / "golden" / "smoke.events.jsonl"
    golden.write_text("", encoding="utf-8")
    assert golden.stat().st_size == 0

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = author_cli.main(
            ["test", "builtin.hype", "--fixture", "smoke", "--regenerate"],
            packs_root=packs,
        )
    assert rc == 0, f"stdout={out.getvalue()!r} stderr={err.getvalue()!r}"
    assert golden.stat().st_size > 0
    assert golden.read_bytes() == committed_bytes
    assert "commit if intentional" in out.getvalue()
