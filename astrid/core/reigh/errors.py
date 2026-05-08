"""Errors raised by the Reigh DataProvider layer."""

from __future__ import annotations


class TimelineNotFoundError(RuntimeError):
    """Raised when reigh-data-fetch returns no timeline for the requested id."""


class TimelineVersionConflictError(RuntimeError):
    """Raised when update_timeline_config_versioned exhausts version-conflict retries."""

    def __init__(self, message: str, *, attempts: int, last_expected_version: int | None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_expected_version = last_expected_version
