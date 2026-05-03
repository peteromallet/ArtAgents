"""Bridge audit ledger provenance into thread records and hype metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from artagents.audit.graph import build_graph, load_ledger

from .index import ThreadIndexStore
from .schema import SCHEMA_VERSION


def enrich_run_provenance(repo_root: Path, out_path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    provenance = build_provenance_block(repo_root, out_path, record)
    updated = dict(record)
    updated["provenance"] = provenance
    inject_hype_metadata(out_path, provenance)
    return updated


def build_provenance_block(repo_root: Path, out_path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    thread_id = str(record.get("thread_id") or "")
    run_id = str(record.get("run_id") or "")
    parent_run_ids = [dict(edge) for edge in record.get("parent_run_ids", []) or [] if isinstance(edge, Mapping)]
    audit_summary = _audit_summary(out_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "thread_id": thread_id,
        "thread_label": _thread_label(repo_root, thread_id),
        "run_id": run_id,
        "parent_run_ids": parent_run_ids,
        "contributing_runs": _contributing_runs(repo_root, record, parent_run_ids),
        "starred": bool(record.get("starred", False)),
        "agent_version": str(record.get("agent_version") or "unknown"),
        "audit": audit_summary,
    }


def inject_hype_metadata(out_path: Path, provenance: Mapping[str, Any]) -> None:
    for metadata_path in sorted(out_path.rglob("hype.metadata.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pipeline = dict(payload.get("pipeline") or {})
        pipeline["provenance"] = dict(provenance)
        payload["pipeline"] = pipeline
        metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _audit_summary(out_path: Path) -> dict[str, Any]:
    try:
        events = load_ledger(out_path)
    except FileNotFoundError:
        return {"ledger_present": False, "asset_ids": [], "parent_asset_ids": [], "node_ids": []}
    graph = build_graph(events)
    asset_ids = []
    parent_ids = set()
    nodes = []
    for node in graph["nodes"]:
        if node.get("node_type") == "asset":
            asset_ids.append(str(node.get("id")))
            for parent in node.get("parents") or []:
                parent_ids.add(str(parent))
        elif node.get("node_type") == "node":
            nodes.append(str(node.get("id")))
            for parent in node.get("parents") or []:
                parent_ids.add(str(parent))
            for output in node.get("outputs") or []:
                asset_ids.append(str(output))
    return {
        "ledger_present": True,
        "asset_ids": sorted(set(asset_ids)),
        "parent_asset_ids": sorted(parent_ids),
        "node_ids": sorted(set(nodes)),
    }


def _contributing_runs(repo_root: Path, record: Mapping[str, Any], parent_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in parent_edges:
        run_id = str(edge.get("run_id") or "")
        if not run_id:
            continue
        item = {"run_id": run_id, "kind": str(edge.get("kind") or "causal")}
        if edge.get("group"):
            item["group"] = str(edge["group"])
        _append_contribution(contributions, seen, item)

    output_by_sha = _output_sha_index(repo_root)
    current_run_id = str(record.get("run_id") or "")
    for artifact in record.get("input_artifacts", []) or []:
        if not isinstance(artifact, Mapping):
            continue
        sha = artifact.get("sha256")
        if not isinstance(sha, str):
            continue
        for run_id in output_by_sha.get(sha, []):
            if run_id == current_run_id:
                continue
            _append_contribution(contributions, seen, {"run_id": run_id, "kind": "artifact_hash", "sha256": sha})
    return contributions


def _output_sha_index(repo_root: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    runs_root = repo_root / "runs"
    if not runs_root.is_dir():
        return index
    for run_json in runs_root.glob("*/run.json"):
        try:
            record = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = record.get("run_id")
        if not isinstance(run_id, str):
            continue
        for artifact in record.get("output_artifacts", []) or []:
            if not isinstance(artifact, Mapping):
                continue
            sha = artifact.get("sha256")
            if isinstance(sha, str):
                index.setdefault(sha, []).append(run_id)
    return index


def _append_contribution(items: list[dict[str, Any]], seen: set[tuple[str, str]], item: dict[str, Any]) -> None:
    key = (str(item.get("run_id") or ""), str(item.get("kind") or ""))
    if key in seen or not key[0]:
        return
    seen.add(key)
    items.append(item)


def _thread_label(repo_root: Path, thread_id: str) -> str:
    try:
        index = ThreadIndexStore(repo_root).read()
    except Exception:
        return "Unknown thread"
    thread = index.get("threads", {}).get(thread_id)
    if isinstance(thread, Mapping) and thread.get("label"):
        return str(thread["label"])
    return "Unknown thread"
