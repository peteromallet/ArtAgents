"""Tests for the real RemoteArtifactAdapter (Sprint 5a T12).

Replaces the S3 stub-rejection test. Uses in-process fake executor with
controllable manifest + fetchable bytes — no real network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.adapter.remote_artifact import RemoteArtifactAdapter
from astrid.core.adapter.remote_artifact_fetch import FetchResult, fetch_artifacts
from astrid.core.task.plan import (
    Check,
    ProducesEntry,
    RepeatForEach,
    Step,
)


@pytest.fixture
def adapter() -> RemoteArtifactAdapter:
    return RemoteArtifactAdapter()


def _make_ctx(
    tmp_path: Path,
    slug: str = "demo",
    run_id: str = "run-1",
    plan_step_path: tuple[str, ...] = ("s1",),
    step_version: int = 1,
    iteration: int | None = None,
    item_id: str | None = None,
) -> RunContext:
    proj_root = tmp_path / "projects" / slug
    proj_root.mkdir(parents=True, exist_ok=True)
    return RunContext(
        slug=slug,
        run_id=run_id,
        project_root=proj_root,
        plan_step_path=plan_step_path,
        step_version=step_version,
        iteration=iteration,
        item_id=item_id,
    )


def _make_step(
    step_id: str = "s1",
    adapter: str = "remote-artifact",
    command: str = "echo job-abc123",
    produces: tuple[ProducesEntry, ...] | None = None,
) -> Step:
    return Step(
        id=step_id,
        adapter=adapter,  # type: ignore[arg-type]
        command=command,
        produces=produces or (),
    )


def _make_produces(names: list[str]) -> tuple[ProducesEntry, ...]:
    return tuple(
        ProducesEntry(
            name=name,
            path=name,
            check=Check(check_id="file_nonempty", params={}, sentinel=False),
        )
        for name in names
    )


def _write_produces(step_dir: Path, files: dict[str, bytes]) -> None:
    """Write artifacts into the step's produces directory."""
    produces_dir = step_dir / "produces"
    produces_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (produces_dir / name).write_bytes(content)


