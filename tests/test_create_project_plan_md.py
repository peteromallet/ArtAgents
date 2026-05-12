"""Tests for the per-project plan.md skeleton written by create_project."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.project import paths
from astrid.core.project.project import create_project


def test_create_project_writes_empty_plan_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))

    create_project("foo")

    plan_path = projects_root / "foo" / "plan.md"
    assert plan_path.exists(), "plan.md should be created at the project root"

    content = plan_path.read_text(encoding="utf-8")
    # Heading uses the slug.
    assert content.startswith("# foo — Plan"), f"unexpected heading; got:\n{content[:80]}"
    # Skeleton sections are present and empty.
    assert "## Current focus" in content
    assert "## Open threads" in content
    assert "## Key decisions" in content
    assert "## Notes" in content
    # No content beyond the section headings — every section header should be
    # followed by blank lines, not prose.
    for header in ("## Current focus", "## Open threads", "## Key decisions"):
        idx = content.index(header)
        # Two newlines after the header, then more whitespace before the next
        # `## ` or EOF — ensure we don't accidentally include narrative text.
        tail = content[idx + len(header):]
        next_header = tail.find("##")
        body = tail[: next_header if next_header != -1 else len(tail)]
        assert body.strip() == "", f"section {header!r} should be empty, got: {body!r}"


def test_create_project_does_not_overwrite_existing_plan_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))

    project_dir = projects_root / "foo"
    project_dir.mkdir(parents=True)
    plan_path = project_dir / "plan.md"
    plan_path.write_text("my notes", encoding="utf-8")

    create_project("foo", exist_ok=True)

    assert plan_path.read_text(encoding="utf-8") == "my notes"
