"""Round-trip fixture test pinning timeline JSON byte-equivalence.

Phase 2 prerequisite: this is the regression gate that the upcoming
`Timeline` domain class refactor must keep green. Three assertions:

1. `examples/hype.timeline.full.json` round-trips load -> dump
   byte-for-byte (covers tracks, theme_overrides, generation_defaults,
   per-clip animation/transition/effects, mixed clipTypes).
2. Unknown top-level fields are preserved across load/dump.
   xfail today: the loader currently rejects unknown keys via
   `_raise_unknown_keys`. Phase 2 will introduce a passthrough bag and
   flip this to passing.
3. ArtAgents' Python allowlists (`_TIMELINE_TOP_ALLOWED`,
   `_CLIP_ALLOWED`, `_TRACK_ALLOWED`) match the field set declared in
   the canonical `@banodoco/timeline-schema` JSON Schema. The shared
   schema is the source of truth.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "examples" / "hype.timeline.full.json"

# The shared schema lives inside the npm-installed package under remotion/.
# That's the only on-disk copy available without network. If the install
# moves we surface a clear skip rather than a misleading pass.
_SHARED_SCHEMA_CANDIDATES = (
    REPO_ROOT
    / "remotion"
    / "node_modules"
    / "@banodoco"
    / "timeline-schema"
    / "python"
    / "banodoco_timeline_schema"
    / "timeline.schema.json",
)


def _load_shared_schema() -> dict | None:
    for candidate in _SHARED_SCHEMA_CANDIDATES:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


# Make the in-tree artagents package importable when running pytest from
# the repo root (it already is) — defensive, costs nothing.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artagents.timeline import (  # noqa: E402
    _CLIP_ALLOWED,
    _TIMELINE_TOP_ALLOWED,
    _TRACK_ALLOWED,
    load_timeline,
    save_timeline,
)


class TimelineRoundTripFixtureTest(unittest.TestCase):
    """Phase 2 regression gate."""

    def setUp(self) -> None:
        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"fixture missing: {FIXTURE_PATH}",
        )
        self.original_text = FIXTURE_PATH.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 1. Byte-equivalent round-trip
    # ------------------------------------------------------------------
    def test_round_trip_is_byte_equivalent(self) -> None:
        config = load_timeline(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "roundtrip.json"
            save_timeline(config, out_path)
            roundtripped = out_path.read_text(encoding="utf-8")

        if self.original_text != roundtripped:
            # Surface a JSON-normalised diff so it's obvious what shifted.
            original_norm = json.dumps(
                json.loads(self.original_text), indent=2, sort_keys=True
            )
            roundtrip_norm = json.dumps(
                json.loads(roundtripped), indent=2, sort_keys=True
            )
            self.assertEqual(
                original_norm,
                roundtrip_norm,
                "Round-trip changed timeline content (key order normalised for diff).",
            )
            # Same JSON content, byte mismatch => formatting drift.
            self.fail(
                "Round-trip preserved JSON content but not exact bytes "
                "(formatting drift in save_timeline). Phase 2 must keep "
                "byte-equivalence."
            )

        # Belt-and-braces: every section we care about survived as JSON.
        loaded = json.loads(roundtripped)
        original = json.loads(self.original_text)
        for section in (
            "theme",
            "theme_overrides",
            "tracks",
            "clips",
        ):
            self.assertEqual(
                loaded.get(section),
                original.get(section),
                f"section {section!r} drifted after round-trip",
            )

    # ------------------------------------------------------------------
    # 2. Unknown top-level field preservation (xfail today)
    # ------------------------------------------------------------------
    def test_unknown_top_level_field_is_preserved(self) -> None:
        """Phase 2 will introduce a passthrough bag for unknown keys.

        Today's loader calls `_raise_unknown_keys("Timeline", ...)` which
        rejects anything outside `_TIMELINE_TOP_ALLOWED`. We expect this
        test to fail until Phase 2 lands; when it does, the xfail wrapper
        will report XPASS and force us to flip the marker.
        """
        sentinel_key = "_phase2_canary"
        sentinel_value = "preserve me"

        injected = json.loads(self.original_text)
        injected[sentinel_key] = sentinel_value

        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "with_canary.json"
            in_path.write_text(json.dumps(injected, indent=2), encoding="utf-8")

            try:
                config = load_timeline(in_path)
            except ValueError as exc:
                # Today's behaviour: rejected by _raise_unknown_keys.
                # Use the standard xfail mechanism via SkipTest under
                # unittest, but for pytest-aware xfail we raise the
                # documented marker.
                raise _XFailExpected(
                    f"loader rejects unknown top-level keys today: {exc}"
                )

            out_path = Path(tmp) / "after_roundtrip.json"
            save_timeline(config, out_path)
            after = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(
            after.get(sentinel_key),
            sentinel_value,
            "Phase 2 expected: unknown top-level field survives load/dump.",
        )

    # ------------------------------------------------------------------
    # 3. Allowlist parity with the shared schema package
    # ------------------------------------------------------------------
    def test_allowlist_parity_with_shared_schema(self) -> None:
        schema = _load_shared_schema()
        if schema is None:
            self.skipTest(
                "Shared @banodoco/timeline-schema JSON Schema not found; "
                "expected at one of: "
                + ", ".join(str(p) for p in _SHARED_SCHEMA_CANDIDATES)
                + ". Build the package (npm run -w @banodoco/timeline-schema "
                "build) to enable this assertion."
            )

        defs = schema.get("definitions") or schema.get("$defs") or {}
        timeline_def = defs.get("TimelineConfig")
        clip_def = defs.get("TimelineClip")
        self.assertIsNotNone(timeline_def, "TimelineConfig missing in shared schema")
        self.assertIsNotNone(clip_def, "TimelineClip missing in shared schema")

        shared_top = set((timeline_def.get("properties") or {}).keys())
        shared_clip = set((clip_def.get("properties") or {}).keys())

        # TrackDefinition is inlined under TimelineConfig.tracks.items.
        tracks_node = (timeline_def.get("properties") or {}).get("tracks") or {}
        track_items = tracks_node.get("items") or {}
        shared_track = set((track_items.get("properties") or {}).keys())

        # The shared schema is the source of truth (per artagents/timeline.py
        # docstring: "the JSON-Schema validator there is the canonical shape
        # check"). ArtAgents' frozensets must match exactly.
        self.assertEqual(
            set(_TIMELINE_TOP_ALLOWED),
            shared_top,
            "Timeline top-level allowlist drift between ArtAgents "
            "(_TIMELINE_TOP_ALLOWED) and shared schema (TimelineConfig). "
            f"only-in-artagents={set(_TIMELINE_TOP_ALLOWED) - shared_top}, "
            f"only-in-schema={shared_top - set(_TIMELINE_TOP_ALLOWED)}",
        )
        self.assertEqual(
            set(_CLIP_ALLOWED),
            shared_clip,
            "Clip allowlist drift between ArtAgents (_CLIP_ALLOWED) and "
            "shared schema (TimelineClip). "
            f"only-in-artagents={set(_CLIP_ALLOWED) - shared_clip}, "
            f"only-in-schema={shared_clip - set(_CLIP_ALLOWED)}",
        )
        self.assertEqual(
            set(_TRACK_ALLOWED),
            shared_track,
            "Track allowlist drift between ArtAgents (_TRACK_ALLOWED) and "
            "shared schema (TimelineConfig.tracks[]). "
            f"only-in-artagents={set(_TRACK_ALLOWED) - shared_track}, "
            f"only-in-schema={shared_track - set(_TRACK_ALLOWED)}",
        )


class _XFailExpected(Exception):
    """Internal sentinel translated to pytest.xfail at the boundary."""


# Wire #2 to pytest's xfail using the no-extra-imports approach: a
# pytest collection hook only fires under pytest, so we fall back to a
# unittest skip when run under plain unittest. The decorator below uses
# pytest.mark.xfail when available, else unittest.expectedFailure.
try:
    import pytest  # type: ignore[import-not-found]

    TimelineRoundTripFixtureTest.test_unknown_top_level_field_is_preserved = pytest.mark.xfail(
        reason=(
            "Phase 2 work: loader currently rejects unknown top-level keys "
            "via _raise_unknown_keys. Flip when the passthrough bag lands."
        ),
        strict=True,
        raises=(_XFailExpected, AssertionError),
    )(TimelineRoundTripFixtureTest.test_unknown_top_level_field_is_preserved)
except ImportError:  # pragma: no cover - pytest is the project's runner
    TimelineRoundTripFixtureTest.test_unknown_top_level_field_is_preserved = (
        unittest.expectedFailure(
            TimelineRoundTripFixtureTest.test_unknown_top_level_field_is_preserved
        )
    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