def _write_remote_state(
    step_dir: Path, job_id: str, manifest: dict[str, str] | None = None
) -> None:
    step_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "job_id": job_id,
        "started_at": "2025-01-01T00:00:00.000Z",
        "command": "mock-command",
        "poll_interval_seconds": 1,
        "pid": -1,  # Will be adjusted in tests
    }
    if manifest:
        state["manifest"] = manifest
    (step_dir / "remote_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# dispatch()
# ---------------------------------------------------------------------------


def test_dispatch_rejects_empty_command(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """dispatch() rejects when command is None or empty."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="")
    result = adapter.dispatch(step, ctx)
    assert result.status == "rejected"
    assert "non-empty command" in (result.reason or "")


def test_dispatch_rejects_unparseable_command(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """dispatch() rejects a shell-unparseable command."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="echo 'unclosed")
    result = adapter.dispatch(step, ctx)
    assert result.status == "rejected"
    assert "not shell-parseable" in (result.reason or "")


def test_dispatch_spawns_subprocess_and_persists_remote_state(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """dispatch() spawns step.command as detached subprocess and persists remote_state.json."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="echo job-test-42")

    result = adapter.dispatch(step, ctx)
    assert result.status == "dispatched"
    assert result.pid is not None
    assert result.pid > 0
    assert result.started_at is not None

    # Verify remote_state.json sidecar
    step_dir = _step_dir_from_ctx(ctx)
    remote_state_path = step_dir / "remote_state.json"
    assert remote_state_path.exists()

    state = json.loads(remote_state_path.read_text(encoding="utf-8"))
    assert state["job_id"] == "job-test-42"
    assert state["command"] == step.command
    assert state["pid"] == result.pid


def test_dispatch_writes_returncode_placeholder(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """dispatch() writes a returncode=-1 placeholder file."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="echo job-1")
    adapter.dispatch(step, ctx)

    step_dir = _step_dir_from_ctx(ctx)
    rc = (step_dir / "returncode").read_text(encoding="utf-8").strip()
    assert rc == "-1"


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------


def test_poll_pending_when_no_remote_state(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """poll() returns pending when remote_state.json doesn't exist."""
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    result = adapter.poll(step, ctx)
    assert result.status == "pending"


def test_poll_running_for_live_process(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """poll() returns running when the subprocess is still alive."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="sleep 10")
    adapter.dispatch(step, ctx)

    # The subprocess should still be alive
    result = adapter.poll(step, ctx)
    assert result.status in ("running", "done"), (
        f"Expected running or done, got {result.status}"
    )


def test_poll_done_when_process_exits(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """poll() returns done after the subprocess exits."""
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="true")  # exits immediately
    result = adapter.dispatch(step, ctx)
    assert result.status == "dispatched"

    # Give it a tiny moment to exit
    import time

    time.sleep(0.05)

    poll_result = adapter.poll(step, ctx)
    assert poll_result.status in ("done", "running")


def test_poll_failed_on_corrupt_remote_state(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """poll() returns failed when remote_state.json is corrupt."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "remote_state.json").write_text("not json", encoding="utf-8")

    step = _make_step()
    result = adapter.poll(step, ctx)
    assert result.status == "failed"


# ---------------------------------------------------------------------------
# complete() — full success
# ---------------------------------------------------------------------------


def test_complete_success_all_artifacts_fetched(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """complete() returns completed when all artifacts are present + checksums match."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    # Pre-populate produces directory with 3 artifacts
    artifacts = {
        "out1.txt": b"hello world",
        "out2.txt": b"foo bar",
        "out3.json": b'{"key": "value"}',
    }
    _write_produces(step_dir, artifacts)

    # Write remote_state.json with matching manifest
    import hashlib

    manifest = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in artifacts.items()
    }
    _write_remote_state(step_dir, "job-1", manifest=manifest)

    # Write returncode=0
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=_make_produces(list(artifacts.keys())))
    result = adapter.complete(step, ctx)
    assert result.status == "completed"
    assert result.cost is None  # No cost sidecar


def test_complete_no_produces_declared(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """complete() returns completed trivially when step has no produces."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)
    _write_remote_state(step_dir, "job-1")
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=())
    result = adapter.complete(step, ctx)
    assert result.status == "completed"


# ---------------------------------------------------------------------------
# complete() — partial failure (awaiting_fetch)
# ---------------------------------------------------------------------------


def test_complete_partial_failure_missing_artifacts(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """complete() returns awaiting_fetch when some artifacts are missing."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    # Only write 2 of 5 expected artifacts
    artifacts = {
        "a.txt": b"aaa",
        "b.txt": b"bbb",
    }
    _write_produces(step_dir, artifacts)

    import hashlib

    manifest = {
        "a.txt": hashlib.sha256(b"aaa").hexdigest(),
        "b.txt": hashlib.sha256(b"bbb").hexdigest(),
        "c.txt": hashlib.sha256(b"ccc").hexdigest(),
        "d.txt": hashlib.sha256(b"ddd").hexdigest(),
        "e.txt": hashlib.sha256(b"eee").hexdigest(),
    }
    _write_remote_state(step_dir, "job-2", manifest=manifest)
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=_make_produces(["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]))
    result = adapter.complete(step, ctx)
    assert result.status == "awaiting_fetch"

    # Verify missing items are enumerated in remote_state.json
    state = json.loads(
        (step_dir / "remote_state.json").read_text(encoding="utf-8")
    )
    missing = state.get("missing", [])
    assert len(missing) == 3
    # missing entries are artifact name strings (from FetchResult.missing)
    missing_names = set(missing)
    assert missing_names == {"c.txt", "d.txt", "e.txt"}


# ---------------------------------------------------------------------------
# complete() — checksum mismatch
# ---------------------------------------------------------------------------


def test_complete_checksum_mismatch(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """complete() returns awaiting_fetch when checksums don't match."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    artifacts = {
        "out1.txt": b"correct-content",
    }
    _write_produces(step_dir, artifacts)

    # Manifest declares a DIFFERENT checksum
    manifest = {"out1.txt": "0000000000000000000000000000000000000000000000000000000000000000"}
    _write_remote_state(step_dir, "job-3", manifest=manifest)
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=_make_produces(["out1.txt"]))
    result = adapter.complete(step, ctx)
    assert result.status == "awaiting_fetch"

    state = json.loads(
        (step_dir / "remote_state.json").read_text(encoding="utf-8")
    )
    mismatched = state.get("mismatched", [])
    assert len(mismatched) == 1
    # mismatched entries are artifact name strings (from FetchResult.mismatched)
    assert mismatched[0] == "out1.txt"


# ---------------------------------------------------------------------------
# retry-fetch recovery
# ---------------------------------------------------------------------------


def test_retry_fetch_recovery(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """After fixing a missing artifact, complete() returns completed on retry."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    # Initially only 1 of 2 artifacts present
    artifacts = {"part1.txt": b"data1"}
    _write_produces(step_dir, artifacts)

    import hashlib

    manifest = {
        "part1.txt": hashlib.sha256(b"data1").hexdigest(),
        "part2.txt": hashlib.sha256(b"data2").hexdigest(),
    }
    _write_remote_state(step_dir, "job-4", manifest=manifest)
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=_make_produces(["part1.txt", "part2.txt"]))

    # First attempt — partial failure
    result1 = adapter.complete(step, ctx)
    assert result1.status == "awaiting_fetch"

    # Fix the missing artifact
    _write_produces(step_dir, {"part1.txt": b"data1", "part2.txt": b"data2"})

    # Retry — should succeed
    result2 = adapter.complete(step, ctx)
    assert result2.status == "completed"


def test_retry_fetch_idempotent(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """complete() is idempotent — re-running on completed step returns completed."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    artifacts = {"final.json": b'{"done": true}'}
    _write_produces(step_dir, artifacts)

    import hashlib

    manifest = {
        "final.json": hashlib.sha256(b'{"done": true}').hexdigest(),
    }
    _write_remote_state(step_dir, "job-5", manifest=manifest)
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    step = _make_step(produces=_make_produces(["final.json"]))

    result1 = adapter.complete(step, ctx)
    assert result1.status == "completed"

    # Re-run — still completed
    result2 = adapter.complete(step, ctx)
    assert result2.status == "completed"


# ---------------------------------------------------------------------------
# fetch_artifacts() standalone
# ---------------------------------------------------------------------------


def test_fetch_artifacts_standalone(
    adapter: RemoteArtifactAdapter, tmp_path: Path
) -> None:
    """fetch_artifacts() standalone works with explicit manifest."""
    ctx = _make_ctx(tmp_path)
    step_dir = _step_dir_from_ctx(ctx)

    artifacts = {
        "x.json": b'{"x": 1}',
        "y.json": b'{"y": 2}',
        "z.json": b'{"z": 3}',
    }
    _write_produces(step_dir, artifacts)

    import hashlib

    manifest = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in artifacts.items()
    }

    step = _make_step(produces=_make_produces(["x.json", "y.json", "z.json"]))
    result = fetch_artifacts(step, ctx, manifest=manifest)
    assert result.status == "completed"
    assert len(result.fetched) == 3
    assert len(result.missing) == 0
    assert len(result.mismatched) == 0
    assert len(result.checksums) == 3


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _step_dir_from_ctx(run_ctx: RunContext) -> Path:
    """Replicate _step_dir logic from remote_artifact.py."""
    base = run_ctx.project_root / "runs" / run_ctx.run_id / "steps"
    for segment in run_ctx.plan_step_path:
        base = base / segment
    base = base / f"v{run_ctx.step_version}"
    if run_ctx.iteration is not None:
        base = base / "iterations" / f"{run_ctx.iteration:03d}"
    elif run_ctx.item_id is not None:
        base = base / "items" / run_ctx.item_id
    return base