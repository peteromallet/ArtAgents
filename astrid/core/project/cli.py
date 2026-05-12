"""Command-line interface for Astrid projects.

T10 collapsed the parallel placement schema. T11 reinstates ``edit
<project_id>`` (sub-verbs ``add-clip``/``move-clip``/``set-theme``) and
``list <project_id>`` that operate on reigh-app UUIDs through
``astrid.core.reigh.SupabaseDataProvider``. Edit verbs shell out to
``scripts/node/ops_helper.mjs`` to apply timeline-ops primitives, then call
``SupabaseDataProvider.save_timeline`` with the required
``expected_version`` (read from reigh-data-fetch's ``config_version``).

Auth scope (FLAG-012, SD-009): the CLI is an ownership-bound client, so the
write path uses a user PAT (``REIGH_PAT``) by default rather than the
worker-only service-role key. ``--service-role`` is provided as a documented
escape hatch for operators who know the row is theirs to edit; the worker
itself uses a separate code path (``astrid.core.worker.banodoco_worker``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from astrid.core.session.binding import (
    SessionBindingError,
    resolve_current_session,
)

from . import paths
from .project import ProjectError, create_project, require_project, show_project
from .schema import SOURCE_KINDS
from .source import add_source


REPO_ROOT = Path(__file__).resolve().parents[3]
OPS_HELPER = REPO_ROOT / "scripts" / "node" / "ops_helper.mjs"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileExistsError, FileNotFoundError, ProjectError, ValueError) as exc:
        print(f"projects: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid projects",
        description="Create, inspect, and manage persistent Astrid projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a project.")
    create_parser.add_argument("slug")
    create_parser.add_argument("--name")
    create_parser.add_argument(
        "--project-id",
        dest="project_id",
        help="Optional reigh-app project UUID (stored opaque in project.json).",
    )
    create_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    create_parser.set_defaults(handler=_cmd_create)

    show_parser = subparsers.add_parser("show", help="Show a project tree.")
    _add_project_arg(show_parser)
    show_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    show_parser.set_defaults(handler=_cmd_show)

    source_parser = subparsers.add_parser("source", help="Manage project sources.")
    source_subparsers = source_parser.add_subparsers(dest="source_command", required=True)
    source_add = source_subparsers.add_parser("add", help="Add a source to a project.")
    _add_project_arg(source_add)
    source_add.add_argument("source_id")
    asset_group = source_add.add_mutually_exclusive_group(required=True)
    asset_group.add_argument("--file", dest="file_path", help="Local source media file.")
    asset_group.add_argument("--url", help="Remote http(s) source media URL.")
    source_add.add_argument("--kind", choices=sorted(SOURCE_KINDS), help="Source media kind.")
    source_add.add_argument("--type", help="Asset type such as video/mp4, image/png, or audio/mpeg.")
    source_add.add_argument("--duration", type=float, help="Asset duration in seconds.")
    source_add.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    source_add.set_defaults(handler=_cmd_source_add)

    list_parser = subparsers.add_parser(
        "list",
        help="List timelines on a reigh-app project (project_id UUID).",
    )
    list_parser.add_argument("project_id", help="reigh-app project UUID.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(handler=_cmd_list)

    edit_parser = subparsers.add_parser(
        "edit",
        help="Edit a reigh-app timeline via timeline-ops primitives + SupabaseDataProvider.",
    )
    edit_parser.add_argument("project_id", help="reigh-app project UUID.")
    edit_parser.add_argument("--timeline-id", required=True, help="reigh-app timeline UUID.")
    edit_parser.add_argument(
        "--service-role",
        action="store_true",
        help="Worker-only escape hatch: authenticate via REIGH_SUPABASE_SERVICE_ROLE_KEY.",
    )
    edit_parser.add_argument("--json", action="store_true")
    edit_subparsers = edit_parser.add_subparsers(dest="edit_op", required=True)

    add_clip = edit_subparsers.add_parser("add-clip", help="Insert a clip via timeline-ops.addClip.")
    add_clip.add_argument("--clip-json", required=True, help="JSON object describing the clip.")
    add_clip.add_argument("--position", type=int, help="Insertion index (default: append).")
    add_clip.set_defaults(handler=_cmd_edit, edit_op_name="add-clip")

    move_clip = edit_subparsers.add_parser("move-clip", help="Reposition a clip via timeline-ops.moveClip.")
    move_clip.add_argument("--clip-id", required=True)
    move_clip.add_argument("--new-position", required=True, type=float, help="New start time in seconds.")
    move_clip.set_defaults(handler=_cmd_edit, edit_op_name="move-clip")

    set_theme = edit_subparsers.add_parser("set-theme", help="Set the active theme via timeline-ops.setTimelineTheme.")
    set_theme.add_argument("--theme-id", required=True)
    set_theme.set_defaults(handler=_cmd_edit, edit_op_name="set-theme")

    # --- cost (Sprint 5b) ---
    cost_parser = subparsers.add_parser("cost", help="Show cost rollup for a project.")
    _add_project_arg(cost_parser)
    cost_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of pretty-print.",
    )
    cost_parser.add_argument(
        "--include-aborted",
        action="store_true",
        help="Include aborted runs in the cost rollup.",
    )
    cost_parser.set_defaults(handler=_cmd_project_cost)

    # --- export (Sprint 5b) ---
    export_parser = subparsers.add_parser("export", help="Export a project bundle.")
    _add_project_arg(export_parser)
    export_parser.add_argument("--out", required=True, help="Output tarball path (.tar.gz).")
    export_parser.add_argument(
        "--include-aborted",
        action="store_true",
        help="Include aborted runs in the export bundle.",
    )
    export_parser.set_defaults(handler=_cmd_project_export)

    return parser


def _add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="Project slug.")


def _cmd_create(args: argparse.Namespace) -> int:
    project = create_project(args.slug, name=args.name, project_id=getattr(args, "project_id", None))
    if args.json:
        _print_json({"project": project, "root": str(paths.project_dir(project["slug"]))})
        return 0
    _print_project_header(project["slug"])
    print(f"created: {project['name']}")
    if project.get("project_id"):
        print(f"project_id: {project['project_id']}")
    print(f"next: python3 -m astrid projects show --project {project['slug']}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    project = require_project(args.project)
    payload = show_project(args.project)
    if args.json:
        _print_json(payload)
        return 0
    _print_project_header(project["slug"])
    _print_project_tree(payload)
    return 0


def _cmd_source_add(args: argparse.Namespace) -> int:
    require_project(args.project)
    asset: dict[str, Any] = {}
    if args.file_path:
        asset["file"] = args.file_path
    if args.url:
        asset["url"] = args.url
    if args.type:
        asset["type"] = args.type
    if args.duration is not None:
        asset["duration"] = args.duration
    source = add_source(args.project, args.source_id, asset=asset, kind=args.kind)
    if args.json:
        _print_json({"source": source})
        return 0
    _print_project_header(args.project)
    print(f"source: {source['source_id']}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List timelines for a reigh-app project via reigh-data-fetch."""

    from astrid.core.reigh import env as reigh_env
    from astrid.core.reigh.supabase_client import post_json

    auth = ("pat", reigh_env.resolve_pat())
    payload = post_json(
        reigh_env.resolve_api_url(),
        {"project_id": args.project_id},
        auth=auth,
    )
    timelines = []
    if isinstance(payload, dict):
        raw = payload.get("timelines")
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                timelines.append(
                    {
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "config_version": entry.get("config_version"),
                        "updated_at": entry.get("updated_at"),
                    }
                )
    if args.json:
        _print_json({"project_id": args.project_id, "timelines": timelines})
        return 0
    print(f"project_id: {args.project_id}")
    if not timelines:
        print("timelines: none")
        return 0
    print("timelines:")
    for entry in timelines:
        print(f"  - {entry['id']} v={entry.get('config_version')} name={entry.get('name')}")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    """Edit a reigh-app timeline via timeline-ops + SupabaseDataProvider."""

    from astrid.core.reigh import env as reigh_env
    from astrid.core.reigh.data_provider import SupabaseDataProvider

    op = args.edit_op_name
    op_args = _build_op_args(args, op)

    if not OPS_HELPER.is_file():
        raise ProjectError(f"ops helper missing: {OPS_HELPER}")
    if shutil.which("node") is None:
        raise ProjectError("node executable not found on PATH; install Node 20+ to run edit verbs")

    provider = SupabaseDataProvider.from_env()
    if args.service_role:
        write_auth = ("service_role", reigh_env.resolve_service_role_key())
    else:
        write_auth = ("pat", reigh_env.resolve_pat())

    # First load to know expected_version (the mutator path will re-fetch on
    # conflict, but we need a starting version to satisfy the
    # save_timeline contract).
    _, current_version = provider.load_timeline(args.project_id, args.timeline_id)

    def mutator(config: dict[str, Any], version: int) -> dict[str, Any]:
        return _run_ops_helper(config, version, op, op_args)

    result = provider.save_timeline(
        args.timeline_id,
        mutator,
        project_id=args.project_id,
        auth=write_auth,
        expected_version=current_version,
        retries=3,
        force=False,
    )
    if args.json:
        _print_json(
            {
                "timeline_id": args.timeline_id,
                "project_id": args.project_id,
                "op": op,
                "new_version": result.new_version,
                "attempts": result.attempts,
            }
        )
        return 0
    print(
        f"edited timeline {args.timeline_id} project_id={args.project_id} "
        f"op={op} new_version={result.new_version} attempts={result.attempts}"
    )
    return 0


