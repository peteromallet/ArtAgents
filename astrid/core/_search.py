"""Shared capability search across executors, orchestrators, and elements.

The match function is intentionally simple (token AND-search across a few
weighted fields). Callers pass a uniform record so the same scorer drives all
three CLIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Field weights tuned so explicit keyword and id matches outrank stray
# matches in the long description. Tweak in tests rather than at the call
# site so the three CLIs stay in lockstep.
FIELD_WEIGHTS: dict[str, float] = {
    "id": 8.0,
    "name": 5.0,
    "keywords": 6.0,
    "short_description": 4.0,
    "binaries": 5.0,
    "description": 1.5,
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class SearchRecord:
    id: str
    kind: str
    short_description: str
    fields: dict[str, str]


@dataclass(frozen=True)
class SearchHit:
    record: SearchRecord
    score: float


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(value or "")]


def search(records: Iterable[SearchRecord], terms: list[str], *, limit: int = 25) -> list[SearchHit]:
    query_tokens = [token for term in terms for token in tokenize(term)]
    if not query_tokens:
        return []

    hits: list[SearchHit] = []
    for record in records:
        score = _score_record(record, query_tokens)
        if score > 0:
            hits.append(SearchHit(record=record, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.record.id))
    if limit > 0:
        return hits[:limit]
    return hits


def _score_record(record: SearchRecord, query_tokens: list[str]) -> float:
    field_token_sets: dict[str, list[str]] = {
        name: tokenize(text) for name, text in record.fields.items()
    }
    total = 0.0
    matched_tokens: set[str] = set()
    for token in query_tokens:
        token_score = 0.0
        token_matched = False
        for field_name, weight in FIELD_WEIGHTS.items():
            tokens = field_token_sets.get(field_name)
            if not tokens:
                continue
            if token in tokens:
                token_score += weight
                token_matched = True
            elif any(token in candidate for candidate in tokens):
                token_score += weight * 0.4
                token_matched = True
        if token_matched:
            total += token_score
            matched_tokens.add(token)
    if not matched_tokens:
        return 0.0
    if matched_tokens == set(query_tokens):
        # Reward queries where every term landed somewhere.
        total *= 1.5
    return total


def short_description_or_truncated(short: str, description: str, *, limit: int = 117) -> str:
    if short:
        return short
    if not description:
        return ""
    text = description.strip().replace("\n", " ")
    if len(text) <= limit + 3:
        return text
    return text[:limit] + "..."


__all__ = [
    "FIELD_WEIGHTS",
    "SearchHit",
    "SearchRecord",
    "search",
    "short_description_or_truncated",
    "tokenize",
]
