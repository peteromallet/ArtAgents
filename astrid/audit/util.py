from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|bearer|credential)", re.I)
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|hf_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{12,})"
)
MAX_TEXT_PREVIEW = 500


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "item"


def stable_id(*parts: object) -> str:
    raw = "|".join(json.dumps(part, sort_keys=True, default=str) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    label = _slug(str(parts[0])) if parts else "audit"
    return f"{label}-{digest}"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted[str(key)] = "<redacted>" if SECRET_KEY_RE.search(str(key)) else redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str) and SECRET_VALUE_RE.search(value):
        return SECRET_VALUE_RE.sub("<redacted>", value)
    return value


def file_metadata(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    stat = path.stat()
    metadata: dict[str, Any] = {
        "size_bytes": stat.st_size,
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    if stat.st_size <= 16 * 1024 * 1024:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata["sha256"] = digest.hexdigest()
    return metadata


def text_preview(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        return None
    if path.suffix.lower() not in {".txt", ".json", ".jsonl", ".md", ".srt", ".csv", ".log"}:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text[:MAX_TEXT_PREVIEW] if text else None
