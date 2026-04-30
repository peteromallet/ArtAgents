from __future__ import annotations

from typing import Protocol

from artagents.enriched_arrangement import EnrichedArrangement, ReviewerFinding


class Reviewer(Protocol):
    name: str

    def review(self, enriched: EnrichedArrangement) -> list[ReviewerFinding]: ...
