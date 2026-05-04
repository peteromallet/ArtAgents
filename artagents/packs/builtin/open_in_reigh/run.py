#!/usr/bin/env python3
"""Push a locally-materialized hype timeline into a reigh-app row.

Default flow: load ``hype.timeline.json`` + ``hype.assets.json`` from ``--out``,
then call ``SupabaseDataProvider.save_timeline`` to upsert the row identified
by ``--timeline-id``.

SD-009 / FLAG-012 — auth scope: this CLI helper writes a user-owned row, so by
default it authenticates with the user's PAT (``REIGH_PAT``) rather than the
worker-only service-role key. The DataProvider's optimistic-versioning path
still applies; ``--force`` skips the version check (logged WARNING) for
operators who know what they're doing.

Escape hatches preserved from the pre-T7 helper:

* ``--print-sql`` emits an ``INSERT ... ON CONFLICT`` template for the
  Supabase SQL editor (no network).
* ``--copy-to`` / probe-based file copy keeps the byte-preserved file handoff
  for reigh-app's file-based demo dirs.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from ....timeline import Timeline


DEFAULT_REIGH_APP = Path("/Users/peteromalley/Documents/reigh-workspace/reigh-app")
PROBE_DIRS = ("public/timelines", "public/demos", "timelines", "demos")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Push hype.timeline.json + hype.assets.json into reigh-app via SupabaseDataProvider.",
        epilog=(
            "Default flow writes to public.timelines via the user-PAT auth path through "
            "SupabaseDataProvider.save_timeline. --print-sql and --copy-to are escape hatches: "
            "they skip the network entirely and emit a SQL template / byte-preserved file copies."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", type=Path, required=True, help="Directory containing hype.timeline.json and hype.assets.json.")
    parser.add_argument("--timeline-id", required=True, help="UUID for public.timelines.id.")
    parser.add_argument("--project-id", help="reigh-app project UUID. Required for the default DataProvider push (skipped for --print-sql / --copy-to / --copy-files).")
    parser.add_argument("--reigh-app", type=Path, default=DEFAULT_REIGH_APP, help=f"Path to the reigh-app checkout for --copy-files probing. Default: {DEFAULT_REIGH_APP}")
    parser.add_argument("--copy-to", type=Path, help="Byte-preserved file copy: copy the JSON files into this directory.")
    parser.add_argument("--copy-files", action="store_true", help="Probe reigh-app for a file-based demo dir and copy hype.timeline.json/hype.assets.json there.")
    parser.add_argument("--name", default="hype", help="Name used when probing a file-based demo folder.")
    parser.add_argument("--print-sql", action="store_true", help="Print an UPSERT template for public.timelines instead of pushing via the DataProvider.")
    parser.add_argument("--dry-run", action="store_true", help="Show the intended action without writing files or making network calls.")
    parser.add_argument("--force", action="store_true", help="Skip optimistic-version check (logged WARNING).")
    parser.add_argument("--service-role", action="store_true", help="Worker-only escape hatch: authenticate via REIGH_SUPABASE_SERVICE_ROLE_KEY instead of REIGH_PAT. Avoid for ownership-bound CLI calls.")
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


def print_manual_handoff():
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


def push_via_data_provider(args, timeline_path):
    """Default flow: SupabaseDataProvider.save_timeline with the local timeline as mutator output."""

    if not args.project_id:
        print(
            "open_in_reigh: --project-id is required for the default DataProvider push. "
            "Use --print-sql, --copy-to, or --copy-files to skip the network.",
            file=sys.stderr,
        )
        return 2

    new_timeline = load_timeline_blob(timeline_path)
    if not isinstance(new_timeline, dict):
        print("open_in_reigh: timeline JSON must be a JSON object", file=sys.stderr)
        return 2
    if "placements" in new_timeline:
        # Pre-T10 placement-schema timelines are no longer pushable via the
        # DataProvider; reigh-app's `timelines.config` column expects the
        # canonical clip-shaped TimelineConfig. Reject early with a clear
        # diagnostic instead of letting validate_timeline emit a generic error.
        print(
            "open_in_reigh: refusing to push placement-style timeline.json to reigh-app. "
            "The DataProvider expects the canonical clip-shaped TimelineConfig "
            "(per @banodoco/timeline-schema). Re-export with the collapsed schema first.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(
            f"Would push timeline_id={args.timeline_id} project_id={args.project_id} via "
            f"{'service-role' if args.service_role else 'user PAT'} auth"
        )
        return 0

    from artagents.core.reigh import env as reigh_env
    from artagents.core.reigh.data_provider import SupabaseDataProvider

    provider = SupabaseDataProvider.from_env()

    if args.service_role:
        auth = ("service_role", reigh_env.resolve_service_role_key())
    else:
        auth = ("pat", reigh_env.resolve_pat())

    def mutator(_current, _version):
        return new_timeline

    result = provider.save_timeline(
        args.timeline_id,
        mutator,
        project_id=args.project_id,
        auth=auth,
        expected_version=None if args.force else 0,
        retries=3,
        force=bool(args.force),
    )
    print(
        f"Pushed timeline {args.timeline_id} (project_id={args.project_id}, "
        f"new_version={result.new_version}, attempts={result.attempts})"
    )
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    timeline_path, assets_path = source_paths(args.out)
    if timeline_path is None or assets_path is None:
        return 1

    # Escape hatches: --print-sql and --copy-to / --copy-files / probe.
    handled_offline = False
    if args.copy_to is not None or args.copy_files:
        target = probe_target(args)
        if target is not None:
            maybe_copy_files(timeline_path, assets_path, target, args.dry_run)
            handled_offline = True
        elif args.copy_to is not None:
            # User asked for a copy but the dir wasn't writable (probe_target only
            # returns None when --copy-to is missing AND no probe match found).
            handled_offline = True
        else:
            print_manual_handoff()
            handled_offline = True

    if args.print_sql:
        print_sql(args, timeline_path, assets_path)
        handled_offline = True

    if handled_offline:
        return 0

    return push_via_data_provider(args, timeline_path)


if __name__ == "__main__":
    raise SystemExit(main())
