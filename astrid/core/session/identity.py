"""Stable agent identity + first-run bootstrap.

The identity record (``~/.astrid/identity.json``) is the per-machine agent
slug new sessions inherit by default. ``astrid attach --as agent:<id>``
overrides for a single tab without rewriting the file.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.session.paths import identity_path

_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class IdentityError(ValueError):
    """Raised when an agent identity record is malformed or input is invalid."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Identity:
    agent_id: str
    created_at: str

    @classmethod
    def from_dict(cls, raw: Any) -> "Identity":
        if not isinstance(raw, dict):
            raise IdentityError("identity record must be an object")
        agent_id = raw.get("agent_id")
        created_at = raw.get("created_at")
        if not isinstance(agent_id, str) or _AGENT_ID_RE.fullmatch(agent_id) is None:
            raise IdentityError(
                "identity.agent_id must be a slug (lowercase letters/digits/_-, "
                f"start with letter or digit), got {agent_id!r}"
            )
        if not isinstance(created_at, str) or not created_at:
            raise IdentityError("identity.created_at must be a non-empty string")
        return cls(agent_id=agent_id, created_at=created_at)


def read_identity() -> Identity | None:
    """Return the on-disk identity, or ``None`` when it does not exist."""

    try:
        raw = read_json(identity_path())
    except FileNotFoundError:
        return None
    return Identity.from_dict(raw)


def write_identity(identity: Identity) -> None:
    write_json_atomic(identity_path(), asdict(identity))


def validate_agent_slug(raw: str) -> str:
    if not isinstance(raw, str) or _AGENT_ID_RE.fullmatch(raw) is None:
        raise IdentityError(
            "agent id must be a slug (lowercase letters/digits/_-, start with letter or digit)"
        )
    return raw


def bootstrap_identity(*, prompt: Callable[[str], str] | None = None) -> Identity:
    """Prompt for an agent slug and persist a new :class:`Identity`.

    Re-prompts on validation failure (up to 3 attempts). Surfaces
    :class:`IdentityError` after 3 invalid replies so callers can fall back
    to error messaging rather than spin forever. ``prompt`` defaults to
    :func:`builtins.input` resolved lazily so tests that monkeypatch
    ``builtins.input`` see the override.
    """

    if prompt is None:
        import builtins

        prompt = builtins.input
    for _ in range(3):
        try:
            reply = prompt("agent id (slug, e.g. claude-1): ").strip()
        except EOFError as exc:
            raise IdentityError(
                "agent identity is not configured and stdin is not interactive; "
                "run `astrid status` in an interactive shell"
            ) from exc
        try:
            slug = validate_agent_slug(reply)
        except IdentityError as exc:
            print(f"  invalid: {exc}")
            continue
        identity = Identity(agent_id=slug, created_at=_now_iso())
        write_identity(identity)
        return identity
    raise IdentityError("agent id bootstrap exhausted 3 attempts")
