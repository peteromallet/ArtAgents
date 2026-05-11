"""Session dataclass + JSON serialization.

A :class:`Session` is the per-tab binding record stored under
``~/.astrid/sessions/<ulid>.json``. Frozen — :func:`dataclasses.replace` is
used to produce updated copies (e.g. when WriterContext auto-rebinds the
``run_id`` after observing a fresh ``current_run.json``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from astrid.core.project.jsonio import read_json, write_json_atomic

SessionRole = Literal["writer", "reader", "orphan-pending"]
_ALLOWED_ROLES: tuple[SessionRole, ...] = ("writer", "reader", "orphan-pending")


class SessionValidationError(ValueError):
    """Raised when a session record fails validation."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Session:
    id: str
    project: str
    agent_id: str
    attached_at: str
    last_used_at: str
    role: SessionRole
    timeline: str | None = None
    timeline_id: str | None = None
    run_id: str | None = None

    def with_changes(self, **changes: Any) -> "Session":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_dict())

    @classmethod
    def from_dict(cls, raw: Any) -> "Session":
        if not isinstance(raw, dict):
            raise SessionValidationError("session record must be an object")
        try:
            role = raw["role"]
            if role not in _ALLOWED_ROLES:
                raise SessionValidationError(
                    f"session.role must be one of {_ALLOWED_ROLES}, got {role!r}"
                )
            return cls(
                id=_require_str(raw, "id"),
                project=_require_str(raw, "project"),
                timeline=_optional_str(raw, "timeline"),
                timeline_id=_optional_str(raw, "timeline_id"),
                run_id=_optional_str(raw, "run_id"),
                agent_id=_require_str(raw, "agent_id"),
                attached_at=_require_str(raw, "attached_at"),
                last_used_at=_require_str(raw, "last_used_at"),
                role=role,
            )
        except KeyError as exc:
            raise SessionValidationError(f"session missing field {exc.args[0]!r}") from exc

    @classmethod
    def from_json(cls, path: str | Path) -> "Session":
        return cls.from_dict(read_json(path))


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise SessionValidationError(f"session.{key} must be a non-empty string")
    return value


def _optional_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SessionValidationError(f"session.{key} must be null or a non-empty string")
    return value
