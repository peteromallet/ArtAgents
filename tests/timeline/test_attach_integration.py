"""Tests for timeline integration with astrid attach — three branches for timeline resolution."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.session import cli
from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.paths import ASTRID_HOME_ENV


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Seed ASTRID_HOME + identity + a demo project with timelines."""
    monkeypatch.setenv(ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))

    # Seed demo project.
    pdir = tmp_path / "projects" / "demo"
    pdir.mkdir(parents=True)
    (pdir / "runs").mkdir()
    (pdir / "sources").mkdir()

    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _seed_timeline(
    projects_root: Path,
    project_slug: str,
    *,
    slug: str = "default",
    name: str = "Default",
    is_default: bool = True,
) -> str:
    """Create a minimal timeline and return its ULID."""
    from astrid.threads.ids import generate_ulid

    ulid = generate_ulid()
    tdir = projects_root / project_slug / "timelines" / ulid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "assembly.json").write_text(
        json.dumps({"schema_version": 1, "assembly": {}}), encoding="utf-8"
    )
    (tdir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contributing_runs": [],
                "final_outputs": [],
                "tombstoned_at": None,
            }
        ),
        encoding="utf-8",
    )
    (tdir / "display.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": slug,
                "name": name,
                "is_default": is_default,
            }
        ),
        encoding="utf-8",
    )
    return ulid


def _write_project_json(
    projects_root: Path,
    project_slug: str,
    *,
    default_timeline_id: str | None = None,
) -> None:
    (projects_root / project_slug / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": project_slug,
                "schema_version": 1,
                "slug": project_slug,
                "updated_at": "2026-05-11T00:00:00Z",
                "default_timeline_id": default_timeline_id,
            }
        ),
        encoding="utf-8",
    )


def _args(**kw: object) -> argparse.Namespace:
    defaults = {
        "project": "demo",
        "timeline": None,
        "session": None,
        "as_agent": None,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Branch 1: explicit --timeline
# ---------------------------------------------------------------------------


class TestExplicitTimeline:
    def test_explicit_timeline_resolves_correctly(self, env: dict[str, Path]) -> None:
        projects = env["projects"]
        ulid = _seed_timeline(projects, "demo", slug="alpha")
        _write_project_json(projects, "demo", default_timeline_id=ulid)

        buf = StringIO()
        rc = cli.cmd_attach(_args(timeline="alpha"), out=buf)
        assert rc == 0
        output = buf.getvalue()
        assert "session created" in output
        assert "export ASTRID_SESSION_ID=" in output
        assert "timeline: alpha" in output
        # Should NOT show the "Using default timeline" hint when explicit.
        # (It may or may not — the explicit path bypasses the default-resolution message.)

    def test_explicit_timeline_not_found_errors(self, env: dict[str, Path]) -> None:
        projects = env["projects"]
        ulid = _seed_timeline(projects, "demo", slug="alpha")
        _write_project_json(projects, "demo", default_timeline_id=ulid)

        buf = StringIO()
        import sys
        from io import StringIO as StderrCapture

        stderr_buf = StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            rc = cli.cmd_attach(_args(timeline="nonexistent"), out=buf)
        finally:
            sys.stderr = old_stderr

        assert rc == 2
        assert "not found" in stderr_buf.getvalue()


# ---------------------------------------------------------------------------
# Branch 2: default present (stderr message)
# ---------------------------------------------------------------------------


class TestDefaultTimeline:
    def test_default_timeline_prints_stderr_hint(self, env: dict[str, Path]) -> None:
        projects = env["projects"]
        ulid = _seed_timeline(projects, "demo", slug="primary")
        _write_project_json(projects, "demo", default_timeline_id=ulid)

        buf = StringIO()
        import sys
        from io import StringIO as StderrCapture

        stderr_buf = StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            rc = cli.cmd_attach(_args(), out=buf)
        finally:
            sys.stderr = old_stderr

        assert rc == 0
        stderr_output = stderr_buf.getvalue()
        assert "Using default timeline: primary" in stderr_output
        assert "Use --timeline to override" in stderr_output

        # stdout should show the resolved slug, not (none).
        stdout_output = buf.getvalue()
        assert "timeline: primary" in stdout_output
        assert "timeline: (none)" not in stdout_output


# ---------------------------------------------------------------------------
# Branch 3: none present (prompt mocked / non-interactive error)
# ---------------------------------------------------------------------------


class TestNoDefaultTimeline:
    def test_non_interactive_errors_clearly(self, env: dict[str, Path]) -> None:
        """When no --timeline and no default, timelines exist, and stdin is not a tty, error with hint."""
        projects = env["projects"]
        # Seed a timeline so timelines *exist* but none is the default.
        _seed_timeline(projects, "demo", slug="alpha", is_default=False)
        _write_project_json(projects, "demo")

        buf = StringIO()
        import sys

        stderr_buf = StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            rc = cli.cmd_attach(_args(), out=buf)
        finally:
            sys.stderr = old_stderr

        assert rc == 2
        stderr_output = stderr_buf.getvalue()
        assert "no default timeline; pass --timeline" in stderr_output

    def test_no_timelines_at_all(self, env: dict[str, Path]) -> None:
        """No timelines exist at all — bootstrap case: attach succeeds with timeline=None."""
        projects = env["projects"]
        _write_project_json(projects, "demo")

        buf = StringIO()
        import sys

        stderr_buf = StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            rc = cli.cmd_attach(_args(), out=buf)
        finally:
            sys.stderr = old_stderr

        # Bootstrap: attach succeeds even without timelines.
        assert rc == 0
        # stdout should show timeline: (none) since there are no timelines yet.
        stdout_output = buf.getvalue()
        assert "timeline: (none)" in stdout_output