"""T20: artagents author test (Phase 5 SCAFFOLD) — file-vs-file diff against
golden, ignoring volatile ts/hash. Branches: missing/empty golden -> exit 2
+ Phase 9 message; matching golden -> exit 0; mismatched golden -> exit 1
with unified diff in stdout. Per FLAG-P5-004 the runtime replay path is
explicitly NOT tested here — that's Phase 9.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from artagents.orchestrate import cli as author_cli


_BODY = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.app")
def app(): return [code("step_a", argv=["echo","x"])]
'''


def _make_pack(tmp_path: Path) -> Path:
    packs = tmp_path / "packs"
    pack = packs / "demo"
    pack.mkdir(parents=True)
    (pack / "app.py").write_text(_BODY, encoding="utf-8")
    return packs


def test_missing_golden_returns_2_with_phase9_message(tmp_path: Path) -> None:
    packs = _make_pack(tmp_path)
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = author_cli.main(["test", "demo.app", "--fixture", "f1"], packs_root=packs)
    assert rc == 2
    assert "implement Phase 9 to capture golden runs" in err.getvalue()


def test_empty_golden_returns_2_with_phase9_message(tmp_path: Path) -> None:
    packs = _make_pack(tmp_path)
    golden = packs / "demo" / "golden"
    golden.mkdir(parents=True)
    (golden / "f1.events.jsonl").write_text("", encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = author_cli.main(["test", "demo.app", "--fixture", "f1"], packs_root=packs)
    assert rc == 2
    assert "implement Phase 9 to capture golden runs" in err.getvalue()


def test_matching_golden_and_captured_returns_0(tmp_path: Path) -> None:
    """Volatile ts and hash differ between golden and captured; everything
    else matches; _strip_volatile makes the comparison succeed.
    """
    packs = _make_pack(tmp_path)
    golden_dir = packs / "demo" / "golden"
    fixt_dir = packs / "demo" / "fixtures" / "f1"
    golden_dir.mkdir(parents=True)
    fixt_dir.mkdir(parents=True)
    golden_line = '{"hash":"sha256:OLD","kind":"run_started","run_id":"r1","ts":"2026-01-01T00:00:00Z"}'
    captured_line = '{"hash":"sha256:NEW","kind":"run_started","run_id":"r1","ts":"2026-05-04T22:00:00Z"}'
    (golden_dir / "f1.events.jsonl").write_text(golden_line + "\n", encoding="utf-8")
    (fixt_dir / "events.jsonl").write_text(captured_line + "\n", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = author_cli.main(["test", "demo.app", "--fixture", "f1"], packs_root=packs)
    assert rc == 0
    assert "ok demo.app --fixture f1" in buf.getvalue()


def test_mismatched_golden_returns_1_with_unified_diff(tmp_path: Path) -> None:
    packs = _make_pack(tmp_path)
    golden_dir = packs / "demo" / "golden"
    fixt_dir = packs / "demo" / "fixtures" / "f1"
    golden_dir.mkdir(parents=True)
    fixt_dir.mkdir(parents=True)
    golden_line = '{"hash":"sha256:x","kind":"run_started","run_id":"r1","ts":"2026-01-01T00:00:00Z"}'
    captured_line = '{"hash":"sha256:y","kind":"step_attested","plan_step_id":"review","ts":"2026-05-04T22:00:00Z"}'
    (golden_dir / "f1.events.jsonl").write_text(golden_line + "\n", encoding="utf-8")
    (fixt_dir / "events.jsonl").write_text(captured_line + "\n", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = author_cli.main(["test", "demo.app", "--fixture", "f1"], packs_root=packs)
    assert rc == 1
    out = buf.getvalue()
    assert "--- golden/f1.events.jsonl" in out
    assert "+++ fixtures/f1/events.jsonl" in out
    # Drift content present in the diff.
    assert "run_started" in out
    assert "step_attested" in out
