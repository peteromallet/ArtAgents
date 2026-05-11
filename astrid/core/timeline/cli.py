"""Command-line interface for Astrid timelines (Sprint 2)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from astrid.core.project.current_run import read_current_run
from astrid.core.session.binding import (
    SessionBindingError,
    resolve_current_session,
)

from . import crud
from .defaults import read_project_default, write_project_default
from .integrity import verify

_SESSION_GATE_HINT = (
    "A timeline command requires a bound session. "
    "Run 'astrid attach <project>' first."
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (crud.TimelineCrudError, SessionBindingError) as exc:
        print(f"timelines: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"timelines: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid timelines",
        description="Create, inspect, and manage project timelines.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- ls ---
    ls_parser = subparsers.add_parser("ls", help="List timelines in the current project.")
    ls_parser.add_argument(
        "--project",
        help="Project slug (required when no session is bound).",
    )
    ls_parser.set_defaults(handler=cmd_ls)

    # --- create ---
    create_parser = subparsers.add_parser("create", help="Create a timeline.")
    create_parser.add_argument("slug", help="Timeline slug (lowercase, letters/digits/hyphens).")
    create_parser.add_argument("--name", help="Human-readable name (defaults to slug).")
    create_parser.add_argument(
        "--default",
        action="store_true",
        dest="is_default",
        help="Set as the project default timeline.",
    )
    create_parser.set_defaults(handler=cmd_create)

    # --- show ---
    show_parser = subparsers.add_parser("show", help="Show a timeline.")
    show_parser.add_argument("slug", help="Timeline slug.")
    show_parser.add_argument(
        "--verify",
        action="store_true",
        help="Recompute integrity (sha256) for each final output.",
    )
    show_parser.set_defaults(handler=cmd_show)

    # --- rename ---
    rename_parser = subparsers.add_parser("rename", help="Rename a timeline slug.")
    rename_parser.add_argument("old_slug", metavar="slug", help="Current timeline slug.")
    rename_parser.add_argument("new_slug", metavar="new-slug", help="New timeline slug.")
    rename_parser.set_defaults(handler=cmd_rename)

    # --- finalize ---
    finalize_parser = subparsers.add_parser(
        "finalize", help="Record a final output with sha256 integrity."
    )
    finalize_parser.add_argument("slug", help="Timeline slug.")
    finalize_parser.add_argument("--output", required=True, help="Path to the output file.")
    finalize_parser.add_argument("--kind", default="unknown", help="Free-text output kind (mp4, transcript, etc.).")
    finalize_parser.add_argument(
        "--from-run",
        help="Run ID this output originates from (defaults to the current run).",
    )
    finalize_parser.add_argument(
        "--recorded-by", default="agent:cli", help="Agent identifier."
    )
    finalize_parser.set_defaults(handler=cmd_finalize)

    # --- tombstone ---
    tombstone_parser = subparsers.add_parser(
        "tombstone", help="Soft-delete a timeline (marks tombstoned, leaves files)."
    )
    tombstone_parser.add_argument("slug", help="Timeline slug.")
    tombstone_parser.set_defaults(handler=cmd_tombstone)

    # --- purge ---
    purge_parser = subparsers.add_parser(
        "purge", help="Hard-delete a timeline directory tree."
    )
    purge_parser.add_argument("slug", help="Timeline slug.")
    purge_parser.add_argument(
        "--yes-really",
        action="store_true",
        help="Confirm you really want to delete this timeline permanently.",
    )
    purge_parser.set_defaults(handler=cmd_purge)

    # --- set-default ---
    set_default_parser = subparsers.add_parser(
        "set-default", help="Set a timeline as the project default."
    )
    set_default_parser.add_argument("slug", help="Timeline slug.")
    set_default_parser.set_defaults(handler=cmd_set_default)

    return parser


# ---------------------------------------------------------------------------
# Handler: ls
# ---------------------------------------------------------------------------


def cmd_ls(args: argparse.Namespace) -> int:
    session = resolve_current_session()
    project_slug = args.project

    if session is not None:
        project_slug = project_slug or session.project
    if not project_slug:
        print(
            "timelines: no project specified; use --project <slug> or bind a session with 'astrid attach'",
            file=sys.stderr,
        )
        return 2

    rows = crud.list_timelines(project_slug)
    if not rows:
        print(f"(no timelines in project '{project_slug}')")
        return 0

    # Table header.
    print(f"{'SLUG':<20} {'NAME':<24} {'DEFAULT':<8} {'RUNS':>5} {'LAST FINALIZED':<20}")
    print("-" * 80)
    for row in rows:
        default_marker = "*" if row.is_default else ""
        last = row.last_finalized or "-"
        print(
            f"{row.slug:<20} {row.name:<24} {default_marker:<8} {row.run_count:>5} {last:<20}"
        )

    return 0


# ---------------------------------------------------------------------------
# Handler: create
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    session = _require_session()
    result = crud.create_timeline(
        session.project,
        args.slug,
        name=args.name,
        is_default=args.is_default,
    )
    print(f"created timeline '{result['slug']}' (ulid: {result['ulid']})")
    if args.is_default:
        print(f"set as default timeline for project '{session.project}'")
    return 0


# ---------------------------------------------------------------------------
# Handler: show
# ---------------------------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    session = _require_session()
    data = crud.show_timeline(session.project, args.slug)
    if data is None:
        print(f"timeline '{args.slug}' not found", file=sys.stderr)
        return 1

    display = data["display"]
    manifest = data["manifest"]
    assembly = data["assembly"]
    ulid = data["ulid"]

    print(f"Timeline: {display.name}")
    print(f"  slug:      {display.slug}")
    print(f"  ulid:      {ulid}")
    print(f"  default:   {display.is_default}")
    if manifest.tombstoned_at:
        print(f"  tombstoned: {manifest.tombstoned_at}")
    print(f"  contributing runs: {len(manifest.contributing_runs)}")
    print()

    print("Assembly:")
    if assembly.assembly:
        import json

        print(f"  keys: {sorted(assembly.assembly.keys())}")
    else:
        print("  (empty)")
    print()

    print(f"Final outputs ({len(manifest.final_outputs)}):")
    if not manifest.final_outputs:
        print("  (none)")
    else:
        for fo in manifest.final_outputs:
            if args.verify:
                status = verify(fo)
            else:
                status = fo.check_status
            marker = ""
            if status != "ok":
                marker = f"  [{status.upper()}]"
            print(f"  - {fo.kind:<16} {fo.path}")
            print(f"    sha256: {fo.sha256}")
            print(f"    size:   {fo.size} bytes")
            print(f"    status: {status}{marker}")
            print(f"    run:    {fo.from_run}")
            print(f"    at:     {fo.recorded_at}")
            print()

    return 0


# ---------------------------------------------------------------------------
# Handler: rename
# ---------------------------------------------------------------------------


def cmd_rename(args: argparse.Namespace) -> int:
    session = _require_session()
    result = crud.rename_timeline(session.project, args.old_slug, args.new_slug)
    print(f"renamed timeline '{args.old_slug}' -> '{result['slug']}'")
    return 0


# ---------------------------------------------------------------------------
# Handler: finalize
# ---------------------------------------------------------------------------


def cmd_finalize(args: argparse.Namespace) -> int:
    session = _require_session()
    from_run = args.from_run
    if from_run is None:
        from_run = read_current_run(session.project) or ""
        if not from_run:
            print(
                "timelines: no current run bound; pass --from-run explicitly",
                file=sys.stderr,
            )
            return 2

    fo = crud.finalize_output(
        session.project,
        args.slug,
        args.output,
        kind=args.kind,
        from_run=from_run,
        recorded_by=args.recorded_by,
    )
    print(
        f"finalized '{fo.kind}' output for timeline '{args.slug}' "
        f"(sha256: {fo.sha256[:16]}..., size: {fo.size} bytes)"
    )
    return 0


# ---------------------------------------------------------------------------
# Handler: tombstone
# ---------------------------------------------------------------------------


def cmd_tombstone(args: argparse.Namespace) -> int:
    session = _require_session()
    result = crud.tombstone_timeline(session.project, args.slug)
    print(
        f"tombstoned timeline '{result['slug']}' at {result['tombstoned_at']}"
    )
    return 0


# ---------------------------------------------------------------------------
# Handler: purge
# ---------------------------------------------------------------------------


def cmd_purge(args: argparse.Namespace) -> int:
    session = _require_session()

    if not args.yes_really:
        print(
            f"timelines: purge requires --yes-really to permanently delete timeline '{args.slug}'",
            file=sys.stderr,
        )
        return 2

    # Double-confirmation for interactive terminals.
    if sys.stdin.isatty():
        try:
            answer = input(
                f"Permanently delete timeline '{args.slug}'? This cannot be undone. [y/N] "
            )
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            print("timelines: purge cancelled", file=sys.stderr)
            return 2
        if answer.strip().lower() not in ("y", "yes"):
            print("timelines: purge cancelled", file=sys.stderr)
            return 2

    crud.purge_timeline(session.project, args.slug)
    print(f"purged timeline '{args.slug}'")
    return 0


# ---------------------------------------------------------------------------
# Handler: set-default
# ---------------------------------------------------------------------------


def cmd_set_default(args: argparse.Namespace) -> int:
    session = _require_session()
    result = crud.set_default(session.project, args.slug)
    print(
        f"timeline '{result['slug']}' is now the default for project '{session.project}'"
    )
    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_session() -> Any:
    session = resolve_current_session()
    if session is None:
        raise SessionBindingError(_SESSION_GATE_HINT)
    return session