"""Crockford ULID helpers for thread, run, and group records."""

from __future__ import annotations

import os
import re
import threading
import time

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_LENGTH = 26
ULID_RE = re.compile(r"^[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{26}$")

_RANDOM_BITS = 80
_RANDOM_MASK = (1 << _RANDOM_BITS) - 1
_STATE_LOCK = threading.Lock()
_LAST_MS = -1
_LAST_RANDOM = 0


def generate_ulid() -> str:
    """Return a 26-character Crockford ULID, monotonic within this process."""
    global _LAST_MS, _LAST_RANDOM

    now_ms = int(time.time() * 1000)
    with _STATE_LOCK:
        if now_ms > _LAST_MS:
            _LAST_MS = now_ms
            _LAST_RANDOM = int.from_bytes(os.urandom(10), "big")
        else:
            _LAST_RANDOM = (_LAST_RANDOM + 1) & _RANDOM_MASK
            if _LAST_RANDOM == 0:
                while now_ms <= _LAST_MS:
                    time.sleep(0.001)
                    now_ms = int(time.time() * 1000)
                _LAST_MS = now_ms
                _LAST_RANDOM = int.from_bytes(os.urandom(10), "big")
        value = (_LAST_MS << _RANDOM_BITS) | _LAST_RANDOM
    return _encode_crockford(value)


def generate_thread_id() -> str:
    return generate_ulid()


def generate_run_id() -> str:
    return generate_ulid()


def generate_group_id() -> str:
    return generate_ulid()


def is_ulid(value: object) -> bool:
    return isinstance(value, str) and ULID_RE.fullmatch(value) is not None


def require_ulid(value: object, field: str = "id") -> str:
    if not is_ulid(value):
        raise ValueError(f"{field} must be a 26-character Crockford ULID")
    return str(value)


def _encode_crockford(value: int) -> str:
    chars = ["0"] * ULID_LENGTH
    for index in range(ULID_LENGTH - 1, -1, -1):
        chars[index] = CROCKFORD_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)
