"""Event normalization for author-test golden diffs."""

# We strip 'hash' rather than recomputing — chain hashes are downstream of stripped fields, and structural drift is the diff signal.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_VOLATILE_FIELDS = ("ts", "hash", "run_id", "pid")


def _rewrite_paths(value: Any, run_dir_str: str | None) -> Any:
    if run_dir_str is None:
        return value
    if isinstance(value, str):
        if value == run_dir_str:
            return "<RUN_DIR>"
        prefix = run_dir_str.rstrip("/") + "/"
        if value.startswith(prefix):
            return "<RUN_DIR>/" + value[len(prefix):]
        return value
    if isinstance(value, dict):
        return {k: _rewrite_paths(v, run_dir_str) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_paths(v, run_dir_str) for v in value]
    return value


def normalize_events(
    events: list[dict[str, Any]],
    *,
    run_dir: Path | None,
) -> list[dict[str, Any]]:
    run_dir_str = str(run_dir) if run_dir is not None else None
    out: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        stripped = {k: v for k, v in ev.items() if k not in _VOLATILE_FIELDS}
        out.append(_rewrite_paths(stripped, run_dir_str))
    return out


def dump_events_jsonl(events: list[dict[str, Any]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(
                json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            )
            fh.write("\n")
