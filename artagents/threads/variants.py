"""Variant groups and append-only selections for thread runs."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ids import is_ulid, require_ulid
from .schema import SCHEMA_VERSION, utc_now

VARIANT_SIDECAR_NAME = ".artagents.variants.json"
SELECTION_SENTENCE = (
    "selections are append-only; the most recent write is authoritative on read; "
    "prior selections are preserved as history but do not affect current keepers."
)


class VariantStateError(ValueError):
    """Raised when a variant group or selection is invalid."""


def annotate_output_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    out_path: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    sidecar = out_path / VARIANT_SIDECAR_NAME
    if not sidecar.is_file():
        return artifacts
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return artifacts
    by_path: dict[str, dict[str, Any]] = {}
    for item in payload.get("artifacts", []):
        if not isinstance(item, Mapping):
            continue
        raw_path = item.get("path")
        if not raw_path:
            continue
        try:
            rel = _repo_relative(Path(str(raw_path)), repo_root)
        except ValueError:
            rel = str(raw_path)
        by_path[rel] = _variant_annotation(item)
    annotated = []
    for artifact in artifacts:
        updated = dict(artifact)
        if updated.get("path") in by_path:
            updated.update(by_path[updated["path"]])
        annotated.append(updated)
    return annotated


def update_groups_for_run(repo_root: Path, record: Mapping[str, Any]) -> dict[str, Any] | None:
    thread_id = str(record.get("thread_id") or "")
    run_id = str(record.get("run_id") or "")
    if not (is_ulid(thread_id) and is_ulid(run_id)):
        return None
    variant_artifacts = [
        (index, artifact)
        for index, artifact in enumerate(record.get("output_artifacts", []) or [])
        if isinstance(artifact, Mapping) and artifact.get("role", "other") == "variant"
    ]
    if not variant_artifacts:
        return None
    state = VariantState(repo_root, thread_id)

    def mutate(groups: dict[str, Any]) -> dict[str, Any]:
        for artifact_index, artifact in variant_artifacts:
            group_id = _require_group(artifact.get("group"))
            group = groups["groups"].setdefault(
                group_id,
                {
                    "schema_version": SCHEMA_VERSION,
                    "thread_id": thread_id,
                    "group": group_id,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                    "artifacts": [],
                    "resolved": False,
                    "selection": None,
                },
            )
            ref = _artifact_ref(run_id, artifact_index, artifact)
            existing_keys = {(item.get("run_id"), item.get("artifact_index")) for item in group.get("artifacts", [])}
            if (run_id, artifact_index) not in existing_keys:
                group.setdefault("artifacts", []).append(ref)
            group["updated_at"] = utc_now()
        _apply_latest_selections(groups, state.read_selection_history_unlocked())
        return groups

    return state.update_groups(mutate)


def unresolved_variant_count(repo_root: Path, thread_id: str) -> int:
    if not is_ulid(thread_id):
        return 0
    groups = VariantState(repo_root, thread_id).read_groups()
    return sum(1 for group in groups.get("groups", {}).values() if group.get("artifacts") and not group.get("resolved"))


def variant_prefix_message(repo_root: Path, thread_id: str) -> str | None:
    count = unresolved_variant_count(repo_root, thread_id)
    if count <= 0:
        return None
    plural = "group" if count == 1 else "groups"
    return f"{count} unresolved variant {plural}; run `python3 -m artagents thread keep <run-id>:<n>[,<n>]` or `<run-id>:none`."


def keep_selection(repo_root: Path, thread_id: str, selector: str, *, action: str = "keep") -> dict[str, Any]:
    require_ulid(thread_id, "thread_id")
    run_id, indices, none_selected = parse_selector(selector)
    state = VariantState(repo_root, thread_id)

    def mutate(groups: dict[str, Any]) -> dict[str, Any]:
        targets = _groups_for_selector(groups, run_id=run_id, indices=indices, none_selected=none_selected)
        if not targets:
            raise VariantStateError(f"no variant group matched {selector!r}")
        records = []
        for group_id, refs in targets.items():
            selected = [] if none_selected or action == "dismiss" else refs
            record = {
                "schema_version": SCHEMA_VERSION,
                "thread_id": thread_id,
                "group": group_id,
                "run_id": run_id,
                "action": action,
                "selected": selected,
                "created_at": utc_now(),
            }
            state.append_selection_unlocked(record)
            records.append(record)
        _apply_latest_selections(groups, state.read_selection_history_unlocked())
        return {"records": records, "groups": groups}

    return state.update_groups(mutate)


def read_current_keepers(repo_root: Path, thread_id: str) -> dict[str, list[dict[str, Any]]]:
    groups = VariantState(repo_root, thread_id).read_groups()
    keepers: dict[str, list[dict[str, Any]]] = {}
    for group_id, group in groups.get("groups", {}).items():
        selected = ((group.get("selection") or {}).get("selected") or []) if isinstance(group, Mapping) else []
        keepers[group_id] = list(selected)
    return keepers


def selection_history(repo_root: Path, thread_id: str) -> list[dict[str, Any]]:
    return VariantState(repo_root, thread_id).read_selection_history()


def resolve_group_for_selection(repo_root: Path, run_id: str, index: int) -> str | None:
    threads_root = repo_root / ".artagents" / "threads"
    if not threads_root.is_dir():
        return None
    for groups_json in threads_root.glob("*/groups.json"):
        try:
            groups = json.loads(groups_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for group_id, group in groups.get("groups", {}).items():
            for artifact in group.get("artifacts", []):
                if artifact.get("run_id") == run_id and int(artifact.get("group_index", -1)) == index:
                    return str(group_id)
    return None


def write_sidecar(out_path: Path, artifacts: Iterable[Mapping[str, Any]]) -> None:
    items = [_jsonable(dict(item)) for item in artifacts]
    if not items:
        return
    payload = {"schema_version": SCHEMA_VERSION, "artifacts": items}
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / VARIANT_SIDECAR_NAME).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_selector(selector: str) -> tuple[str, list[int], bool]:
    if ":" not in selector:
        raise VariantStateError("selection must look like <run-id>:<n>[,<n>] or <run-id>:none")
    run_id, raw_indices = selector.split(":", 1)
    require_ulid(run_id, "selection run_id")
    if raw_indices == "none":
        return run_id, [], True
    indices = []
    for raw in raw_indices.split(","):
        try:
            value = int(raw)
        except ValueError as exc:
            raise VariantStateError("selection indices must be positive integers or none") from exc
        if value < 1:
            raise VariantStateError("selection indices must be positive integers")
        indices.append(value)
    return run_id, indices, False


class VariantState:
    def __init__(self, repo_root: Path | str, thread_id: str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.thread_id = require_ulid(thread_id, "thread_id")
        self.state_dir = self.repo_root / ".artagents" / "threads" / self.thread_id
        self.groups_path = self.state_dir / "groups.json"
        self.selections_path = self.state_dir / "selections.jsonl"
        self.lock_path = self.state_dir / "groups.json.lock"

    def read_groups(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            groups = self._read_groups_unlocked()
            _apply_latest_selections(groups, self.read_selection_history_unlocked())
            return groups

    def update_groups(self, mutator):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            groups = self._read_groups_unlocked()
            result = mutator(groups)
            self._write_groups_unlocked(groups)
            return result

    def read_selection_history(self) -> list[dict[str, Any]]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            return self.read_selection_history_unlocked()

    def read_selection_history_unlocked(self) -> list[dict[str, Any]]:
        if not self.selections_path.is_file():
            return []
        records = []
        for line in self.selections_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("schema_version") == SCHEMA_VERSION:
                records.append(record)
        return records

    def append_selection_unlocked(self, record: Mapping[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.selections_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @contextlib.contextmanager
    def locked(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_groups_unlocked(self) -> dict[str, Any]:
        if not self.groups_path.is_file():
            return {"schema_version": SCHEMA_VERSION, "thread_id": self.thread_id, "groups": {}}
        try:
            groups = json.loads(self.groups_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": SCHEMA_VERSION, "thread_id": self.thread_id, "groups": {}}
        if groups.get("schema_version") != SCHEMA_VERSION or groups.get("thread_id") != self.thread_id:
            return {"schema_version": SCHEMA_VERSION, "thread_id": self.thread_id, "groups": {}}
        groups.setdefault("groups", {})
        return groups

    def _write_groups_unlocked(self, groups: Mapping[str, Any]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix="groups.", suffix=".tmp", dir=self.state_dir)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(dict(groups), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.groups_path)
            _fsync_dir(self.state_dir)
        finally:
            tmp_path.unlink(missing_ok=True)


def _variant_annotation(item: Mapping[str, Any]) -> dict[str, Any]:
    role = item.get("role", "other")
    if role not in {"variant", "other"}:
        raise VariantStateError("variant sidecar role must be variant or other")
    annotation = {"role": role}
    for key in ("group", "group_index", "duration", "variant_meta"):
        if key in item and item[key] is not None:
            annotation[key] = item[key]
    return annotation


def _require_group(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VariantStateError("variant artifact must include a group")
    return value


def _artifact_ref(run_id: str, artifact_index: int, artifact: Mapping[str, Any]) -> dict[str, Any]:
    ref = {
        "run_id": run_id,
        "artifact_index": artifact_index,
        "group_index": int(artifact.get("group_index") or artifact_index + 1),
        "kind": str(artifact.get("kind") or "artifact"),
    }
    for key in ("path", "sha256", "label", "variant_meta"):
        if key in artifact:
            ref[key] = artifact[key]
    return ref


def _groups_for_selector(
    groups: Mapping[str, Any],
    *,
    run_id: str,
    indices: list[int],
    none_selected: bool,
) -> dict[str, list[dict[str, Any]]]:
    targets: dict[str, list[dict[str, Any]]] = {}
    for group_id, group in groups.get("groups", {}).items():
        matches = []
        for artifact in group.get("artifacts", []):
            if artifact.get("run_id") != run_id:
                continue
            if none_selected or int(artifact.get("group_index", -1)) in indices:
                matches.append(dict(artifact))
        if matches or (none_selected and any(item.get("run_id") == run_id for item in group.get("artifacts", []))):
            targets[str(group_id)] = matches
    return targets


def _apply_latest_selections(groups: dict[str, Any], history: list[dict[str, Any]]) -> None:
    latest = {}
    for record in history:
        group_id = record.get("group")
        if isinstance(group_id, str):
            latest[group_id] = record
    for group_id, group in groups.get("groups", {}).items():
        selection = latest.get(group_id)
        if selection is None:
            group.setdefault("resolved", False)
            group.setdefault("selection", None)
        else:
            group["selection"] = selection
            group["resolved"] = True
            group["updated_at"] = selection.get("created_at") or utc_now()


def _fsync_dir(path: Path) -> None:
    fd = None
    try:
        fd = os.open(path, getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd is not None:
            os.close(fd)


def _repo_relative(path: Path, repo_root: Path) -> str:
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"path must be under repository root: {resolved}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value
