"""Tests for astrid.core.timeline.paths — slug/ULID validators, path constructors, find helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.project.paths import ProjectPathError
from astrid.core.timeline.paths import (
    _TIMELINE_SLUG_RE,
    assembly_path,
    display_path,
    find_timeline_by_slug,
    find_timeline_slug_for_ulid,
    manifest_path,
    timeline_dir,
    timelines_dir,
    validate_timeline_slug,
    validate_timeline_ulid,
)


# ---------------------------------------------------------------------------
# validate_timeline_slug
# ---------------------------------------------------------------------------


class TestValidateTimelineSlug:
    """Slug validation: must match ^[a-z][a-z0-9-]{0,31}$."""

    VALID = [
        "a",
        "abc",
        "default",
        "my-timeline",
        "v2",
        "a-b-c",
        "x" * 32,  # max length
    ]
    INVALID = [
        # Leading digit
        "0abc",
        "1timeline",
        # Leading hyphen
        "-abc",
        # Underscore (not allowed)
        "my_timeline",
        "test_slug",
        # Too long
        "a" * 33,
        "x" * 64,
        # Uppercase
        "ABC",
        "MyTimeline",
        # Empty
        "",
        # Non-string
        42,
        None,
        b"bytes",
    ]

    def test_valid_slugs(self) -> None:
        for slug in self.VALID:
            assert validate_timeline_slug(slug) == slug

    def test_invalid_slugs_raise(self) -> None:
        for slug in self.INVALID:
            with pytest.raises(ProjectPathError):
                validate_timeline_slug(slug)

    def test_regex_rejects_underscores(self) -> None:
        assert _TIMELINE_SLUG_RE.fullmatch("my_slug") is None

    def test_regex_rejects_leading_digit(self) -> None:
        assert _TIMELINE_SLUG_RE.fullmatch("1abc") is None

    def test_regex_rejects_empty(self) -> None:
        assert _TIMELINE_SLUG_RE.fullmatch("") is None

    def test_regex_max_length(self) -> None:
        assert _TIMELINE_SLUG_RE.fullmatch("a" * 32) is not None
        assert _TIMELINE_SLUG_RE.fullmatch("a" * 33) is None


# ---------------------------------------------------------------------------
# validate_timeline_ulid
# ---------------------------------------------------------------------------


class TestValidateTimelineUlid:
    def test_valid_ulid_passes(self) -> None:
        from astrid.threads.ids import generate_ulid

        ulid = generate_ulid()
        assert validate_timeline_ulid(ulid) == ulid

    def test_invalid_ulid_raises(self) -> None:
        with pytest.raises(ProjectPathError):
            validate_timeline_ulid("not-a-ulid")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ProjectPathError):
            validate_timeline_ulid("")

    def test_none_raises(self) -> None:
        with pytest.raises(ProjectPathError):
            validate_timeline_ulid(None)

    def test_wrong_length_raises(self) -> None:
        with pytest.raises(ProjectPathError):
            validate_timeline_ulid("01A" * 8 + "X")  # 25 chars
        with pytest.raises(ProjectPathError):
            validate_timeline_ulid("01A" * 9)  # 27 chars


# ---------------------------------------------------------------------------
# Path constructors
# ---------------------------------------------------------------------------


class TestPathConstructors:
    """Path helpers compose correctly under a given root."""

    def test_timelines_dir(self, tmp_projects_root: Path) -> None:
        d = timelines_dir("demo", root=str(tmp_projects_root))
        assert d == tmp_projects_root / "demo" / "timelines"
        assert d.parent.name == "demo"

    def test_timeline_dir_validates_ulid(self, tmp_projects_root: Path) -> None:
        with pytest.raises(ProjectPathError):
            timeline_dir("demo", "not-a-ulid", root=str(tmp_projects_root))

    def test_assembly_path(self, tmp_projects_root: Path) -> None:
        from astrid.threads.ids import generate_ulid

        ulid = generate_ulid()
        ap = assembly_path("demo", ulid, root=str(tmp_projects_root))
        assert ap.name == "assembly.json"
        assert ap.parent.name == ulid
        assert ap.parent.parent.name == "timelines"

    def test_manifest_path(self, tmp_projects_root: Path) -> None:
        from astrid.threads.ids import generate_ulid

        ulid = generate_ulid()
        mp = manifest_path("demo", ulid, root=str(tmp_projects_root))
        assert mp.name == "manifest.json"

    def test_display_path(self, tmp_projects_root: Path) -> None:
        from astrid.threads.ids import generate_ulid

        ulid = generate_ulid()
        dp = display_path("demo", ulid, root=str(tmp_projects_root))
        assert dp.name == "display.json"


# ---------------------------------------------------------------------------
# find_timeline_by_slug
# ---------------------------------------------------------------------------


class TestFindTimelineBySlug:
    def test_returns_none_when_timelines_dir_absent(
        self, tmp_projects_root: Path
    ) -> None:
        # No timelines/ dir at all.
        (tmp_projects_root / "demo").mkdir()
        result = find_timeline_by_slug("demo", "test", root=str(tmp_projects_root))
        assert result is None

    def test_returns_none_when_no_match(
        self, tmp_projects_root: Path
    ) -> None:
        _seed_timeline(tmp_projects_root, "demo", slug="primary", name="Primary")
        result = find_timeline_by_slug("demo", "nonexistent", root=str(tmp_projects_root))
        assert result is None

    def test_finds_matching_slug(
        self, tmp_projects_root: Path
    ) -> None:
        ulid = _seed_timeline(tmp_projects_root, "demo", slug="primary", name="Primary")
        result = find_timeline_by_slug("demo", "primary", root=str(tmp_projects_root))
        assert result is not None
        found_ulid, found_dir = result
        assert found_ulid == ulid
        assert found_dir.name == ulid

    def test_finds_among_multiple(self, tmp_projects_root: Path) -> None:
        _seed_timeline(tmp_projects_root, "demo", slug="alpha", name="Alpha")
        beta_ulid = _seed_timeline(tmp_projects_root, "demo", slug="beta", name="Beta")
        _seed_timeline(tmp_projects_root, "demo", slug="gamma", name="Gamma")
        result = find_timeline_by_slug("demo", "beta", root=str(tmp_projects_root))
        assert result is not None
        assert result[0] == beta_ulid

    def test_skips_dirs_without_display_json(self, tmp_projects_root: Path) -> None:
        td = timelines_dir("demo", root=str(tmp_projects_root))
        td.mkdir(parents=True)
        bogus = td / "01HXYZABCDEFGHJKMNPQRSTVWXYZ"
        bogus.mkdir()
        # No display.json — should be skipped.
        result = find_timeline_by_slug("demo", "anything", root=str(tmp_projects_root))
        assert result is None


# ---------------------------------------------------------------------------
# find_timeline_slug_for_ulid
# ---------------------------------------------------------------------------


class TestFindTimelineSlugForUlid:
    def test_returns_none_when_display_json_absent(self, tmp_projects_root: Path) -> None:
        from astrid.threads.ids import generate_ulid

        ulid = generate_ulid()
        slug = find_timeline_slug_for_ulid("demo", ulid, root=str(tmp_projects_root))
        assert slug is None

    def test_returns_slug_for_existing_ulid(self, tmp_projects_root: Path) -> None:
        ulid = _seed_timeline(tmp_projects_root, "demo", slug="primary", name="Primary")
        slug = find_timeline_slug_for_ulid("demo", ulid, root=str(tmp_projects_root))
        assert slug == "primary"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_timeline(
    projects_root: Path,
    project_slug: str,
    *,
    slug: str = "default",
    name: str = "Default",
) -> str:
    """Create a minimal timeline under *projects_root* and return its ULID."""
    import json

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
                "is_default": True,
            }
        ),
        encoding="utf-8",
    )
    return ulid