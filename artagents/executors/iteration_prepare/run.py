#!/usr/bin/env python3
"""Prepare provenance, quality, summaries, and ordering for iteration videos."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from artagents._paths import REPO_ROOT
from artagents import modalities
from artagents.threads.ids import is_ulid
from artagents.threads.index import ThreadIndexStore
from artagents.threads.record import sha256_file
from artagents.threads.schema import SCHEMA_VERSION
from artagents.threads.variants import selection_history

DEFAULT_MAX_ITERATIONS = 200
DEFAULT_SUMMARIZER_MODEL_VERSION = "builtin.understand.v1"
DEFAULT_COST_PER_CALL = 0.009


@dataclass
class RunNode:
    run_id: str
    record: dict[str, Any]
    depth: int
    label: str
    parent_edges: list[dict[str, Any]] = field(default_factory=list)
    unresolved_parent_run_ids: list[str] = field(default_factory=list)
    selection_order: int = 999_999


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare iteration-video graph data for a target run.")
    parser.add_argument("--target-run-id", required=True, help="Target run id to prepare.")
    parser.add_argument("--out", required=True, help="Directory for iteration.prepare outputs.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(os.environ.get("ARTAGENTS_REPO_ROOT", REPO_ROOT))),
        help="Repository root. Defaults to ARTAGENTS_REPO_ROOT or the ArtAgents repo.",
    )
    parser.add_argument("--max-iterations", type=int, default=None, help="Maximum uncached summarize calls. Defaults to ARTAGENTS_ITERATION_MAX or 200.")
    parser.add_argument("--summarizer-model-version", default=DEFAULT_SUMMARIZER_MODEL_VERSION)
    parser.add_argument("--cost-per-call", type=float, default=DEFAULT_COST_PER_CALL)
    parser.add_argument("--summary-query", default="Summarize this ArtAgents run for an iteration video.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = prepare_iteration(
            repo_root=Path(args.repo_root),
            out_path=Path(args.out),
            target_run_id=args.target_run_id,
            max_iterations=args.max_iterations,
            summarizer_model_version=args.summarizer_model_version,
            cost_per_call=args.cost_per_call,
            summary_query=args.summary_query,
        )
    except PrepareError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"manifest": result["manifest_path"], "quality": result["quality_path"]}, sort_keys=True))
    return 0


class PrepareError(RuntimeError):
    pass


def prepare_iteration(
    *,
    repo_root: Path,
    out_path: Path,
    target_run_id: str,
    max_iterations: int | None = None,
    summarizer_model_version: str = DEFAULT_SUMMARIZER_MODEL_VERSION,
    cost_per_call: float = DEFAULT_COST_PER_CALL,
    summary_query: str = "Summarize this ArtAgents run for an iteration video.",
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    out_path = out_path.expanduser().resolve()
    if not is_ulid(target_run_id):
        raise PrepareError("target run id must be a 26-character Crockford ULID")
    max_iterations = _resolve_max_iterations(max_iterations)
    all_records = load_run_records(repo_root)
    if target_run_id not in all_records:
        raise PrepareError(f"unknown target run: {target_run_id}")

    nodes = collect_graph(repo_root, all_records, target_run_id)
    ordered_nodes = order_nodes(nodes)
    quality = compute_quality(ordered_nodes, target_run_id=target_run_id)
    summaries, cache_stats = summarize_nodes(
        repo_root=repo_root,
        nodes=ordered_nodes,
        max_iterations=max_iterations,
        summarizer_model_version=summarizer_model_version,
        summary_query=summary_query,
    )
    manifest = build_manifest(
        repo_root=repo_root,
        nodes=ordered_nodes,
        target_run_id=target_run_id,
        quality=quality,
        summaries=summaries,
        cache_stats=cache_stats,
        summarizer_model_version=summarizer_model_version,
        cost_per_call=cost_per_call,
    )
    out_path.mkdir(parents=True, exist_ok=True)
    quality_path = out_path / "iteration.quality.json"
    manifest_path = out_path / "iteration.manifest.json"
    _write_json(quality_path, quality)
    _write_json(manifest_path, manifest)
    return {"manifest": manifest, "quality": quality, "manifest_path": str(manifest_path), "quality_path": str(quality_path)}


def load_run_records(repo_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    runs_root = repo_root / "runs"
    if not runs_root.is_dir():
        return records
    for run_json in sorted(runs_root.glob("**/run.json")):
        try:
            record = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = record.get("run_id")
        if isinstance(run_id, str) and is_ulid(run_id):
            record["_run_json_path"] = _repo_rel(run_json, repo_root)
            records[run_id] = record
    return records


def collect_graph(repo_root: Path, all_records: Mapping[str, dict[str, Any]], target_run_id: str) -> list[RunNode]:
    target = all_records[target_run_id]
    thread_id = str(target.get("thread_id") or "")
    thread_run_ids = _thread_run_ids(repo_root, thread_id)
    output_by_sha = _output_sha_index(all_records)
    selection_orders = _selection_orders(repo_root, thread_id)
    nodes: dict[str, RunNode] = {}
    queue: list[tuple[str, int]] = [(target_run_id, 0)]

    while queue:
        run_id, depth = queue.pop(0)
        if run_id not in all_records:
            continue
        record = all_records[run_id]
        existing = nodes.get(run_id)
        if existing is not None and existing.depth >= depth:
            continue
        parent_edges, unresolved = _parent_edges_for_record(record, all_records, output_by_sha)
        label = "in_thread" if record.get("thread_id") == thread_id or run_id in thread_run_ids else "pulled_by_ancestry"
        nodes[run_id] = RunNode(
            run_id=run_id,
            record=record,
            depth=depth,
            label=label,
            parent_edges=parent_edges,
            unresolved_parent_run_ids=unresolved,
            selection_order=selection_orders.get(run_id, 999_999),
        )
        for edge in parent_edges:
            parent_id = edge.get("run_id")
            if isinstance(parent_id, str) and parent_id in all_records and parent_id != run_id:
                queue.append((parent_id, depth + 1))
    return list(nodes.values())


def order_nodes(nodes: list[RunNode]) -> list[RunNode]:
    return sorted(nodes, key=lambda node: (-node.depth, node.selection_order, node.run_id))


def compute_quality(nodes: list[RunNode], *, target_run_id: str) -> dict[str, Any]:
    total = len(nodes)
    if total == 0:
        raise PrepareError(f"no candidate runs found for {target_run_id}")
    valid_roots = [node.run_id for node in nodes if not node.record.get("input_artifacts")]
    runs_with_parents = [node.run_id for node in nodes if node.parent_edges]
    unresolved = [
        {
            "run_id": node.run_id,
            "missing_parent_run_ids": node.unresolved_parent_run_ids,
            "reason": "missing referenced producer",
        }
        for node in nodes
        if node.unresolved_parent_run_ids or (not node.parent_edges and node.run_id not in valid_roots)
    ]
    parent_capture_score = (len(set(runs_with_parents)) + len(set(valid_roots))) / total
    has_brief_sha = 1.0 if any(node.record.get("brief_content_sha256") for node in nodes) else 0.0
    has_resolved_input_artifact = 1.0 if all(_has_resolved_inputs(node) for node in nodes) else 0.0
    data_quality = round(0.5 * parent_capture_score + 0.3 * has_brief_sha + 0.2 * has_resolved_input_artifact, 6)
    missing_signals = []
    if has_brief_sha == 0.0:
        missing_signals.append("brief_content_sha256")
    if has_resolved_input_artifact == 0.0:
        missing_signals.append("resolved_input_artifact")
    if unresolved:
        missing_signals.append("producer_lineage")
    return {
        "schema_version": SCHEMA_VERSION,
        "target_run_id": target_run_id,
        "total_runs": total,
        "data_quality": data_quality,
        "parent_capture_score": round(parent_capture_score, 6),
        "has_brief_sha": has_brief_sha,
        "has_resolved_input_artifact": has_resolved_input_artifact,
        "valid_roots": sorted(valid_roots),
        "runs_with_parents": sorted(set(runs_with_parents)),
        "unresolved_producer_runs": unresolved,
        "missing_signals": missing_signals,
    }


def summarize_nodes(
    *,
    repo_root: Path,
    nodes: list[RunNode],
    max_iterations: int,
    summarizer_model_version: str,
    summary_query: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    cache_dir = repo_root / ".artagents" / "iteration_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    misses: list[RunNode] = []
    for node in nodes:
        cache_path = _cache_path(cache_dir, node.run_id, summarizer_model_version)
        cached = _read_json(cache_path)
        if cached is not None:
            summaries[node.run_id] = dict(cached)
        else:
            misses.append(node)
    if len(misses) > max_iterations:
        raise PrepareError(
            f"iteration.prepare needs {len(misses)} uncached summarize calls, above max_iterations={max_iterations}. "
            f"Raise the cap with --max-iterations or ARTAGENTS_ITERATION_MAX; default cap is {DEFAULT_MAX_ITERATIONS}."
        )
    generated = _summarize_misses(misses, summarizer_model_version=summarizer_model_version, summary_query=summary_query)
    for node, summary in generated.items():
        cache_path = _cache_path(cache_dir, node, summarizer_model_version)
        _write_json(cache_path, summary)
        summaries[node] = summary
    return summaries, {"hits": len(nodes) - len(misses), "misses": len(misses)}


def summarize_run_with_backoff(node: RunNode, *, summarizer_model_version: str, summary_query: str) -> dict[str, Any]:
    delay = 0.05
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            return call_builtin_understand(node, summarizer_model_version=summarizer_model_version, summary_query=summary_query)
        except Exception as exc:  # pragma: no cover - exercised by tests through monkeypatching
            last_error = exc
            time.sleep(delay)
            delay *= 2
    raise PrepareError(f"summary failed for {node.run_id}: {last_error}")


def call_builtin_understand(node: RunNode, *, summarizer_model_version: str, summary_query: str) -> dict[str, Any]:
    artifact = _primary_summarizable_artifact(node.record)
    if artifact is None:
        return _fallback_summary(node, summarizer_model_version, "no summarizable artifact")
    mode = _understand_mode(str(artifact.get("kind") or ""))
    if mode is None or not artifact.get("path"):
        return _fallback_summary(node, summarizer_model_version, "unsupported artifact kind")
    artifact_path = REPO_ROOT / str(artifact["path"])
    if not artifact_path.is_file():
        return _fallback_summary(node, summarizer_model_version, "artifact unavailable")
    flag = "--audio" if mode == "audio" else "--image"
    command = [
        sys.executable,
        "-m",
        "artagents.executors.understand.run",
        "--mode",
        mode,
        flag,
        str(artifact_path),
        "--query",
        summary_query,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise PrepareError((completed.stderr or completed.stdout or "builtin.understand failed").strip())
    text = (completed.stdout or "").strip()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": node.run_id,
        "summary": text,
        "summarizer_model_version": summarizer_model_version,
        "executor_id": "builtin.understand",
        "mode": mode,
    }


def build_manifest(
    *,
    repo_root: Path,
    nodes: list[RunNode],
    target_run_id: str,
    quality: Mapping[str, Any],
    summaries: Mapping[str, dict[str, Any]],
    cache_stats: Mapping[str, int],
    summarizer_model_version: str,
    cost_per_call: float,
) -> dict[str, Any]:
    renderer_candidates: dict[str, dict[str, Any]] = {}
    run_items = []
    for node in nodes:
        output_artifacts = [artifact for artifact in node.record.get("output_artifacts", []) or [] if isinstance(artifact, Mapping)]
        for artifact in output_artifacts:
            kind = str(artifact.get("kind") or "unknown")
            renderer_candidates.setdefault(kind, modalities.resolve_renderer_for_kind(kind))
        run_items.append(
            {
                "run_id": node.run_id,
                "thread_id": node.record.get("thread_id"),
                "label": node.label,
                "causal_depth": node.depth,
                "selection_order": node.selection_order,
                "parent_run_ids": node.parent_edges,
                "unresolved_parent_run_ids": node.unresolved_parent_run_ids,
                "out_path": node.record.get("out_path"),
                "executor_id": node.record.get("executor_id"),
                "orchestrator_id": node.record.get("orchestrator_id"),
                "output_artifacts": output_artifacts,
                "summary": summaries.get(node.run_id),
            }
        )
    uncached = int(cache_stats.get("misses", 0))
    return {
        "schema_version": SCHEMA_VERSION,
        "target_run_id": target_run_id,
        "thread_id": nodes[-1].record.get("thread_id") if nodes else None,
        "runs": run_items,
        "renderer_candidates": renderer_candidates,
        "quality": dict(quality),
        "summary_cache": {"hits": int(cache_stats.get("hits", 0)), "misses": uncached},
        "cost_estimate": {
            "summarize_calls": len(nodes),
            "uncached_summarize_calls": uncached,
            "summarizer_model_version": summarizer_model_version,
            "cost_per_call": cost_per_call,
            "estimated_cost": round(uncached * cost_per_call, 6),
        },
        "allocation_hints": {"ordered_by": ["causal_depth", "selection_event", "run_ulid"]},
    }


def _summarize_misses(
    misses: list[RunNode],
    *,
    summarizer_model_version: str,
    summary_query: str,
) -> dict[str, dict[str, Any]]:
    if not misses:
        return {}
    sequential = os.environ.get("ARTAGENTS_SUMMARIZE_SEQUENTIAL", "").strip().lower() in {"1", "true", "yes"}
    if sequential:
        return {
            node.run_id: summarize_run_with_backoff(
                node,
                summarizer_model_version=summarizer_model_version,
                summary_query=summary_query,
            )
            for node in misses
        }
    max_workers = int(os.environ.get("ARTAGENTS_SUMMARIZE_CONCURRENCY", "4"))
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_by_node = {
            pool.submit(
                summarize_run_with_backoff,
                node,
                summarizer_model_version=summarizer_model_version,
                summary_query=summary_query,
            ): node
            for node in misses
        }
        for future in concurrent.futures.as_completed(future_by_node):
            node = future_by_node[future]
            results[node.run_id] = future.result()
    return results


def _parent_edges_for_record(
    record: Mapping[str, Any],
    all_records: Mapping[str, dict[str, Any]],
    output_by_sha: Mapping[str, list[str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    run_id = str(record.get("run_id") or "")
    edges: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for raw in record.get("parent_run_ids", []) or []:
        _append_edge(edges, unresolved, raw, all_records)
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    for raw in provenance.get("contributing_runs", []) or []:
        _append_edge(edges, unresolved, raw, all_records)
    for artifact in record.get("input_artifacts", []) or []:
        if not isinstance(artifact, Mapping):
            continue
        sha = artifact.get("sha256")
        if not isinstance(sha, str):
            continue
        for parent_id in output_by_sha.get(sha, []):
            if parent_id != run_id:
                _append_edge(edges, unresolved, {"run_id": parent_id, "kind": "artifact_hash"}, all_records)
    return _dedupe_edges(edges), sorted(set(unresolved))


def _append_edge(
    edges: list[dict[str, Any]],
    unresolved: list[str],
    raw: object,
    all_records: Mapping[str, dict[str, Any]],
) -> None:
    if isinstance(raw, str):
        run_id = raw
        kind = "causal"
        group = None
    elif isinstance(raw, Mapping):
        run_id = raw.get("run_id")
        kind = raw.get("kind") or "causal"
        group = raw.get("group")
    else:
        return
    if not isinstance(run_id, str) or not is_ulid(run_id):
        return
    if run_id not in all_records:
        unresolved.append(run_id)
        return
    edge = {"run_id": run_id, "kind": str(kind)}
    if group:
        edge["group"] = str(group)
    edges.append(edge)


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (str(edge.get("run_id")), str(edge.get("kind")), str(edge.get("group") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def _thread_run_ids(repo_root: Path, thread_id: str) -> set[str]:
    try:
        index = ThreadIndexStore(repo_root).read()
    except Exception:
        return set()
    thread = index.get("threads", {}).get(thread_id, {})
    return {str(run_id) for run_id in thread.get("run_ids", []) or []}


def _selection_orders(repo_root: Path, thread_id: str) -> dict[str, int]:
    if not is_ulid(thread_id):
        return {}
    orders: dict[str, int] = {}
    try:
        history = selection_history(repo_root, thread_id)
    except Exception:
        return orders
    for order, record in enumerate(history):
        for selected in record.get("selected", []) or []:
            if isinstance(selected, Mapping) and isinstance(selected.get("run_id"), str):
                orders.setdefault(str(selected["run_id"]), order)
    return orders


def _output_sha_index(records: Mapping[str, dict[str, Any]]) -> dict[str, list[str]]:
    by_sha: dict[str, list[str]] = {}
    for run_id, record in records.items():
        for artifact in record.get("output_artifacts", []) or []:
            if isinstance(artifact, Mapping) and isinstance(artifact.get("sha256"), str):
                by_sha.setdefault(str(artifact["sha256"]), []).append(run_id)
    return by_sha


def _has_resolved_inputs(node: RunNode) -> bool:
    artifacts = [artifact for artifact in node.record.get("input_artifacts", []) or [] if isinstance(artifact, Mapping)]
    if not artifacts:
        return True
    return any(isinstance(artifact.get("sha256"), str) for artifact in artifacts)


def _primary_summarizable_artifact(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for artifact in record.get("output_artifacts", []) or []:
        if isinstance(artifact, Mapping) and artifact.get("kind") in {"image", "audio"} and artifact.get("path"):
            return artifact
    return None


def _understand_mode(kind: str) -> str | None:
    if kind == "image":
        return "image"
    if kind == "audio":
        return "audio"
    return None


def _fallback_summary(node: RunNode, model_version: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": node.run_id,
        "summary": f"{node.record.get('executor_id') or node.record.get('orchestrator_id') or 'run'}: {reason}",
        "summarizer_model_version": model_version,
        "executor_id": "builtin.understand",
        "fallback": True,
        "reason": reason,
    }


def _cache_path(cache_dir: Path, run_id: str, model_version: str) -> Path:
    safe_version = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in model_version)
    return cache_dir / f"{run_id}__{safe_version}.json"


def _resolve_max_iterations(raw: int | None) -> int:
    if raw is not None:
        return int(raw)
    env_value = os.environ.get("ARTAGENTS_ITERATION_MAX", "").strip()
    return int(env_value) if env_value else DEFAULT_MAX_ITERATIONS


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(repo_root.expanduser().resolve()).as_posix()
    except ValueError:
        return f"sha256:{sha256_file(path)}"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
