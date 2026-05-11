#!/usr/bin/env python3
"""Read-only scanner that inventories astrid-projects/ file artifacts into a CSV."""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

PROJECTS_ROOT = Path("~/Documents/reigh-workspace/astrid-projects").expanduser()
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "reshape"
CSV_COLUMNS = ["project_slug", "file_kind", "absolute_path", "size_bytes", "modified_at_iso"]

FileKind = str


def _modified_iso(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=UTC).isoformat()


def _scan_project(project_dir: Path) -> list[tuple[str, FileKind, str, int, str]]:
    rows: list[tuple[str, FileKind, str, int, str]] = []
    slug = project_dir.name

    def add(path: Path, kind: FileKind) -> None:
        if path.exists():
            rows.append((slug, kind, str(path), path.stat().st_size, _modified_iso(path)))

    # Project-level files
    add(project_dir / "active_run.json", "active_run")
    add(project_dir / "timeline.json", "project_timeline")

    # .astrid/threads.json
    add(project_dir / ".astrid" / "threads.json", "threads_json")

    # Per-run timelines and plans
    runs_dir = project_dir / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            add(run_dir / "timeline.json", "run_timeline")
            add(run_dir / "plan.json", "run_plan")

    # Threads directories
    for threads_dir in project_dir.glob("**/threads"):
        if threads_dir.is_dir():
            for thread_file in sorted(threads_dir.iterdir()):
                if thread_file.is_file():
                    add(thread_file, "thread_file")

    # thread_*.json files (anywhere under project tree)
    for thread_file in sorted(project_dir.rglob("thread_*.json")):
        # Avoid double-counting files already found under threads/ dirs
        if thread_file.parent.name == "threads":
            continue
        add(thread_file, "thread_file")

    return rows


def main() -> None:
    today = datetime.now(UTC).strftime("%Y%m%d")
    output_path = OUTPUT_DIR / f"inventory-baseline-{today}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not PROJECTS_ROOT.is_dir():
        # Write header-only CSV when source is missing
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(CSV_COLUMNS)
        print(f"Source directory missing; wrote header-only CSV to {output_path}")
        return

    all_rows: list[tuple[str, FileKind, str, int, str]] = []
    for entry in sorted(PROJECTS_ROOT.iterdir()):
        if entry.is_dir():
            all_rows.extend(_scan_project(entry))

    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for row in all_rows:
            writer.writerow(row)

    print(f"Inventory written to {output_path} ({len(all_rows)} artifacts)")


if __name__ == "__main__":
    main()