#!/usr/bin/env python3
"""Text matching helpers shared by validate.py."""

from __future__ import annotations

import re
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def token_set_similarity(expected: str, actual: str) -> float:
    exp = set(tokenize(expected))
    if not exp:
        return 1.0
    act = set(tokenize(actual))
    return len(exp & act) / len(exp)


def segments_in_range(segments: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [
        seg
        for seg in segments
        if float(seg.get("end", 0)) > start and float(seg.get("start", 0)) < end
    ]
