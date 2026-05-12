"""Tests for remote-artifact adapter rejection (Sprint 3 T22).

Asserts the exact deferral string + non-zero exit / exception raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.adapter import RunContext
from astrid.core.task.plan import Step

# Sprint 5a: the remote-artifact stub has been replaced by the real adapter.
# The deferral symbols (REMOTE_ARTIFACT_DEFERRAL, RemoteArtifactDeferralError,
# _deferral_message) no longer exist. This test file is replaced by
# test_remote_artifact_real.py in T12.
try:
    from astrid.core.adapter.remote_artifact import (  # noqa: F401
        REMOTE_ARTIFACT_DEFERRAL,
        RemoteArtifactAdapter,
        RemoteArtifactDeferralError,
        _deferral_message,
    )
except ImportError:
    import pytest  # noqa: F401
    pytest.skip(
        "remote-artifact stub removed in Sprint 5a T4; "
        "replaced by test_remote_artifact_real.py (T12)",
        allow_module_level=True,
    )


@pytest.fixture
def adapter() -> RemoteArtifactAdapter:
    return RemoteArtifactAdapter()


def _make_ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        slug="demo",
        run_id="run-1",
        project_root=tmp_path,
        plan_step_path=("s1",),
        step_version=1,
    )


def _make_step() -> Step:
    return Step(id="s1", adapter="remote-artifact", command="fetch-artifact")


def test_deferral_message_exact_string() -> None:
    """Verify the deferral message is exactly the string from the brief."""
    msg = _deferral_message("test-step")
    expected = (
        "astrid start / astrid next: step 'test-step' declares adapter 'remote-artifact'; "
        "not yet implemented (Sprint 5a). Use --adapter local or manual."
    )
    assert msg == expected


def test_remote_artifact_deferral_constant() -> None:
    """REMOTE_ARTIFACT_DEFERRAL is the template constant (with {step_id} placeholder)."""
    assert "{step_id}" in REMOTE_ARTIFACT_DEFERRAL
    assert "Sprint 5a" in REMOTE_ARTIFACT_DEFERRAL


def test_dispatch_raises_deferral_error(adapter: RemoteArtifactAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    with pytest.raises(RemoteArtifactDeferralError) as exc:
        adapter.dispatch(step, ctx)
    assert "remote-artifact" in str(exc.value)
    assert "Sprint 5a" in str(exc.value)
    assert "Use --adapter local or manual" in str(exc.value)


def test_poll_raises_deferral_error(adapter: RemoteArtifactAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    with pytest.raises(RemoteArtifactDeferralError):
        adapter.poll(step, ctx)


def test_complete_raises_deferral_error(adapter: RemoteArtifactAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    with pytest.raises(RemoteArtifactDeferralError):
        adapter.complete(step, ctx)


def test_deferral_error_is_runtime_error() -> None:
    """RemoteArtifactDeferralError inherits from RuntimeError so cmd_next can catch it."""
    assert issubclass(RemoteArtifactDeferralError, RuntimeError)


def test_step_id_interpolated_in_message() -> None:
    """The step id is dynamically interpolated."""
    msg_for_a = _deferral_message("step-a")
    msg_for_b = _deferral_message("step-b")
    assert "step-a" in msg_for_a
    assert "step-b" in msg_for_b
    assert msg_for_a != msg_for_b