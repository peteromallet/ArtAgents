"""CLI for Astrid thread state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from astrid._paths import REPO_ROOT

from .attribute import archive_thread, backfill_runs, create_thread, enforce_lifecycle, reopen_thread, resolve_thread_ref
from .index import ThreadIndexStore
from .variants import SELECTION_SENTENCE, VariantState, keep_selection, read_current_keepers, selection_history


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    repo_root = _repo_root()
    if args.command == "new":
        return _new(repo_root, args)
    if args.command == "list":
        return _list(repo_root, args)
    if args.command == "show":
        return _show(repo_root, args)
    if args.command == "archive":
        return _archive(repo_root, args)
    if args.command == "reopen":
        return _reopen(repo_root, args)
    if args.command == "backfill":
        return _backfill(repo_root, args)
    if args.command == "keep":
        return _keep(repo_root, args)
    if args.command == "dismiss":
        return _dismiss(repo_root, args)
    if args.command == "group":
        return _group(repo_root, args)
    parser.print_help()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m astrid thread")
    sub = parser.add_subparsers(dest="command")
    new = sub.add_parser("new", help="create and activate a thread")
    new.add_argument("label", nargs="?", default="Astrid thread")
    listed = sub.add_parser("list", help="list threads")
    listed.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="show one thread")
    show.add_argument("thread")
    show.add_argument("--json", action="store_true")
    show.add_argument("--no-content", action="store_true")
    archive = sub.add_parser("archive", help="archive a thread")
    archive.add_argument("thread")
    reopen = sub.add_parser("reopen", help="reopen a thread")
    reopen.add_argument("thread")
    backfill = sub.add_parser("backfill", help="index existing runs without moving files")
    backfill.add_argument("--dry-run", action="store_true")
    keep = sub.add_parser(
        "keep",
        help="record a variant selection",
        epilog=SELECTION_SENTENCE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    keep.add_argument("selection", help="Selection like <run-id>:<n>[,<n>] or <run-id>:none")
    keep.add_argument("--thread", default="@active", help="Thread id or @active")
    dismiss = sub.add_parser(
        "dismiss",
        help="dismiss a variant selection",
        epilog=SELECTION_SENTENCE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dismiss.add_argument("selection", help="Selection like <run-id>:<n>[,<n>] or <run-id>:none")
    dismiss.add_argument("--thread", default="@active", help="Thread id or @active")
    group = sub.add_parser("group", help="inspect variant groups")
    group.add_argument("thread", nargs="?", default="@active")
    group.add_argument("--json", action="store_true")
    return parser


def _new(repo_root: Path, args: argparse.Namespace) -> int:
    thread = create_thread(repo_root, args.label)
    print(f"{thread['thread_id']} {thread['label']}")
    return 0


def _list(repo_root: Path, args: argparse.Namespace) -> int:
    index = enforce_lifecycle(repo_root)
    rows = [_thread_summary(thread, active=index.get("active_thread_id") == thread_id) for thread_id, thread in sorted(index["threads"].items())]
    if args.json:
        print(json.dumps({"schema_version": 1, "active_thread_id": index.get("active_thread_id"), "threads": rows}, indent=2, sort_keys=True))
        return 0
    for row in rows:
        marker = "*" if row["active"] else " "
        print(f"{marker} {row['thread_id']} {row['status']} runs={row['run_count']} {row['label']}")
    return 0


def _show(repo_root: Path, args: argparse.Namespace) -> int:
    try:
        thread_id = resolve_thread_ref(repo_root, args.thread)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    index = ThreadIndexStore(repo_root).read()
    thread = index["threads"][thread_id]
    runs = [_load_run(repo_root, run_id) for run_id in thread.get("run_ids", [])]
    payload = {"thread": thread, "runs": [run for run in runs if run is not None]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"Thread: {thread['label']}")
    print(f"ID: {thread['thread_id']}")
    print(f"Status: {thread['status']}")
    print(f"Runs: {len(thread.get('run_ids', []))}")
    for run in payload["runs"]:
        print(f"- {run['run_id']} {run.get('status')} {run.get('out_path')}")
        if not args.no_content:
            if run.get("brief_content_sha256"):
                print(f"  brief_sha256: {run['brief_content_sha256']}")
            for artifact in run.get("output_artifacts", []):
                print(f"  output: {artifact.get('kind', 'artifact')} {artifact.get('path') or artifact.get('label') or artifact.get('sha256')}")
    return 0


def _archive(repo_root: Path, args: argparse.Namespace) -> int:
    thread = archive_thread(repo_root, args.thread)
    print(f"archived {thread['thread_id']}")
    return 0


def _reopen(repo_root: Path, args: argparse.Namespace) -> int:
    thread = reopen_thread(repo_root, args.thread)
    print(f"reopened {thread['thread_id']}")
    return 0


def _backfill(repo_root: Path, args: argparse.Namespace) -> int:
    if args.dry_run:
        print("dry-run: backfill scans runs/ and records index entries without moving files")
        return 0
    summary = backfill_runs(repo_root)
    print(f"backfilled run_records={summary['run_records']} threads_created={summary['threads_created']} paths_recorded={summary['paths_recorded']}")
    return 0


def _keep(repo_root: Path, args: argparse.Namespace) -> int:
    thread_id = resolve_thread_ref(repo_root, args.thread)
    result = keep_selection(repo_root, thread_id, args.selection, action="keep")
    print(f"kept selections={len(result['records'])}")
    return 0


def _dismiss(repo_root: Path, args: argparse.Namespace) -> int:
    thread_id = resolve_thread_ref(repo_root, args.thread)
    result = keep_selection(repo_root, thread_id, args.selection, action="dismiss")
    print(f"dismissed selections={len(result['records'])}")
    return 0


def _group(repo_root: Path, args: argparse.Namespace) -> int:
    thread_id = resolve_thread_ref(repo_root, args.thread)
    groups = VariantState(repo_root, thread_id).read_groups()
    keepers = read_current_keepers(repo_root, thread_id)
    history = selection_history(repo_root, thread_id)
    payload = {"groups": groups, "keepers": keepers, "selection_history_count": len(history)}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for group_id, group in sorted(groups.get("groups", {}).items()):
        status = "resolved" if group.get("resolved") else "unresolved"
        print(f"{group_id} {status} variants={len(group.get('artifacts', []))} keepers={len(keepers.get(group_id, []))}")
    return 0


def _thread_summary(thread: dict[str, Any], *, active: bool) -> dict[str, Any]:
    return {
        "thread_id": thread["thread_id"],
        "label": thread["label"],
        "status": thread["status"],
        "run_count": len(thread.get("run_ids", [])),
        "active": active,
        "created_at": thread.get("created_at"),
        "updated_at": thread.get("updated_at"),
        "archived_at": thread.get("archived_at"),
    }


def _load_run(repo_root: Path, run_id: str) -> dict[str, Any] | None:
    runs_root = repo_root / "runs"
    for run_json in runs_root.glob("*/run.json"):
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("run_id") == run_id:
            return data
    return None


def _repo_root() -> Path:
    return Path(os.environ.get("ARTAGENTS_REPO_ROOT", REPO_ROOT)).expanduser().resolve()