def _build_op_args(args: argparse.Namespace, op: str) -> dict[str, Any]:
    if op == "add-clip":
        try:
            clip = json.loads(args.clip_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--clip-json must be valid JSON: {exc.msg}") from exc
        if not isinstance(clip, dict):
            raise ValueError("--clip-json must decode to a JSON object")
        body: dict[str, Any] = {"clip": clip}
        if args.position is not None:
            body["position"] = args.position
        return body
    if op == "move-clip":
        return {"clipId": args.clip_id, "newPosition": args.new_position}
    if op == "set-theme":
        return {"themeId": args.theme_id}
    raise ValueError(f"unsupported edit op: {op}")


def _run_ops_helper(
    timeline: dict[str, Any],
    version: int,
    op: str,
    op_args: dict[str, Any],
) -> dict[str, Any]:
    request = json.dumps({"timeline": timeline, "version": version, "op": op, "args": op_args})
    completed = subprocess.run(
        ["node", str(OPS_HELPER)],
        input=request,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "ops_helper exited non-zero"
        raise ProjectError(f"ops_helper failed: {stderr}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"ops_helper produced non-JSON stdout: {exc.msg}") from exc
    timeline_out = response.get("timeline")
    if not isinstance(timeline_out, dict):
        raise ProjectError("ops_helper response missing .timeline object")
    return timeline_out


# ---------------------------------------------------------------------------
# Handler: project cost (Sprint 5b T8)
# ---------------------------------------------------------------------------


def _cmd_project_cost(args: argparse.Namespace) -> int:
    """Aggregate cost across all timelines in a project."""
    _require_project_session(args.project)

    from astrid.core.project.paths import project_dir
    from astrid.core.task.events import read_events
    from astrid.core.task.run_audit import _cost_by_source, _run_status
    from astrid.core.timeline.crud import list_timelines

    include_aborted = bool(getattr(args, "include_aborted", False))
    json_out = bool(getattr(args, "json", False))

    proj_root = project_dir(args.project)
    runs_dir = proj_root / "runs"

    timelines = list_timelines(args.project)
    if not timelines:
        if json_out:
            _print_json({"project": args.project, "grand_total": 0.0, "by_source": {}, "timeline_count": 0})
            return 0
        print(f"Project cost for '{args.project}': no timelines found")
        return 0

    # Collect unique contributing runs across all timelines
    seen_runs: set[str] = set()
    run_ids: list[str] = []
    for ts in timelines:
        try:
            from astrid.core.timeline.model import Manifest as TLManifest
            mp = project_dir(args.project) / "timelines" / ts.ulid / "manifest.json"
            if mp.is_file():
                manifest = TLManifest.from_json(mp)
                for rid in manifest.contributing_runs:
                    if rid not in seen_runs:
                        seen_runs.add(rid)
                        run_ids.append(rid)
        except Exception:
            continue

    # Aggregate costs across runs
    by_source: dict[str, float] = {}
    grand_total = 0.0
    run_count = 0

    for run_id in run_ids:
        run_root = runs_dir / run_id
        if not run_root.is_dir():
            continue
        events_path = run_root / "events.jsonl"
        if not events_path.exists():
            continue
        events = read_events(events_path)

        status = _run_status(events)
        if status == "aborted" and not include_aborted:
            continue

        run_count += 1
        cost_summary = _cost_by_source(events)
        for source, info in cost_summary.items():
            if isinstance(info, dict):
                amt = info.get("amount", 0)
                by_source[source] = by_source.get(source, 0.0) + float(amt)
                grand_total += float(amt)

    if json_out:
        payload: dict[str, Any] = {
            "project": args.project,
            "timeline_count": len(timelines),
            "contributing_runs": run_count,
            "include_aborted": include_aborted,
            "grand_total": round(grand_total, 6),
            "by_source": {
                source: round(amt, 6) for source, amt in sorted(by_source.items())
            },
        }
        _print_json(payload)
        return 0

    print(f"Cost rollup for project '{args.project}' ({len(timelines)} timelines, {run_count} contributing runs):")
    print()
    if not by_source:
        print("  (no cost data)")
    else:
        for source in sorted(by_source):
            amt = by_source[source]
            print(f"  {source:<20} ${amt:>10.4f}")
    print(f"  {'─' * 32}")
    print(f"  {'TOTAL':<20} ${grand_total:>10.4f}")
    return 0


# ---------------------------------------------------------------------------
# Handler: project export (Sprint 5b T9)
# ---------------------------------------------------------------------------


def _cmd_project_export(args: argparse.Namespace) -> int:
    """Export a project as a self-contained tarball bundle."""
    _require_project_session(args.project)

    from astrid.core.project.paths import project_dir
    from astrid.core.task.events import read_events
    from astrid.core.task.run_audit import _run_status
    from astrid.core.timeline.crud import list_timelines

    include_aborted = bool(getattr(args, "include_aborted", False))
    out_path = Path(args.out).expanduser().resolve()
    proj_root = project_dir(args.project)
    runs_dir = proj_root / "runs"

    timelines = list_timelines(args.project)

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        manifest_entries: list[tuple[str, str]] = []

        def _add_file(src: Path, rel: str) -> None:
            dst = tmpdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            sha = hashlib.sha256(dst.read_bytes()).hexdigest()
            manifest_entries.append((rel, sha))

        # Collect unique contributing runs across all timelines
        seen_runs: set[str] = set()
        all_run_ids: list[str] = []
        for ts in timelines:
            # Copy timeline container files
            tdir = proj_root / "timelines" / ts.ulid
            for name in ("assembly.json", "manifest.json", "display.json"):
                src = tdir / name
                if src.is_file():
                    _add_file(src, f"timelines/{ts.ulid}/{name}")

            # Collect run IDs
            try:
                from astrid.core.timeline.model import Manifest as TLManifest
                mp = tdir / "manifest.json"
                if mp.is_file():
                    manifest = TLManifest.from_json(mp)
                    for rid in manifest.contributing_runs:
                        if rid not in seen_runs:
                            seen_runs.add(rid)
                            all_run_ids.append(rid)
            except Exception:
                continue

        # Copy project-level files
        project_json = proj_root / "project.json"
        if project_json.is_file():
            _add_file(project_json, "project.json")

        # Copy contributing runs
        for run_id in all_run_ids:
            run_root = runs_dir / run_id
            if not run_root.is_dir():
                continue

            events_path = run_root / "events.jsonl"
            if events_path.exists():
                events = read_events(events_path)
                status = _run_status(events)
                if status == "aborted" and not include_aborted:
                    continue

            # Copy plan.json
            plan_path = proj_root / "plan.json"
            if plan_path.is_file():
                _add_file(plan_path, f"runs/{run_id}/plan.json")

            # Copy events.jsonl
            if events_path.is_file():
                _add_file(events_path, f"runs/{run_id}/events.jsonl")

            # Copy produces/ tree
            produces_root = run_root / "produces"
            if produces_root.is_dir():
                for src_file in produces_root.rglob("*"):
                    if src_file.is_file():
                        rel = str(Path("runs") / run_id / "produces" / src_file.relative_to(produces_root))
                        _add_file(src_file, rel)

            # Copy run.json if present
            run_json = run_root / "run.json"
            if run_json.is_file():
                _add_file(run_json, f"runs/{run_id}/run.json")

        # Write MANIFEST.txt
        manifest_txt = tmpdir / "MANIFEST.txt"
        lines = [f"{sha}  {rel}" for rel, sha in sorted(manifest_entries)]
        manifest_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Build tarball
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out_path, "w:gz") as tar:
            for member in sorted(tmpdir.iterdir()):
                tar.add(member, arcname=member.name)

    print(f"exported project '{args.project}' to {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SESSION_GATE_HINT = (
    "A project command requires a bound session. "
    "Run 'astrid attach <project>' first."
)


def _require_project_session(project_slug: str) -> None:
    session = resolve_current_session()
    if session is None:
        raise SessionBindingError(_SESSION_GATE_HINT)


def _print_project_header(slug: str) -> None:
    print(f"Project: {slug}")
    print(f"Root: {paths.project_dir(slug)}")


def _print_project_tree(payload: dict[str, Any]) -> None:
    project = payload["project"]
    print(f"{project['slug']}/")
    print("  project.json")
    print("  sources/")
    for source_id in payload.get("sources", []):
        print(f"    {source_id}/")
        print("      source.json")
        print("      analysis/")
    print("  runs/")
    for run_id in payload.get("runs", []):
        print(f"    {run_id}/")
        print("      run.json")
        print("      assets.json")
        print("      metadata.json")
    # Sprint 2: timelines as first-class containers.
    try:
        from astrid.core.timeline import crud as timeline_crud
        summaries = timeline_crud.list_timelines(payload["project"]["slug"])
    except Exception:
        summaries = []
    if summaries:
        print("  timelines/")
        for t in summaries:
            print(f"    {t.ulid}/  (slug: {t.slug}, name: {t.name})")
            print("      assembly.json")
            print("      manifest.json")
            print("      display.json")
    if payload.get("project_id"):
        print(f"reigh project_id: {payload['project_id']}")


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
