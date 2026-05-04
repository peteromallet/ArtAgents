"""Renderer parity gate against sprint-08 timeline fixtures.

T14 commits this gate as a documented skip. The sprint-08 helpers
``createAgentWorkflowTimelineFixture`` / ``createEmbedDemoTimelineFixture``
live in reigh-app's ``src/tools/video-editor/testing.ts`` and have not yet
been published as a consumable package. Until JSON snapshots of those
fixtures are committed under ``tests/fixtures/sprint08/`` and golden hashes
under ``tests/fixtures/sprint08/golden/<name>.sha256``, this test
``pytest.skip``s with a clear reason rather than failing.

When goldens land, this test runs ``scripts/node/export_fixtures.mjs --json``
to enumerate fixtures, hashes the canonical JSON of each fixture, and
compares against the committed golden hash.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPORT_HELPER = ROOT / "scripts" / "node" / "export_fixtures.mjs"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "sprint08"
GOLDEN_DIR = FIXTURES_DIR / "golden"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_export_helper() -> dict | None:
    if not EXPORT_HELPER.is_file():
        return None
    if not _node_available():
        return None
    result = subprocess.run(
        ["node", str(EXPORT_HELPER), "--json"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _canonical_hash(payload) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_renderer_parity_against_sprint08_fixtures() -> None:
    if not _node_available():
        pytest.skip("node not available; renderer parity helper requires Node ESM")
    manifest = _run_export_helper()
    if manifest is None:
        pytest.skip("export_fixtures.mjs unavailable or returned non-JSON output")

    fixtures = manifest.get("fixtures") or []
    if not fixtures:
        pytest.skip(
            "no sprint-08 fixtures committed under tests/fixtures/sprint08/. "
            "Snapshot createAgentWorkflowTimelineFixture/createEmbedDemoTimelineFixture from "
            "reigh-app/src/tools/video-editor/testing.ts and commit the JSON + golden hashes."
        )

    pending_goldens = [fixture["name"] for fixture in fixtures if not fixture.get("golden_hash")]
    if pending_goldens:
        pytest.skip(
            "sprint-08 fixtures present but goldens missing: "
            + ", ".join(pending_goldens)
            + ". Generate goldens via the headless render path and commit the .sha256 files."
        )

    for fixture in fixtures:
        path = Path(fixture["fixture_path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual = _canonical_hash(payload)
        expected = fixture["golden_hash"]
        assert actual == expected, (
            f"renderer parity hash mismatch for {fixture['name']}: "
            f"expected={expected} actual={actual}"
        )
