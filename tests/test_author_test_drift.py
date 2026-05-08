"""Phase 9 author-test drift: copy the packs tree to a tmp dir, mutate the
golden, run with packs_root=<tmp>, assert rc==1 and unified-diff headers."""

from __future__ import annotations

import io
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from astrid.orchestrate import cli as author_cli


_REPO_PACKS = Path(__file__).resolve().parents[1] / "astrid" / "packs"


def test_author_test_reports_drift_with_unified_diff(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    shutil.copytree(_REPO_PACKS, packs)

    golden = packs / "builtin" / "golden" / "smoke.events.jsonl"
    lines = golden.read_text(encoding="utf-8").splitlines()
    # Flip the first line's "kind" to a value that cannot match (write the
    # munged line back; downstream lines remain untouched).
    lines[0] = lines[0].replace('"run_started"', '"BOGUS_KIND"', 1)
    golden.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = author_cli.main(
            ["test", "builtin.hype", "--fixture", "smoke"],
            packs_root=packs,
        )
    assert rc == 1, f"stdout={out.getvalue()!r} stderr={err.getvalue()!r}"
    body = out.getvalue()
    assert "--- golden/smoke.events.jsonl" in body
    assert "+++" in body
