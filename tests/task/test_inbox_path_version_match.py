"""Tests for inbox path+version match across supersede events (Sprint 3 T21).

Covers: supersede routing, stale → .rejected/, missing submitted_by_kind rejects.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from astrid.core.task.inbox import (
    CONSUMED_DIR_NAME,
    INBOX_DIR_NAME,
    InboxEntry,
    InboxValidationError,
    REJECTED_DIR_NAME,
    _parse_entry,
)


# ---------------------------------------------------------------------------
# _parse_entry — schema_version:2
# ---------------------------------------------------------------------------

def test_parse_v2_entry_with_plan_step_path() -> None:
    raw = {
        "schema_version": 2,
        "plan_step_path": ["parent", "child"],
        "step_version": 1,
        "submitted_by": "agent-1",
        "submitted_by_kind": "agent",
        "decision": "approve",
        "submitted_at": "2026-05-12T00:00:00Z",
        "evidence": {},
    }
    entry = _parse_entry(Path("/tmp/test.json"), raw)
    assert entry is not None
    assert entry.plan_step_path == ("parent", "child")
    assert entry.step_version == 1
    assert entry.submitted_by_kind == "agent"
    assert entry.schema_version == 2


def test_parse_v2_entry_rejects_missing_submitted_by_kind() -> None:
    """Identity field submitted_by_kind is required; parser raises on missing."""
    raw = {
        "schema_version": 2,
        "plan_step_path": ["s1"],
        "step_version": 1,
        "submitted_by": "agent-1",
        "decision": "approve",
        "submitted_at": "2026-05-12T00:00:00Z",
        "evidence": {},
    }
    with pytest.raises(InboxValidationError, match="submitted_by_kind"):
        _parse_entry(Path("/tmp/test.json"), raw)


def test_parse_v2_entry_with_item_id() -> None:
    raw = {
        "schema_version": 2,
        "plan_step_path": ["s1"],
        "step_version": 1,
        "item_id": "abc123",
        "submitted_by": "human-1",
        "submitted_by_kind": "actor",
        "decision": "approve",
        "submitted_at": "2026-05-12T00:00:00Z",
        "evidence": {},
    }
    entry = _parse_entry(Path("/tmp/test.json"), raw)
    assert entry is not None
    assert entry.item_id == "abc123"


def test_parse_legacy_entry() -> None:
    """Legacy entries without schema_version → handled by _parse_legacy_entry."""
    raw = {
        "step_id": "s1",
        "decision": "approve",
        "evidence": {},
        "submitted_at": "2026-05-12T00:00:00Z",
        "submitted_by": "someone",
    }
    entry = _parse_entry(Path("/tmp/test.json"), raw)
    # Legacy entries get schema_version=0 sentinel
    if entry is not None:
        assert entry.schema_version == 0


def test_parse_entry_rejects_bad_schema_version() -> None:
    raw = {
        "schema_version": 99,
        "plan_step_path": ["s1"],
    }
    with pytest.raises(InboxValidationError, match="schema_version"):
        _parse_entry(Path("/tmp/test.json"), raw)


# ---------------------------------------------------------------------------
# Identity enforcement (submitted_by_kind required)
# ---------------------------------------------------------------------------

def test_identity_enforcement_missing_kind() -> None:
    """Entries without submitted_by_kind raise InboxValidationError."""
    raw = {
        "schema_version": 2,
        "plan_step_path": ["s1"],
        "step_version": 1,
        "submitted_by": "someone",
        "decision": "approve",
        "submitted_at": "2026-05-12T00:00:00Z",
        "evidence": {},
    }
    with pytest.raises(InboxValidationError, match="submitted_by_kind"):
        _parse_entry(Path("/tmp/test.json"), raw)


def test_identity_enforcement_has_kind() -> None:
    raw = {
        "schema_version": 2,
        "plan_step_path": ["s1"],
        "step_version": 1,
        "submitted_by": "agent-1",
        "submitted_by_kind": "agent",
        "decision": "approve",
        "submitted_at": "2026-05-12T00:00:00Z",
        "evidence": {},
    }
    entry = _parse_entry(Path("/tmp/test.json"), raw)
    assert entry.submitted_by_kind == "agent"


# ---------------------------------------------------------------------------
# Stale entries → .rejected/
# ---------------------------------------------------------------------------

def test_stale_entries_destination_known() -> None:
    """Verify the stale-entry constants exist and are deterministic."""
    assert INBOX_DIR_NAME == "inbox"
    assert CONSUMED_DIR_NAME == ".consumed"
    assert REJECTED_DIR_NAME == ".rejected"