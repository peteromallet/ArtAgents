"""Sprint 5b: thumbnail_maker orchestrator — plan v2 emission + task gate loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from astrid.packs.builtin.orchestrators.thumbnail_maker.plan_template import build_plan_v2, emit_plan_json
from astrid.packs.builtin.executors.asset_cache import run as asset_cache
from astrid.core.task import env as task_env
from astrid.core.task import gate as task_gate
from astrid.core.task.events import append_event
from astrid.core.project.run import (
    ProjectRunError,
    finalize_project_run,
    prepare_project_run,
    reject_project_with_out,
)
from astrid.core.project.paths import project_dir, validate_project_slug


# ---------------------------------------------------------------------------
# Constants (kept from original)
# ---------------------------------------------------------------------------

DEFAULT_SIZE = "1536x864"
DEFAULT_COUNT = 1
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_QUALITY = "medium"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_VISUAL_MODE = "fast"
DEFAULT_REFERENCE_MODE = "auto"
DEFAULT_MAX_CANDIDATES = 20
MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300030202030202030303030403030405080505"
    "0404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812"
    "141514ffdb00430103040405040509050509140d0b0d14141414141414141414141414141414141414141414"
    "141414141414141414141414141414141414141414141414141414141414141414ffc0001108000100010301220002"
    "1101031101ffc4001400010000000000000000000000000000000000000008ffc40014100100000000000000"
    "000000000000000000000000ffda000c03010002110311003f00b2c001ffd9"
)

OUTPUT_DIRS = {
    "evidence": "evidence",
    "references": "references",
    "prompts": "prompts",
    "generated": "generated",
    "review": "review",
}

PERSON_TERMS = {
    "face", "headshot", "host", "interview", "man", "person",
    "portrait", "presenter", "speaker", "talking", "woman",
}
SCENE_TERMS = {
    "background", "crowd", "environment", "location", "room",
    "scene", "stage", "studio", "venue",
}
TEXT_TERMS = {
    "caption", "headline", "quote", "subtitle", "text", "title", "words",
}
EMOTION_TERMS = {
    "angry", "dramatic", "emotional", "excited", "funny",
    "intense", "laugh", "shocked", "surprised",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT, for example 1536x864")
    return int(match.group(1)), int(match.group(2))


def normalized_size(value: str) -> str:
    width, height = parse_size(value)
    return f"{width}x{height}"


def build_output_layout(out_dir: Path) -> dict[str, Path]:
    root = out_dir.expanduser().resolve()
    layout = {"root": root}
    layout.update({key: root / name for key, name in OUTPUT_DIRS.items()})
    return layout


def ensure_output_layout(layout: dict[str, Path]) -> None:
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)


def _query_tokens(query: str) -> list[str]:
    return sorted(set(re.findall(r"[a-z0-9]+", query.lower())))


def plan_evidence_needs(query: str) -> dict[str, Any]:
    tokens = _query_tokens(query)
    token_set = set(tokens)
    needs: list[dict[str, Any]] = []
    if token_set & PERSON_TERMS:
        needs.append({
            "id": "speaker_or_person_framing",
            "reason": "Query appears to need a readable person or speaker-oriented frame.",
            "source": "video_frames",
            "selection_hint": "Prefer clear upper-body or face-visible composition when present.",
        })
    if token_set & SCENE_TERMS:
        needs.append({
            "id": "scene_context",
            "reason": "Query references the surrounding scene or location.",
            "source": "scene_frames",
            "selection_hint": "Prefer frames that show the environment clearly.",
        })
    if token_set & TEXT_TERMS:
        needs.append({
            "id": "title_or_quote_context",
            "reason": "Query references text, a title, caption, or quoted idea.",
            "source": "query_text",
            "selection_hint": "Preserve room for readable thumbnail text.",
        })
    if token_set & EMOTION_TERMS:
        needs.append({
            "id": "expressive_moment",
            "reason": "Query asks for an emotional or high-energy thumbnail.",
            "source": "video_frames",
            "selection_hint": "Prefer visually expressive frames.",
        })
    if not needs:
        needs.append({
            "id": "representative_visual_context",
            "reason": "No specialized evidence need was detected, so representative video frames are sufficient.",
            "source": "scene_frames",
            "selection_hint": "Prefer sharp, legible, non-transitional frames.",
        })
    return {
        "query": query,
        "tokens": tokens,
        "needs": needs,
        "planner": {"name": "deterministic_keyword_planner", "version": 1},
    }


def resolve_video_for_analysis(video: str, *, dry_run: bool) -> dict[str, Any]:
    original = str(video)
    try:
        resolved = asset_cache.resolve_input(original, want="path")
    except Exception as exc:
        if not dry_run:
            raise
        return {
            "original": original,
            "resolved": original,
            "resolved_ok": False,
            "resolution_error": str(exc),
        }
    return {
        "original": original,
        "resolved": str(Path(resolved)),
        "resolved_ok": True,
        "resolution_error": None,
    }


def _sha256_for_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Orchestrator (plan v2 + task gate)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create source-relevant thumbnail candidates for a video."
    )
    parser.add_argument("--video", help="Source video path or URL.", default=argparse.SUPPRESS)
    parser.add_argument("--query", default="auto", help="Thumbnail direction or search query.")
    parser.add_argument("--out", type=Path, help="Output directory.", default=argparse.SUPPRESS)
    parser.add_argument("--size", default=DEFAULT_SIZE, type=normalized_size)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--quality", default=DEFAULT_QUALITY, choices=("low", "medium", "high", "auto"))
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT, choices=("png", "jpeg", "jpg", "webp"))
    parser.add_argument("--visual-mode", default=DEFAULT_VISUAL_MODE, choices=("fast", "best"))
    parser.add_argument("--reference-mode", default=DEFAULT_REFERENCE_MODE, choices=("auto", "always", "never"))
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--feedback")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--project", help="Project slug.", default=argparse.SUPPRESS)
    parser.add_argument("--python-exec", help="Python executable.", default=sys.executable)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def resolve_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parsed = build_parser().parse_args(argv)
    cli_values = vars(parsed)
    merged = dict(cli_values)

    args = argparse.Namespace(**merged)
    args.python_exec = str(getattr(args, "python_exec", sys.executable))
    args.verbose = bool(getattr(args, "verbose", False))
    args.dry_run = bool(getattr(args, "dry_run", False))

    out = getattr(args, "out", None)
    if out is not None:
        args.out = Path(out).expanduser().resolve()

    video = getattr(args, "video", None)
    if video is not None and not asset_cache.is_url(video):
        args.video = Path(video).expanduser().resolve()

    return args


def _write_run_json(args: argparse.Namespace) -> None:
    run_json = args.out / "run.json"
    consumes: list[dict[str, str]] = []
    video = getattr(args, "video", None)
    if video is not None and isinstance(video, Path) and video.is_file():
        consumes.append({"source": str(video), "sha256": _sha256_for_path(video)})

    fields: dict[str, Any] = {
        "consumes": consumes,
        "orchestrator": "builtin.thumbnail_maker",
    }

    if run_json.exists():
        try:
            existing = json.loads(run_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(fields)
        run_json.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        run_json.parent.mkdir(parents=True, exist_ok=True)
        run_json.write_text(json.dumps(fields, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_run_started(run_root: Path) -> None:
    import datetime as dt
    ev = {"kind": "run_started", "ts": dt.datetime.now(dt.timezone.utc).isoformat()}
    append_event(run_root / "events.jsonl", ev)


def run_orchestrator(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)

    project_slug = getattr(args, "project", None)
    if project_slug is not None:
        proj_root = project_dir(project_slug)
        plan_path = proj_root / "plan.json"
    else:
        plan_path = args.out / "plan.json"

    plan = build_plan_v2(
        python_exec=args.python_exec,
        run_root=args.out,
        source=getattr(args, "video", None),
    )
    emit_plan_json(plan, plan_path)

    from astrid.core.task.plan import compute_plan_hash
    plan_hash = compute_plan_hash(plan_path)

    _write_run_json(args)
    _append_run_started(args.out)

    if args.dry_run:
        print(f"thumbnail_maker: plan emitted to {plan_path} (plan_hash={plan_hash})")
        return 0

    if project_slug is None:
        print("thumbnail_maker: --project required for task-gate execution", file=sys.stderr)
        return 1

    slug = validate_project_slug(project_slug)
    return _execute_via_task_gate(slug, args)


def _execute_via_task_gate(slug: str, args: argparse.Namespace) -> int:
    import subprocess as sp

    while True:
        try:
            decision = task_gate.gate_command(
                slug,
                task_gate.command_for_argv(
                    ["python3", "-m", "astrid", "thumbnail_maker", "--project", slug]
                ),
                ["thumbnail_maker", "--project", slug],
                reentry=True,
            )
        except task_gate.TaskRunGateError as exc:
            print(f"thumbnail_maker: gate error: {exc.reason}", file=sys.stderr)
            return 1

        if not decision.active:
            return 0

        if decision.command is None:
            continue

        print(f"thumbnail_maker: running step: {' '.join(decision.command)}", flush=True)
        result = sp.run(decision.command, check=False)
        if result.returncode != 0:
            print(f"thumbnail_maker: step failed with returncode={result.returncode}", file=sys.stderr)
            return result.returncode

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    project_context = None

    try:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--project")
        parser.add_argument("--out")
        parsed, _unknown = parser.parse_known_args(effective_argv)

        if parsed.project and task_env.is_in_task_run(parsed.project):
            try:
                task_gate.gate_command(
                    parsed.project,
                    task_gate.command_for_argv(
                        ["python3", "-m", "astrid", "thumbnail_maker", *effective_argv]
                    ),
                    effective_argv,
                    reentry=True,
                )
            except task_gate.TaskRunGateError as exc:
                print(exc.recovery, file=sys.stderr)
                return 1

        if parsed.project:
            reject_project_with_out(parsed.project, parsed.out)
            project_context = prepare_project_run(
                parsed.project,
                tool_id="builtin.thumbnail_maker",
                kind="orchestrator",
                argv=["thumbnail_maker", *effective_argv],
                metadata={"entrypoint": "direct"},
            )
            effective_argv = [*effective_argv, "--out", str(project_context.run_root)]

        args = resolve_args(effective_argv)
        if project_context is not None:
            args.project = project_context.project_slug

        returncode = run_orchestrator(args)

        if project_context is not None:
            finalize_project_run(
                project_context,
                status="success" if returncode == 0 else "failed",
                returncode=returncode,
                metadata={"dry_run": args.dry_run},
            )

        return returncode
    except SystemExit as exc:
        if project_context is not None:
            finalize_project_run(
                project_context,
                status="error",
                returncode=exc.code if isinstance(exc.code, int) else 1,
                error=exc,
            )
        if isinstance(exc.code, int):
            return exc.code
        return 1
    except Exception as exc:
        if project_context is not None:
            finalize_project_run(project_context, status="error", returncode=-1, error=exc)
        raise


if __name__ == "__main__":
    raise SystemExit(main())