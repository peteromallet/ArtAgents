from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .util import MAX_TEXT_PREVIEW, file_metadata, redact, stable_id, text_preview, utc_now

PARENT_IDS_ENV = "ASTRID_AUDIT_PARENT_IDS"


def _env_parent_ids() -> list[str]:
    raw = os.environ.get(PARENT_IDS_ENV, "").strip()
    if not raw:
        return []
    return [item for item in raw.split(",") if item]


@dataclass
class AuditContext:
    run_dir: Path
    enabled: bool = True

    def __post_init__(self) -> None:
        self.run_dir = self.run_dir.resolve()
        self.audit_dir = self.run_dir / "audit"
        self.ledger_path = self.audit_dir / "ledger.jsonl"
        if self.enabled:
            self.audit_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_dir: Path | str, *, enabled: bool = True) -> "AuditContext":
        return cls(Path(run_dir), enabled=enabled)

    @classmethod
    def from_env(cls) -> "AuditContext | None":
        if os.environ.get("ASTRID_AUDIT_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
            return None
        run_dir = os.environ.get("ASTRID_AUDIT_RUN_DIR", "").strip()
        if not run_dir:
            return None
        return cls.for_run(run_dir)

    def _relative(self, path: Path | str | None) -> str | None:
        if path is None:
            return None
        path_obj = Path(path)
        try:
            resolved = path_obj.resolve()
        except OSError:
            resolved = path_obj
        try:
            return str(resolved.relative_to(self.run_dir))
        except ValueError:
            return str(path)

    def append(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        payload = {"schema_version": 1, "created_at": utc_now(), **redact(event)}
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def register_asset(
        self,
        *,
        kind: str,
        path: Path | str | None = None,
        label: str | None = None,
        asset_id: str | None = None,
        parents: Iterable[str] = (),
        stage: str | None = None,
        metadata: dict[str, Any] | None = None,
        preview: dict[str, Any] | None = None,
        registration_source: str = "creation",
    ) -> str:
        parent_ids = list(parents)
        rel_path = self._relative(path)
        produced_id = asset_id or stable_id(kind, rel_path, label, sorted(parent_ids), stage)
        path_obj = Path(path) if path is not None else None
        merged_metadata = dict(metadata or {})
        if path_obj is not None:
            merged_metadata.update(file_metadata(path_obj))
        merged_preview = dict(preview or {})
        if path_obj is not None and "text" not in merged_preview:
            text = text_preview(path_obj)
            if text:
                merged_preview["text"] = text
        self.append(
            {
                "event": "asset.created",
                "asset_id": produced_id,
                "kind": kind,
                "label": label or rel_path or kind,
                "path": rel_path,
                "parents": parent_ids,
                "stage": stage,
                "metadata": merged_metadata,
                "preview": merged_preview,
                "registration_source": registration_source,
            }
        )
        return produced_id

    def register_node(
        self,
        *,
        stage: str,
        kind: str = "step",
        label: str | None = None,
        node_id: str | None = None,
        parents: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
        outputs: Iterable[str] = (),
        registration_source: str = "creation",
    ) -> str:
        parent_ids = list(parents)
        output_ids = list(outputs)
        produced_id = node_id or stable_id(stage, kind, label, sorted(parent_ids), sorted(output_ids))
        self.append(
            {
                "event": "node.created",
                "node_id": produced_id,
                "kind": kind,
                "label": label or stage,
                "stage": stage,
                "parents": parent_ids,
                "outputs": output_ids,
                "metadata": metadata or {},
                "registration_source": registration_source,
            }
        )
        return produced_id

    def register_decision(
        self,
        *,
        stage: str,
        label: str,
        selected: Iterable[str] = (),
        rejected: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> str:
        selected_ids = list(selected)
        rejected_ids = list(rejected)
        decision_id = stable_id("decision", stage, label, sorted(selected_ids), sorted(rejected_ids))
        self.append(
            {
                "event": "decision.created",
                "decision_id": decision_id,
                "stage": stage,
                "label": label,
                "selected": selected_ids,
                "rejected": rejected_ids,
                "metadata": metadata or {},
            }
        )
        return decision_id

    def register_prompt_ref(
        self,
        *,
        prompt: str | None = None,
        path: Path | str | None = None,
        label: str = "Prompt",
        parents: Iterable[str] = (),
        stage: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        preview: dict[str, Any] = {}
        if prompt:
            preview["text"] = prompt[:MAX_TEXT_PREVIEW]
        return self.register_asset(
            kind="prompt",
            path=path,
            label=label,
            parents=parents,
            stage=stage,
            metadata=metadata,
            preview=preview,
        )


def register_output(
    *,
    kind: str,
    path: Path | str,
    label: str | None = None,
    stage: str | None = None,
    parents: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> str | None:
    context = AuditContext.from_env()
    if context is None:
        return None
    parent_ids = list(parents) or _env_parent_ids()
    return context.register_asset(kind=kind, path=path, label=label, stage=stage, parents=parent_ids, metadata=metadata)


def register_outputs(
    *,
    stage: str,
    outputs: Iterable[tuple[str, Path | str, str]],
    parents: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    context = AuditContext.from_env()
    if context is None:
        return []
    parent_ids = list(parents) or _env_parent_ids()
    output_ids = [
        context.register_asset(kind=kind, path=path, label=label, parents=parent_ids, stage=stage, metadata=metadata)
        for kind, path, label in outputs
        if Path(path).exists()
    ]
    context.register_node(stage=stage, label=stage, parents=parent_ids, outputs=output_ids, metadata=metadata or {})
    return output_ids
