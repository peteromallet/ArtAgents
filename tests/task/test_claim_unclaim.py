"""Tests for claim/unclaim verbs (Sprint 3 T21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.task.claim import (
    CLAIM_KIND,
    UNCLAIM_KIND,
    _make_claim_event,
    _make_unclaim_event,
    _parse_for_flag,
    build_parser,
)


def test_claim_event_shape() -> None:
    event = _make_claim_event(
        "s1", claimed_by="agent-1", claimed_by_kind="agent", writer_epoch=1
    )
    assert event["kind"] == CLAIM_KIND
    assert event["step"] == "s1"
    assert event["claimed_by"] == "agent-1"
    assert event["claimed_by_kind"] == "agent"
    assert event["writer_epoch"] == 1
    assert "ts" in event


def test_unclaim_event_shape() -> None:
    event = _make_unclaim_event(
        "parent/child", unclaimed_by="human-bob", unclaimed_by_kind="actor", writer_epoch=3
    )
    assert event["kind"] == UNCLAIM_KIND
    assert event["step"] == "parent/child"
    assert event["unclaimed_by"] == "human-bob"
    assert event["unclaimed_by_kind"] == "actor"
    assert event["writer_epoch"] == 3


def test_parse_for_flag_agent() -> None:
    ident, kind = _parse_for_flag("agent:gpt-5")
    assert ident == "gpt-5"
    assert kind == "agent"


def test_parse_for_flag_human() -> None:
    ident, kind = _parse_for_flag("human:Alice")
    assert ident == "Alice"
    assert kind == "actor"


def test_parse_for_flag_rejects_bare_string() -> None:
    import sys
    with pytest.raises(SystemExit):
        _parse_for_flag("nobody")


def test_parse_for_flag_rejects_empty_agent() -> None:
    import sys
    with pytest.raises(SystemExit):
        _parse_for_flag("agent:")


def test_parse_for_flag_rejects_empty_human() -> None:
    import sys
    with pytest.raises(SystemExit):
        _parse_for_flag("human:")


def test_build_parser_has_claim_and_unclaim() -> None:
    import argparse
    parser = build_parser()
    # Find the subparsers action
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            assert 'claim' in action.choices
            assert 'unclaim' in action.choices
            return
    pytest.fail("No _SubParsersAction found")