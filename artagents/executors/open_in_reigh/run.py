#!/usr/bin/env python3
"""Best-effort manual handoff helper for reigh-app timeline JSON."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from ...timeline import Timeline


DEFAULT_REIGH_APP = Path("/Users/peteromalley/Documents/reigh-workspace/reigh-app")
PROBE_DIRS = ("public/timelines", "public/demos", "timelines", "demos")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Copy hype.timeline.json + hype.assets.json for manual handoff into reigh-app-compatible locations.",
        epilog=(
            "Asset path limitation: hype.assets.json keeps local absolute paths from cut.py. "
            "reigh-app's SupabaseDataProvider resolves asset `file` values as HTTP URLs or "
            "timeline-assets bucket keys, so local paths must be replaced after upload or self-hosting."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", type=Path, required=True, help="Directory containing hype.timeline.json and hype.assets.json.")
    parser.add_argument("--reigh-app", type=Path, default=DEFAULT_REIGH_APP, help=f"Path to the reigh-app checkout. Default: {DEFAULT_REIGH_APP}")
    parser.add_argument("--copy-to", type=Path, help="Copy the JSON files into this directory instead of probing reigh-app.")
    parser.add_argument("--name", default="hype", help="Name used when probing a file-based demo folder.")
    parser.add_argument("--print-sql", action="store_true", help="Print an UPSERT template for public.timelines. The bridge never opens a Supabase connection.")
    parser.add_argument("--timeline-id", required=True, help="UUID for public.timelines.id. Required; no default is generated.")
    parser.add_argument("--dry-run", action="store_true", help="Show the intended action without writing files.")
    return parser


def source_paths(out_dir):
    timeline_path = out_dir.resolve() / "hype.timeline.json"
    assets_path = out_dir.resolve() / "hype.assets.json"
    missing = [str(path) for path in (timeline_path, assets_path) if not path.is_file()]
    if missing:
        print(f"open_in_reigh.py: missing required output file(s): {', '.join(missing)}", file=sys.stderr)
        return None, None
    return timeline_path, assets_path


def probe_target(args):
    if args.copy_to:
        return args.copy_to.resolve()
    base = args.reigh_app.resolve()
    for rel in PROBE_DIRS:
        candidate = base / rel
        if candidate.is_dir():
            return candidate / args.name
    return None


def print_copy_plan(timeline_path, assets_path, target, dry_run):
    label = "Would copy" if dry_run else "Copied"
    print(f"{label} {timeline_path} -> {target / timeline_path.name}")
    print(f"{label} {assets_path} -> {target / assets_path.name}")
    print("Reminder: reigh-app's live editor reads timeline rows from Supabase public.timelines, not these copied files.")


def maybe_copy_files(timeline_path, assets_path, target, dry_run):
    if target is None:
        return
    print_copy_plan(timeline_path, assets_path, target, dry_run)
    if dry_run:
        return
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(timeline_path, target / timeline_path.name)
    shutil.copyfile(assets_path, target / assets_path.name)


def print_manual_handoff(args):
    print(
        "\n".join(
            [
                "No file-backed reigh-app import directory was found.",
                "reigh-app stores timeline data in public.timelines rows with config + asset_registry columns.",
                "Provider reference: reigh-app/src/tools/video-editor/data/SupabaseDataProvider.ts",
                "Manual handoff options:",
                "1. Paste the SQL below into the Supabase dashboard SQL editor after filling <PROJECT_ID> and <USER_ID>.",
                "2. Rerun with --print-sql for the ready INSERT ... ON CONFLICT statement.",
                "3. Rerun with --copy-to DIR if you still want byte-preserved file copies for reference.",
                "ASSET PATH LIMITATION:",
                "hype.assets.json contains local absolute paths from cut.py.",
                "SupabaseDataProvider resolves asset `file` values only as HTTP URLs or timeline-assets bucket keys.",
                "Upload media to the timeline-assets bucket or self-host it, then update each asset `file` value before the timeline will play.",
            ]
        )
    )


def load_json_blob(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_timeline_blob(path):
    return Timeline.load(path).to_json_data()


def sql_json_literal(obj):
    return json.dumps(obj, ensure_ascii=False).replace("'", "''")


def print_sql(args, timeline_path, assets_path):
    timeline_blob = sql_json_literal(load_timeline_blob(timeline_path))
    assets_blob = sql_json_literal(load_json_blob(assets_path))
    safe_name = args.name.replace("'", "''")
    print("SQL template only: fill <PROJECT_ID> and <USER_ID> yourself. This bridge does NOT open a Supabase connection.")
    print(
        "INSERT INTO public.timelines (id, config, asset_registry, project_id, user_id, name) "
        f"VALUES ('{args.timeline_id}', '{timeline_blob}'::jsonb, '{assets_blob}'::jsonb, '<PROJECT_ID>', '<USER_ID>', '{safe_name}') "
        "ON CONFLICT (id) DO UPDATE SET config = EXCLUDED.config, asset_registry = EXCLUDED.asset_registry;"
    )


def main(argv=None):
    args = build_parser().parse_args(argv)
    timeline_path, assets_path = source_paths(args.out)
    if timeline_path is None or assets_path is None:
        return 1
    target = probe_target(args)
    if target is not None:
        maybe_copy_files(timeline_path, assets_path, target, args.dry_run)
    else:
        print_manual_handoff(args)
    if args.print_sql:
        print_sql(args, timeline_path, assets_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
