"""Command-line interface for ArtAgents projects."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import paths
from .materialize import require_run_clip, write_materialized_project_timeline
from .project import ProjectError, create_project, require_project, show_project
from .schema import SOURCE_KINDS, run_ref, source_ref
from .source import add_source, require_source
from .timeline import add_placement, load_timeline, remove_placement


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
        prog="python3 -m artagents projects",
        description="Create, inspect, and manage persistent ArtAgents projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a project.")
    create_parser.add_argument("slug")
    create_parser.add_argument("--name")
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

    timeline_parser = subparsers.add_parser("timeline", help="Inspect and edit a project timeline.")
    timeline_subparsers = timeline_parser.add_subparsers(dest="timeline_command", required=True)
    timeline_show = timeline_subparsers.add_parser("show", help="Show ProjectTimeline placements.")
    _add_project_arg(timeline_show)
    timeline_show.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    timeline_show.set_defaults(handler=_cmd_timeline_show)

    place_source = timeline_subparsers.add_parser("place-source", help="Place a source clip on the project timeline.")
    _add_project_arg(place_source)
    place_source.add_argument("placement_id")
    place_source.add_argument("--source", required=True, help="Source id to place.")
    place_source.add_argument("--track", required=True, help="Timeline track id.")
    place_source.add_argument("--at", required=True, type=float, help="Placement start time in seconds.")
    place_source.add_argument("--from", dest="from_", type=float, help="Source trim start in seconds.")
    place_source.add_argument("--to", type=float, help="Source trim end in seconds.")
    place_source.add_argument("--entrance-json", help="JSON object/list for entrance animation.")
    place_source.add_argument("--exit-json", help="JSON object/list for exit animation.")
    place_source.add_argument("--transition-json", help="JSON object for transition.")
    place_source.add_argument("--effects-json", help="JSON list for effects.")
    place_source.add_argument("--params-json", help="JSON object for clip params.")
    place_source.add_argument("--replace", action="store_true", help="Replace an existing placement with the same id.")
    place_source.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    place_source.set_defaults(handler=_cmd_timeline_place_source)

    place_run = timeline_subparsers.add_parser("place-run", help="Place a clip from a project run on the timeline.")
    _add_project_arg(place_run)
    place_run.add_argument("placement_id")
    place_run.add_argument("--run", dest="run_id", required=True, help="Project run id.")
    place_run.add_argument("--clip", required=True, help="Clip id inside the run timeline.")
    place_run.add_argument("--track", required=True, help="Timeline track id.")
    place_run.add_argument("--at", required=True, type=float, help="Placement start time in seconds.")
    place_run.add_argument("--from", dest="from_", type=float, help="Override clip trim start in seconds.")
    place_run.add_argument("--to", type=float, help="Override clip trim end in seconds.")
    place_run.add_argument("--entrance-json", help="JSON object/list for entrance animation.")
    place_run.add_argument("--exit-json", help="JSON object/list for exit animation.")
    place_run.add_argument("--transition-json", help="JSON object for transition.")
    place_run.add_argument("--effects-json", help="JSON list for effects.")
    place_run.add_argument("--params-json", help="JSON object for clip params.")
    place_run.add_argument("--replace", action="store_true", help="Replace an existing placement with the same id.")
    place_run.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    place_run.set_defaults(handler=_cmd_timeline_place_run)

    timeline_remove = timeline_subparsers.add_parser("remove", help="Remove a placement from the project timeline.")
    _add_project_arg(timeline_remove)
    timeline_remove.add_argument("placement_id")
    timeline_remove.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    timeline_remove.set_defaults(handler=_cmd_timeline_remove)

    materialize_parser = subparsers.add_parser("materialize", help="Write renderable hype.timeline.json and hype.assets.json.")
    _add_project_arg(materialize_parser)
    materialize_parser.add_argument("--out", required=True, help="Output directory for materialized files.")
    materialize_parser.add_argument("--theme", default="banodoco-default", help="Timeline theme slug.")
    materialize_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    materialize_parser.set_defaults(handler=_cmd_materialize)
    return parser


def _add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="Project slug.")


def _cmd_create(args: argparse.Namespace) -> int:
    project = create_project(args.slug, name=args.name)
    if args.json:
        _print_json({"project": project, "root": str(paths.project_dir(project["slug"]))})
        return 0
    _print_project_header(project["slug"])
    print(f"created: {project['name']}")
    print(f"next: python3 -m artagents projects show --project {project['slug']}")
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
    print(f"next: python3 -m artagents projects timeline show --project {args.project}")
    return 0


def _cmd_timeline_show(args: argparse.Namespace) -> int:
    project = require_project(args.project)
    timeline = load_timeline(args.project)
    if args.json:
        _print_json({"timeline": timeline})
        return 0
    _print_project_header(project["slug"])
    placements = timeline.get("placements", [])
    if not placements:
        print("timeline:")
        print("  placements: none")
        return 0
    print("timeline:")
    for placement in placements:
        ref = placement.get("source", {})
        print(
            f"  - {placement.get('id')} track={placement.get('track')} at={placement.get('at')} "
            f"source={ref.get('kind')}:{ref.get('id') or ref.get('run_id')}"
        )
    return 0


def _cmd_timeline_place_source(args: argparse.Namespace) -> int:
    require_project(args.project)
    require_source(args.project, args.source)
    timeline = add_placement(
        args.project,
        args.placement_id,
        track=args.track,
        at=args.at,
        source=source_ref(args.source),
        from_=args.from_,
        to=args.to,
        entrance=_json_option(args.entrance_json, "--entrance-json"),
        exit=_json_option(args.exit_json, "--exit-json"),
        transition=_json_option(args.transition_json, "--transition-json"),
        effects=_json_option(args.effects_json, "--effects-json"),
        params=_json_option(args.params_json, "--params-json"),
        replace=bool(args.replace),
    )
    placement = next(item for item in timeline["placements"] if item["id"] == args.placement_id)
    if args.json:
        _print_json({"placement": placement, "timeline": timeline})
        return 0
    _print_project_header(args.project)
    print(f"placement: {placement['id']}")
    print(f"source: source:{args.source}")
    print(f"next: python3 -m artagents projects materialize --project {args.project} --out <dir>")
    return 0


def _cmd_timeline_place_run(args: argparse.Namespace) -> int:
    require_project(args.project)
    require_run_clip(args.project, args.run_id, args.clip)
    timeline = add_placement(
        args.project,
        args.placement_id,
        track=args.track,
        at=args.at,
        source=run_ref(args.run_id, args.clip),
        from_=args.from_,
        to=args.to,
        entrance=_json_option(args.entrance_json, "--entrance-json"),
        exit=_json_option(args.exit_json, "--exit-json"),
        transition=_json_option(args.transition_json, "--transition-json"),
        effects=_json_option(args.effects_json, "--effects-json"),
        params=_json_option(args.params_json, "--params-json"),
        replace=bool(args.replace),
    )
    placement = next(item for item in timeline["placements"] if item["id"] == args.placement_id)
    if args.json:
        _print_json({"placement": placement, "timeline": timeline})
        return 0
    _print_project_header(args.project)
    print(f"placement: {placement['id']}")
    print(f"source: run:{args.run_id}:{args.clip}")
    print(f"next: python3 -m artagents projects materialize --project {args.project} --out <dir>")
    return 0


def _cmd_timeline_remove(args: argparse.Namespace) -> int:
    timeline = remove_placement(args.project, args.placement_id)
    if args.json:
        _print_json({"removed": args.placement_id, "timeline": timeline})
        return 0
    _print_project_header(args.project)
    print(f"removed: {args.placement_id}")
    print(f"next: python3 -m artagents projects timeline show --project {args.project}")
    return 0


def _cmd_materialize(args: argparse.Namespace) -> int:
    require_project(args.project)
    timeline_path, assets_path = write_materialized_project_timeline(args.project, args.out, theme=args.theme)
    if args.json:
        _print_json({"assets": str(assets_path), "timeline": str(timeline_path)})
        return 0
    _print_project_header(args.project)
    print(f"timeline: {timeline_path}")
    print(f"assets: {assets_path}")
    return 0


def _json_option(raw: str | None, flag: str) -> Any:
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{flag} must be valid JSON: {exc.msg}") from exc


def _print_project_header(slug: str) -> None:
    print(f"Project: {slug}")
    print(f"Root: {paths.project_dir(slug)}")


def _print_project_tree(payload: dict[str, Any]) -> None:
    project = payload["project"]
    print(f"{project['slug']}/")
    print("  project.json")
    print("  timeline.json")
    print("  sources/")
    for source_id in payload.get("sources", []):
        print(f"    {source_id}/")
        print("      source.json")
        print("      analysis/")
    print("  runs/")
    for run_id in payload.get("runs", []):
        print(f"    {run_id}/")
        print("      run.json")
        print("      timeline.json")
        print("      assets.json")
        print("      metadata.json")
    print(f"placements: {payload['timeline']['placements']}")


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
