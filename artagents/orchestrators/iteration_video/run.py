#!/usr/bin/env python3
"""Orchestrate prepare, assemble, render, and finalization for iteration videos."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from artagents._paths import REPO_ROOT
from artagents import modalities
from artagents.executors.iteration_assemble import run as assemble
from artagents.executors.iteration_prepare import run as prepare
from artagents.executors.render import run as render_executor
from artagents.threads.ids import is_ulid
from artagents.threads.index import ThreadIndexStore
from artagents.threads.schema import SCHEMA_VERSION
from artagents.threads.variants import write_sidecar

OUTPUT_FILES = (
    ("iteration.mp4", "video"),
    ("iteration.timeline.json", "metadata"),
    ("iteration.manifest.json", "metadata"),
    ("iteration.report.html", "text"),
    ("iteration.quality.json", "metadata"),
)


class IterationVideoError(RuntimeError):
    pass


def run_orchestrator(request: Any, orchestrator: Any) -> dict[str, Any]:
    repo_root = Path(request.inputs.get("repo_root") or REPO_ROOT).expanduser().resolve()
    out_path = Path(request.out).expanduser().resolve()
    args = _parse_passthrough(tuple(getattr(request, "orchestrator_args", ()) or ()))
    thread_ref = str(request.inputs.get("thread") or getattr(request, "thread", None) or args.thread or "@active")
    target_run_id = request.inputs.get("target_run_id") or args.target_run_id
    if request.dry_run:
        return _dry_run_result(orchestrator.id, out_path=out_path)

    try:
        result = run_iteration_video(
            repo_root=repo_root,
            out_path=out_path,
            thread_ref=thread_ref,
            target_run_id=str(target_run_id) if target_run_id else None,
            max_iterations=args.max_iterations,
            renderers=args.renderers,
            clip_mode=args.clip_mode,
            direction=args.direction,
            mode=args.mode,
            audio_bed=args.audio_bed,
            force=args.force,
            no_content=args.no_content,
        )
    except (IterationVideoError, prepare.PrepareError, assemble.AssembleError, OSError, RuntimeError) as exc:
        return {
            "orchestrator_id": orchestrator.id,
            "kind": orchestrator.kind,
            "runtime_kind": "python",
            "returncode": 2,
            "errors": [str(exc)],
        }
    return {
        "orchestrator_id": orchestrator.id,
        "kind": orchestrator.kind,
        "runtime_kind": "python",
        "returncode": 0,
        "outputs": result["outputs"],
        "planned_commands": result["planned_commands"],
    }


def run_iteration_video(
    *,
    repo_root: Path,
    out_path: Path,
    thread_ref: str,
    target_run_id: str | None = None,
    max_iterations: int | None = None,
    renderers: str | None = None,
    clip_mode: str | None = None,
    direction: str | None = None,
    mode: str = "chaptered",
    audio_bed: str = "auto",
    force: bool = False,
    no_content: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    out_path = out_path.expanduser().resolve()
    target = resolve_target_run_id(repo_root, thread_ref=thread_ref, target_run_id=target_run_id)
    prepare_dir = out_path.parent / f".{out_path.name}.prepare"
    prepare_result = prepare.prepare_iteration(
        repo_root=repo_root,
        out_path=prepare_dir,
        target_run_id=target["target_run_id"],
        max_iterations=max_iterations,
    )
    assemble_result = assemble.assemble_iteration(
        prepare_dir=prepare_dir,
        out_path=out_path,
        repo_root=repo_root,
        force=force,
        direction=direction,
        mode=mode,
        audio_bed=audio_bed,
    )
    _record_requested_flags(
        out_path / "iteration.manifest.json",
        renderers=renderers,
        clip_mode=clip_mode,
        no_content=no_content,
    )
    hype_mp4 = run_builtin_render(out_path)
    iteration_mp4 = out_path / "iteration.mp4"
    if hype_mp4.resolve() != iteration_mp4.resolve():
        shutil.move(str(hype_mp4), str(iteration_mp4))
    write_iteration_group_sidecar(
        out_path=out_path,
        thread_id=target["thread_id"],
        target_run_id=target["target_run_id"],
    )
    return {
        "thread_id": target["thread_id"],
        "target_run_id": target["target_run_id"],
        "prepare": prepare_result,
        "assemble": assemble_result,
        "outputs": {name: str(out_path / name) for name, _kind in OUTPUT_FILES},
        "planned_commands": (
            ("iteration.prepare", target["target_run_id"]),
            ("iteration.assemble", str(prepare_dir), str(out_path)),
            ("builtin.render", str(out_path / "hype.timeline.json"), str(out_path / "hype.assets.json")),
            ("finalize", str(iteration_mp4)),
        ),
    }


def run_builtin_render(brief_out: Path) -> Path:
    return render_executor.render(
        brief_out / "hype.timeline.json",
        brief_out / "hype.assets.json",
        brief_out / "hype.mp4",
    )


def inspect_iteration_thread(
    *,
    repo_root: Path,
    thread_ref: str,
    target_run_id: str | None = None,
    summarizer_model_version: str = prepare.DEFAULT_SUMMARIZER_MODEL_VERSION,
    cost_per_call: float = prepare.DEFAULT_COST_PER_CALL,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    target = resolve_target_run_id(repo_root, thread_ref=thread_ref, target_run_id=target_run_id)
    all_records = prepare.load_run_records(repo_root)
    if target["target_run_id"] not in all_records:
        raise IterationVideoError(f"unknown target run: {target['target_run_id']}")
    nodes = prepare.order_nodes(prepare.collect_graph(repo_root, all_records, target["target_run_id"]))
    quality = prepare.compute_quality(nodes, target_run_id=target["target_run_id"])
    renderers = renderer_decisions(nodes)
    cache_stats = inspect_cache(repo_root, nodes, summarizer_model_version=summarizer_model_version)
    uncached = cache_stats["misses"]
    return {
        "schema_version": SCHEMA_VERSION,
        "thread_id": target["thread_id"],
        "thread_label": target["thread_label"],
        "target_run_id": target["target_run_id"],
        "run_count": len(nodes),
        "detected_modalities": sorted({item["kind"] for item in renderers if item.get("kind")}),
        "chosen_renderers": renderers,
        "quality": quality,
        "summary_cache": cache_stats,
        "cost_estimate": {
            "uncached_summarize_calls": uncached,
            "cost_per_call": cost_per_call,
            "estimated_cost": round(uncached * cost_per_call, 6),
            "summarizer_model_version": summarizer_model_version,
        },
    }


def format_inspection(report: Mapping[str, Any], *, no_content: bool = False) -> str:
    cost = report["cost_estimate"]
    lines = [
        f"thread: {report['thread_id']} ({report.get('thread_label') or 'unlabeled'})",
        f"target_run_id: {report['target_run_id']}",
        f"runs: {report['run_count']}",
        f"data_quality: {report['quality']['data_quality']}",
        f"modalities: {', '.join(report['detected_modalities']) or 'none'}",
        f"summary_cache: {report['summary_cache']['hits']} hit(s), {report['summary_cache']['misses']} miss(es)",
        f"Estimated cost: ~${cost['estimated_cost']:.3f} ({cost['uncached_summarize_calls']} call(s) x ${cost['cost_per_call']:.3f})",
        "renderers:",
    ]
    for item in report["chosen_renderers"]:
        suffix = " fallback" if item.get("fallback") else ""
        lines.append(f"  - {item.get('kind') or 'unknown'} -> {item['renderer']}{suffix}")
    if no_content:
        lines.append("content: suppressed")
    return "\n".join(lines) + "\n"


def resolve_target_run_id(repo_root: Path, *, thread_ref: str, target_run_id: str | None = None) -> dict[str, str]:
    index = ThreadIndexStore(repo_root).read()
    thread_id = index.get("active_thread_id") if thread_ref in {"", "@active", None} else thread_ref
    if not isinstance(thread_id, str) or not is_ulid(thread_id):
        raise IterationVideoError("thread must be a thread id or @active")
    thread = index.get("threads", {}).get(thread_id)
    if not isinstance(thread, Mapping):
        raise IterationVideoError(f"unknown thread: {thread_id}")
    if target_run_id is not None:
        if not is_ulid(target_run_id):
            raise IterationVideoError("target run id must be a 26-character Crockford ULID")
        return {"thread_id": thread_id, "thread_label": str(thread.get("label") or ""), "target_run_id": target_run_id}
    all_records = prepare.load_run_records(repo_root)
    for run_id in reversed(thread.get("run_ids", []) or []):
        if isinstance(run_id, str) and run_id in all_records:
            return {"thread_id": thread_id, "thread_label": str(thread.get("label") or ""), "target_run_id": run_id}
    raise IterationVideoError(f"thread has no recorded runs: {thread_id}")


def renderer_decisions(nodes: list[prepare.RunNode]) -> list[dict[str, Any]]:
    decisions = []
    for node in nodes:
        for artifact in node.record.get("output_artifacts", []) or []:
            if not isinstance(artifact, Mapping):
                continue
            kind = str(artifact.get("kind") or "unknown")
            resolution = modalities.resolve_renderer_for_kind(kind)
            decisions.append(
                {
                    "run_id": node.run_id,
                    "kind": kind,
                    "renderer": resolution["renderer"],
                    "fallback": bool(resolution.get("fallback")),
                }
            )
    return decisions


def inspect_cache(repo_root: Path, nodes: list[prepare.RunNode], *, summarizer_model_version: str) -> dict[str, int]:
    cache_dir = repo_root / ".artagents" / "iteration_cache"
    hits = 0
    misses = 0
    safe_version = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in summarizer_model_version)
    for node in nodes:
        if (cache_dir / f"{node.run_id}__{safe_version}.json").is_file():
            hits += 1
        else:
            misses += 1
    return {"hits": hits, "misses": misses}


def write_iteration_group_sidecar(*, out_path: Path, thread_id: str, target_run_id: str) -> None:
    manifest = _read_json(out_path / "iteration.manifest.json")
    assembly = manifest.get("assembly") if isinstance(manifest.get("assembly"), Mapping) else {}
    group = f"iteration-video:{target_run_id}"
    fallback_diagnostics = list(assembly.get("fallback_diagnostics", []) or []) if isinstance(assembly, Mapping) else []
    artifacts = []
    for index, (filename, kind) in enumerate(OUTPUT_FILES, start=1):
        artifacts.append(
            {
                "path": str(out_path / filename),
                "kind": kind,
                "role": "variant",
                "group": group,
                "group_index": index,
                "label": filename,
                "variant" + "_meta": {
                    "schema_version": SCHEMA_VERSION,
                    "thread_id": thread_id,
                    "target_run_id": target_run_id,
                    "fallback_diagnostics": fallback_diagnostics,
                    "ancestry": {"target_run_id": target_run_id},
                },
            }
        )
    write_sidecar(out_path, artifacts)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if raw and raw[0] == "inspect":
        parser = _inspect_parser()
        args = parser.parse_args(raw[1:])
        try:
            report = inspect_iteration_thread(
                repo_root=Path(args.repo_root),
                thread_ref=args.thread,
                target_run_id=args.target_run_id,
                cost_per_call=args.cost_per_call,
            )
        except IterationVideoError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_inspection(report, no_content=args.no_content), end="")
        return 0
    parser = _run_parser()
    args = parser.parse_args(raw)
    try:
        result = run_iteration_video(
            repo_root=Path(args.repo_root),
            out_path=Path(args.out),
            thread_ref=args.thread,
            target_run_id=args.target_run_id,
            max_iterations=args.max_iterations,
            renderers=args.renderers,
            clip_mode=args.clip_mode,
            direction=args.direction,
            mode=args.mode,
            audio_bed=args.audio_bed,
            force=args.force,
            no_content=args.no_content,
        )
    except (IterationVideoError, prepare.PrepareError, assemble.AssembleError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result["outputs"], indent=2, sort_keys=True))
    return 0


def _parse_passthrough(argv: tuple[str, ...]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--thread", default=None)
    parser.add_argument("--target-run-id", default=None)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--renderers", default=None)
    parser.add_argument("--clip-mode", default=None)
    parser.add_argument("--direction", default=None)
    parser.add_argument("--mode", default="chaptered")
    parser.add_argument("--audio-bed", default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-content", action="store_true")
    return parser.parse_args(list(argv))


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an iteration video from a thread.")
    parser.add_argument("--thread", default="@active", help="Thread id or @active.")
    parser.add_argument("--target-run-id", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--renderers", default=None)
    parser.add_argument("--clip-mode", default=None)
    parser.add_argument("--direction", default=None)
    parser.add_argument("--mode", default="chaptered")
    parser.add_argument("--audio-bed", default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-content", action="store_true")
    return parser


def _inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect an iteration video plan without render or summarize.")
    parser.add_argument("thread", help="Thread id or @active.")
    parser.add_argument("--target-run-id", default=None)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--cost-per-call", type=float, default=prepare.DEFAULT_COST_PER_CALL)
    parser.add_argument("--no-content", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _dry_run_result(orchestrator_id: str, *, out_path: Path) -> dict[str, Any]:
    return {
        "orchestrator_id": orchestrator_id,
        "runtime_kind": "python",
        "returncode": None,
        "dry_run": True,
        "planned_commands": (
            ("iteration.prepare", str(out_path / "_prepare")),
            ("iteration.assemble", str(out_path)),
            ("builtin.render", str(out_path / "hype.timeline.json"), str(out_path / "hype.assets.json")),
            ("finalize", str(out_path / "iteration.mp4")),
        ),
    }


def _record_requested_flags(manifest_path: Path, *, renderers: str | None, clip_mode: str | None, no_content: bool) -> None:
    manifest = _read_json(manifest_path)
    manifest["iteration_video"] = {
        "schema_version": SCHEMA_VERSION,
        "requested_renderers": _csv(renderers),
        "clip_mode": clip_mode,
        "no_content": bool(no_content),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
