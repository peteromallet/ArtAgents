"""Thread attribution, lifecycle, and abandoned run reaping."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ids import generate_thread_id, is_ulid, require_ulid
from .index import ThreadIndexStore
from .record import write_run_record
from .schema import empty_threads_index, make_thread_record, utc_now

OPEN_IDLE_DAYS = 7
ARCHIVED_REOPEN_HOURS = 48

_REAPER_RAN = False


@dataclass(frozen=True)
class AttributionDecision:
    thread_id: str
    source: str
    label: str
    created: bool = False
    reopened: bool = False
    notice: str | None = None
    run_number: int = 0


def attribute_run(
    *,
    repo_root: Path,
    request: Any,
    run_id: str,
    out_path: Path,
    label_seed: str,
    now: datetime | None = None,
) -> AttributionDecision:
    """Choose and update the thread for a new run under the index lock."""
    require_ulid(run_id, "run_id")
    repo_root = repo_root.resolve()
    explicit = getattr(request, "thread", None)
    timestamp = _format_time(now)
    stale_before = _coerce_time(now) - timedelta(days=OPEN_IDLE_DAYS)
    reopen_after = _coerce_time(now) - timedelta(hours=ARCHIVED_REOPEN_HOURS)
    lineage_thread_id = None if explicit else infer_lineage_thread_id(repo_root, request)
    store = ThreadIndexStore(repo_root)

    def mutate(index: dict[str, Any]) -> AttributionDecision:
        if not index:
            index.update(empty_threads_index())
        _apply_lazy_lifecycle(index, stale_before=stale_before, now=timestamp)
        requested = _explicit_thread_id(explicit)
        source = "explicit" if requested else ""
        thread_id = requested
        created = False
        reopened = False
        notice = None

        if thread_id is None and explicit == "@new":
            thread_id = generate_thread_id()
            source = "new"
        if thread_id is None and lineage_thread_id and lineage_thread_id in index["threads"]:
            thread_id = lineage_thread_id
            source = "lineage"
        if thread_id is None:
            active = index.get("active_thread_id")
            if isinstance(active, str) and active in index["threads"]:
                active_record = index["threads"][active]
                if active_record.get("status") == "open":
                    thread_id = active
                    source = "active"
                elif _is_recent_archived(active_record, reopen_after):
                    thread_id = active
                    source = "reopened_active"
                    reopened = True
                    notice = "Reopened the recently archived active thread."
        if thread_id is None:
            thread_id = generate_thread_id()
            source = "new"

        thread = index["threads"].get(thread_id)
        if thread is None:
            thread = make_thread_record(thread_id=thread_id, label=_thread_label(out_path, label_seed), created_at=timestamp, updated_at=timestamp)
            index["threads"][thread_id] = thread
            created = True
        elif thread.get("status") != "open":
            thread["status"] = "open"
            thread["archived_at"] = None
            reopened = True
            notice = notice or "Reopened the selected thread."

        thread.setdefault("run_ids", [])
        if run_id not in thread["run_ids"]:
            thread["run_ids"].append(run_id)
        thread["updated_at"] = timestamp
        index["active_thread_id"] = thread_id
        return AttributionDecision(
            thread_id=thread_id,
            source=source or "new",
            label=str(thread.get("label") or _thread_label(out_path, label_seed)),
            created=created,
            reopened=reopened,
            notice=notice,
            run_number=len(thread["run_ids"]),
        )

    return store.update(mutate)


def enforce_lifecycle(repo_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    timestamp = _format_time(now)
    stale_before = _coerce_time(now) - timedelta(days=OPEN_IDLE_DAYS)
    store = ThreadIndexStore(repo_root)

    def mutate(index: dict[str, Any]) -> dict[str, Any]:
        if not index:
            index.update(empty_threads_index())
        _apply_lazy_lifecycle(index, stale_before=stale_before, now=timestamp)
        return json.loads(json.dumps(index))

    return store.update(mutate)


def infer_lineage_thread_id(repo_root: Path, request: Any) -> str | None:
    for candidate in _path_candidates(request):
        resolved = _resolve_candidate(repo_root, candidate)
        if resolved is None:
            continue
        run_dir = _runs_ancestor(repo_root, resolved)
        if run_dir is None:
            continue
        run_json = run_dir / "run.json"
        if not run_json.is_file():
            continue
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        thread_id = data.get("thread_id")
        if isinstance(thread_id, str) and is_ulid(thread_id):
            return thread_id
    return None


def resolve_thread_ref(repo_root: Path, ref: str) -> str:
    index = enforce_lifecycle(repo_root)
    if ref == "@active":
        active = index.get("active_thread_id")
        if isinstance(active, str) and active in index.get("threads", {}):
            return active
        raise ValueError("no active thread")
    if not is_ulid(ref):
        raise ValueError("thread reference must be a 26-character Crockford ULID or @active")
    if ref not in index.get("threads", {}):
        raise ValueError(f"unknown thread: {ref}")
    return ref


def archive_thread(repo_root: Path, ref: str, *, now: datetime | None = None) -> dict[str, Any]:
    thread_id = resolve_thread_ref(repo_root, ref)
    timestamp = _format_time(now)
    store = ThreadIndexStore(repo_root)

    def mutate(index: dict[str, Any]) -> dict[str, Any]:
        thread = index["threads"][thread_id]
        thread["status"] = "archived"
        thread["archived_at"] = timestamp
        thread["updated_at"] = timestamp
        return dict(thread)

    return store.update(mutate)


def reopen_thread(repo_root: Path, ref: str, *, now: datetime | None = None) -> dict[str, Any]:
    thread_id = resolve_thread_ref(repo_root, ref)
    timestamp = _format_time(now)
    store = ThreadIndexStore(repo_root)

    def mutate(index: dict[str, Any]) -> dict[str, Any]:
        thread = index["threads"][thread_id]
        thread["status"] = "open"
        thread["archived_at"] = None
        thread["updated_at"] = timestamp
        index["active_thread_id"] = thread_id
        return dict(thread)

    return store.update(mutate)


def create_thread(repo_root: Path, label: str, *, now: datetime | None = None) -> dict[str, Any]:
    thread_id = generate_thread_id()
    timestamp = _format_time(now)
    store = ThreadIndexStore(repo_root)

    def mutate(index: dict[str, Any]) -> dict[str, Any]:
        if not index:
            index.update(empty_threads_index())
        thread = make_thread_record(thread_id=thread_id, label=label, created_at=timestamp, updated_at=timestamp)
        index["threads"][thread_id] = thread
        index["active_thread_id"] = thread_id
        return dict(thread)

    return store.update(mutate)


def backfill_runs(repo_root: Path) -> dict[str, int]:
    runs_root = repo_root / "runs"
    summary = {"run_records": 0, "threads_created": 0, "paths_recorded": 0}
    if not runs_root.is_dir():
        return summary
    store = ThreadIndexStore(repo_root)
    run_records = []
    path_only: list[Path] = []
    for child in sorted(runs_root.iterdir()):
        if not child.is_dir():
            continue
        run_json = child / "run.json"
        if run_json.is_file():
            try:
                run_records.append(json.loads(run_json.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        else:
            path_only.append(child)

    def mutate(index: dict[str, Any]) -> None:
        if not index:
            index.update(empty_threads_index())
        for record in run_records:
            thread_id = record.get("thread_id")
            run_id = record.get("run_id")
            if not (isinstance(thread_id, str) and is_ulid(thread_id) and isinstance(run_id, str) and is_ulid(run_id)):
                continue
            thread = index["threads"].get(thread_id)
            if thread is None:
                thread = make_thread_record(thread_id=thread_id, label=f"Backfill: {record.get('out_path') or run_id}")
                index["threads"][thread_id] = thread
                summary["threads_created"] += 1
            thread.setdefault("run_ids", [])
            if run_id not in thread["run_ids"]:
                thread["run_ids"].append(run_id)
            summary["run_records"] += 1
        for path in path_only:
            thread_id = generate_thread_id()
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            thread = make_thread_record(thread_id=thread_id, label=f"Backfill: {path.name}")
            thread["backfilled_paths"] = [rel]
            index["threads"][thread_id] = thread
            summary["threads_created"] += 1
            summary["paths_recorded"] += 1

    store.update(mutate)
    return summary


def reap_orphans_once(repo_root: Path) -> int:
    global _REAPER_RAN
    if _REAPER_RAN:
        return 0
    _REAPER_RAN = True
    return reap_orphans(repo_root)


def reap_orphans(repo_root: Path) -> int:
    count = 0
    runs_root = repo_root / "runs"
    if not runs_root.is_dir():
        return 0
    for run_json in sorted(runs_root.glob("*/run.json")):
        try:
            record = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("ended_at") is not None or record.get("status") != "running":
            continue
        pid = record.get("pid")
        if _pid_alive(pid):
            continue
        updated = dict(record)
        updated["ended_at"] = utc_now()
        updated["returncode"] = -1
        updated["status"] = "orphaned"
        updated["error"] = {"type": "orphaned", "message": "Run was marked orphaned after its owning process exited."}
        try:
            write_run_record(updated, run_json)
        except Exception:
            continue
        count += 1
    return count


def _reset_reaper_for_tests() -> None:
    global _REAPER_RAN
    _REAPER_RAN = False


def _explicit_thread_id(value: object) -> str | None:
    if value in (None, "", "@new", "@active", "@none"):
        return None
    if not isinstance(value, str) or not is_ulid(value):
        raise ValueError("--thread must be a 26-character Crockford ULID, @new, @active, or @none")
    return value


def _apply_lazy_lifecycle(index: dict[str, Any], *, stale_before: datetime, now: str) -> None:
    active = index.get("active_thread_id")
    for thread in index.get("threads", {}).values():
        if thread.get("status") != "open":
            continue
        updated = _parse_time(thread.get("updated_at")) or _parse_time(thread.get("created_at"))
        if updated is not None and updated < stale_before:
            thread["status"] = "archived"
            thread["archived_at"] = now
            if thread.get("thread_id") == active:
                index["active_thread_id"] = thread["thread_id"]


def _is_recent_archived(thread: Mapping[str, Any], reopen_after: datetime) -> bool:
    archived = _parse_time(thread.get("archived_at")) or _parse_time(thread.get("updated_at"))
    return archived is not None and archived >= reopen_after


def _path_candidates(request: Any) -> Iterable[str | Path]:
    for value in (getattr(request, "brief", None), getattr(request, "from_ref", None)):
        yield from _flatten_paths(value)
    for value in dict(getattr(request, "inputs", {}) or {}).values():
        yield from _flatten_paths(value)
    for value in getattr(request, "orchestrator_args", ()) or ():
        yield from _flatten_paths(value)


def _flatten_paths(value: Any) -> Iterable[str | Path]:
    if value in (None, ""):
        return
    if isinstance(value, (str, Path)):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten_paths(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten_paths(item)


def _resolve_candidate(repo_root: Path, value: str | Path) -> Path | None:
    text = str(value)
    if "://" in text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = repo_root / path
    try:
        return path.expanduser().resolve()
    except OSError:
        return None


def _runs_ancestor(repo_root: Path, path: Path) -> Path | None:
    runs_root = (repo_root / "runs").resolve()
    try:
        rel = path.resolve().relative_to(runs_root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    return runs_root / parts[0]


def _thread_label(out_path: Path, seed: str) -> str:
    return out_path.name or seed or "ArtAgents thread"


def _pid_alive(pid: Any) -> bool:
    try:
        numeric = int(pid)
    except (TypeError, ValueError):
        return False
    if numeric <= 0 or numeric == os.getpid():
        return True
    try:
        os.kill(numeric, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _format_time(value: datetime | None) -> str:
    return _coerce_time(value).isoformat().replace("+00:00", "Z")


def _coerce_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
