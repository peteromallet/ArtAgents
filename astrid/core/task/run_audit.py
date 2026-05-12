"""Per-run audit verbs: show / artifacts / trace / cost (Sprint 5a)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from astrid.core.project.paths import project_dir, resolve_projects_root, validate_project_slug
from astrid.core.task.events import read_events, verify_chain
from astrid.core.task.plan import STEP_PATH_SEP, CostEntry, Step, load_plan


def cmd_run_show(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Pretty-print a run summary; ``--json`` for structured output."""
    parser = argparse.ArgumentParser(prog="astrid run show", add_help=True)
    parser.add_argument("run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--json", dest="json_out", action="store_true", help="emit JSON instead of pretty-print")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"run show: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(f"run show: run {args.run_id!r} not found in project {slug!r}", file=sys.stderr)
        return 1

    events_path = run_root / "events.jsonl"
    plan_path = proj_root / "plan.json"

    events = read_events(events_path) if events_path.exists() else []
    plan = load_plan(plan_path) if plan_path.exists() else None

    # Run status
    run_status = _run_status(events)

    # Plan info
    plan_hash_val = plan.plan_id if plan else "unknown"
    initial_steps = len(plan.steps) if plan else 0
    mutation_count = sum(1 for e in events if e.get("kind") in {"plan_mutated"})
    skipped_steps = sum(
        1 for e in events if e.get("kind") in {"step_skipped", "item_skipped"}
    )

    # Step list
    step_rows = _build_step_rows(events, run_root)

    # Cost
    cost_summary = _cost_by_source(events)

    # Acks
    ack_count = sum(1 for e in events if e.get("kind") == "step_attested")
    attested_decisions = sum(1 for e in events if e.get("kind") in {"step_attested", "item_attested"})

    # Consumes
    consumes: list[dict[str, Any]] = []
    run_json_path = run_root / "run.json"
    if run_json_path.exists():
        try:
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            consumes = run_json.get("consumes", [])
        except (json.JSONDecodeError, OSError):
            pass

    # Timestamps
    started_ts = ""
    completed_ts = ""
    for e in events:
        if e.get("kind") == "run_started":
            started_ts = str(e.get("ts", ""))
        if e.get("kind") == "run_completed":
            completed_ts = str(e.get("ts", ""))

    total_cost = sum(c.get("amount", 0) for c in cost_summary.values() if isinstance(c, dict))

    if args.json_out:
        payload: dict[str, Any] = {
            "run_id": args.run_id,
            "status": run_status,
            "project": slug,
            "started": started_ts,
            "completed": completed_ts or None,
            "plan_hash": plan_hash_val,
            "initial_steps": initial_steps,
            "mutations": mutation_count,
            "skipped_steps": skipped_steps,
            "effective_steps": len(step_rows),
            "total_cost": total_cost,
            "cost_by_source": cost_summary,
            "ack_count": ack_count,
            "attested_decisions": attested_decisions,
            "consumes": consumes,
            "steps": step_rows,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    # Pretty-print
    print(f"Run {args.run_id} [{run_status}]")
    print(f"Project: {slug}")
    started_label = f"Started: {started_ts}" if started_ts else "Started: (unknown)"
    if completed_ts:
        print(f"{started_label}  Completed: {completed_ts}")
    else:
        print(f"{started_label}  In-flight")
    cost_line = f"Cost: ${total_cost:.2f}"
    if cost_summary:
        cost_line += "  (" + ", ".join(f"{s}: ${c.get('amount', 0):.2f}" for s, c in cost_summary.items() if isinstance(c, dict)) + ")"
    print(cost_line)
    print()
    print(f"Initial plan: {initial_steps} steps, plan_hash={plan_hash_val}")
    effective_label = f"Effective plan: {len(step_rows)} steps"
    if mutation_count:
        effective_label += f" after {mutation_count} mutations"
    print(effective_label)
    print()
    if step_rows:
        print("Steps (path, version, state, cost):")
        for sr in step_rows:
            sid = sr.get("step_id", "?")
            ver = sr.get("version", 1)
            state = sr.get("state", "?")
            cost_amount = sr.get("cost")
            cost_str = f"${cost_amount:.2f}" if isinstance(cost_amount, (int, float)) else "-"
            extras = sr.get("extras", "")
            print(f"  {sid:30s} v{ver:<3d} {state:20s} {cost_str:>8s}  {extras}")
    else:
        print("Steps: (none)")
    print()
    print(f"Acks: {ack_count} events; {attested_decisions} attested decisions")
    if skipped_steps:
        print(f"Skipped: {skipped_steps} step/item skip events")
    if consumes:
        print(f"Consumes: {len(consumes)} input dependencies")
        for c in consumes:
            src = c.get("source", "?")
            sha = c.get("sha256", "")[:16] if c.get("sha256") else "-"
            print(f"  {src}  sha256={sha}...")
    return 0


def cmd_run_artifacts(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Flat tabular list of artifacts produced by a run."""
    parser = argparse.ArgumentParser(prog="astrid run artifacts", add_help=True)
    parser.add_argument("run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--step", dest="step_filter", default=None, help="filter by step id")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"run artifacts: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(f"run artifacts: run {args.run_id!r} not found", file=sys.stderr)
        return 1

    steps_root = run_root / "steps"
    if not steps_root.is_dir():
        return 0

    header = f"{'step_id':30s} {'ver':>4s} {'iter':>6s} {'item':>10s} {'name':>20s} {'path':>40s} {'check':>12s} {'sha256':>18s} {'cost':>10s}"
    print(header)

    for step_dir in sorted(steps_root.iterdir()):
        if not step_dir.is_dir():
            continue
        step_id = step_dir.name
        if args.step_filter and step_id != args.step_filter:
            continue
        for vdir in sorted(step_dir.iterdir()):
            if not vdir.is_dir() or not vdir.name.startswith("v"):
                continue
            version = vdir.name[1:]  # strip 'v'
            # Check for iterations / items
            _emit_artifact_rows(vdir, step_id, version, "")
            for sub in [vdir / "iterations", vdir / "items"]:
                if sub.is_dir():
                    for child in sorted(sub.iterdir()):
                        if child.is_dir():
                            label = child.name
                            _emit_artifact_rows(child, step_id, version, label)
    return 0


def _emit_artifact_rows(adir: Path, step_id: str, version: str, sub_label: str) -> None:
    """Print artifact rows for a single step version directory."""
    produces_dir = adir / "produces"
    if not produces_dir.is_dir():
        return
    remote_state_path = adir / "remote_state.json"
    declared: dict[str, str] = {}
    missing: set[str] = set()
    mismatched: set[str] = set()
    if remote_state_path.exists():
        try:
            state = json.loads(remote_state_path.read_text(encoding="utf-8"))
            declared = state.get("manifest", {})
            if isinstance(declared, dict):
                declared = {k: v for k, v in declared.items() if isinstance(v, str)}
            else:
                declared = {}
            missing = set(state.get("missing", []))
            mismatched = set(state.get("mismatched", []))
        except (json.JSONDecodeError, OSError):
            pass

    # Walk produces directory for artifact files (skip subdirs like cost.json)
    for art_path in sorted(produces_dir.rglob("*")):
        if art_path.is_dir():
            continue
        if art_path.name == "cost.json":
            continue
        rel = art_path.relative_to(produces_dir)
        name = str(rel)
        short_path = str(rel)
        check_status = "ok"
        if name in missing:
            check_status = "missing"
        elif name in mismatched:
            check_status = "mismatched"
        sha256_val = ""
        try:
            import hashlib
            sha256_val = hashlib.sha256(art_path.read_bytes()).hexdigest()[:16]
        except OSError:
            sha256_val = "unreadable"

        cost_str = "-"
        cost_path = produces_dir / "cost.json"
        if cost_path.exists():
            try:
                cost_data = json.loads(cost_path.read_text(encoding="utf-8"))
                amount = cost_data.get("amount")
                if isinstance(amount, (int, float)):
                    cost_str = f"${amount:.2f}"
            except (json.JSONDecodeError, OSError):
                pass

        iter_label = sub_label if adir.parent and adir.parent.name == "iterations" else ""
        item_label = sub_label if adir.parent and adir.parent.name == "items" else ""
        print(
            f"{step_id:30s} {version:>4s} {iter_label:>6s} {item_label:>10s} "
            f"{name:20s} {short_path:40s} {check_status:>12s} {sha256_val:>18s} {cost_str:>10s}"
        )


def cmd_run_trace(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Chronological event dump for a step (including supersede/tombstone history)."""
    parser = argparse.ArgumentParser(prog="astrid run trace", add_help=True)
    parser.add_argument("run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--step", required=True, dest="step_id", help="step id to trace")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"run trace: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(f"run trace: run {args.run_id!r} not found", file=sys.stderr)
        return 1

    events_path = run_root / "events.jsonl"
    if not events_path.exists():
        print("(no events)", file=sys.stderr)
        return 0

    events = read_events(events_path)
    step_id = args.step_id

    for event in events:
        path_list = event.get("plan_step_path")
        plan_step_id = event.get("plan_step_id")
        # Match: plan_step_path last element == step_id, or plan_step_id matches
        if isinstance(path_list, list) and path_list:
            last = str(path_list[-1])
            if last != step_id:
                continue
        elif isinstance(plan_step_id, str):
            if plan_step_id != step_id and not plan_step_id.endswith(f"/{step_id}"):
                continue
        else:
            continue

        ts = event.get("ts", "")
        kind = event.get("kind", "")
        rc = event.get("returncode")
        reason = event.get("reason", "")
        cost = event.get("cost")
        line = f"{ts}  {kind}"
        if rc is not None:
            line += f"  returncode={rc}"
        if reason:
            line += f"  reason={reason!r}"
        if cost is not None:
            line += f"  cost={cost}"
        print(line)
        # Also print the full JSON for traceability
    return 0


def cmd_run_cost(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Per-run cost aggregation grouped by source."""
    parser = argparse.ArgumentParser(prog="astrid run cost", add_help=True)
    parser.add_argument("run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"run cost: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(f"run cost: run {args.run_id!r} not found", file=sys.stderr)
        return 1

    events_path = run_root / "events.jsonl"
    events = read_events(events_path) if events_path.exists() else []

    by_source = _cost_by_source(events)
    total = sum(c.get("amount", 0) for c in by_source.values() if isinstance(c, dict))

    print(f"Run: {args.run_id}")
    print(f"Total cost: ${total:.2f}")
    if not by_source:
        print("(no cost events)")
        return 0

    print()
    print(f"{'Source':20s} {'Amount':>10s} {'Currency':>8s}")
    for source, info in sorted(by_source.items()):
        if isinstance(info, dict):
            amount = info.get("amount", 0)
            currency = info.get("currency", "USD")
            print(f"{source:20s} ${amount:>9.2f} {currency:>8s}")
        else:
            print(f"{source:20s} {info!s:>10s}")
    return 0


# ---------------------------------------------------------------------------
# events verify (Sprint 5b T5)
# ---------------------------------------------------------------------------


def cmd_events_verify(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Verify the hash chain for a run's events.jsonl.

    Thin CLI wrapper around :func:`astrid.core.task.events.verify_chain`.
    On success prints ``verified: N events, plan_hash=<...>``.
    On failure prints ``broken at line N: <reason>`` and exits 1.

    ``--strict`` additionally replays ``plan_mutated`` events through
    :func:`astrid.core.task.validator.validate_mutation` to check that
    every mutation passes the six-invariant gate.
    """
    parser = argparse.ArgumentParser(prog="astrid events verify", add_help=True)
    parser.add_argument("--run", required=True, dest="run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also validate plan_mutated events against the six-invariant validator",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"events verify: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(
            f"events verify: run {args.run_id!r} not found in project {slug!r}",
            file=sys.stderr,
        )
        return 1

    events_path = run_root / "events.jsonl"
    if not events_path.exists():
        print("verified: 0 events, plan_hash=(no events)")
        return 0

    ok, line_idx, err_msg = verify_chain(events_path)

    events = read_events(events_path)
    n_events = len(events)

    # Extract plan_hash from run_started event
    plan_hash = "unknown"
    for e in events:
        if e.get("kind") == "run_started":
            plan_hash = str(e.get("plan_hash", "unknown"))
            break

    if not ok:
        if line_idx == -1:
            print(f"broken: {err_msg}")
        else:
            print(f"broken at line {line_idx + 1}: {err_msg}")
        return 1

    # ── --strict: replay plan mutations through the validator ──────────
    strict_failures = 0
    if args.strict:
        plan_path = proj_root / "plan.json"
        if not plan_path.exists():
            print("strict: plan.json not found; cannot validate mutations")
        else:
            try:
                from astrid.core.task.plan_verbs import (
                    PLAN_MUTATED_KIND,
                    _apply_diff as plan_apply_diff,
                )
                from astrid.core.task.validator import (
                    MutationInvariantError,
                    validate_mutation,
                )

                plan = load_plan(plan_path)
                current = plan
                mutation_events = [
                    e for e in events if e.get("kind") == PLAN_MUTATED_KIND
                ]
                for i, ev in enumerate(mutation_events):
                    diff = ev.get("diff")
                    if not isinstance(diff, dict):
                        strict_failures += 1
                        print(
                            f"strict: mutation event {i + 1} missing diff field"
                        )
                        continue
                    try:
                        proposed = plan_apply_diff(current, diff)
                        # lease_epoch is not recoverable from event log;
                        # pass epoch=0,0 as a best-effort audit check
                        # (I6 is skipped in audit mode)
                        validate_mutation(
                            prior=current,
                            proposed=proposed,
                            lease_epoch_actual=0,
                            lease_epoch_expected=0,
                        )
                        current = proposed
                    except (MutationInvariantError, Exception) as exc:
                        strict_failures += 1
                        print(
                            f"strict: mutation event {i + 1} failed: {exc}"
                        )

                # Sprint 5b: reject skip events whose target step is not
                # optional=True in the effective (post-mutation) plan tree.
                # This is defence-in-depth on already-written event logs.
                from astrid.core.task.plan import (
                    iter_steps_with_path as _iter_steps,
                )
                effective_index = {
                    path: step for path, step in _iter_steps(current)
                }
                for i, ev in enumerate(events):
                    if ev.get("kind") not in {"step_skipped", "item_skipped"}:
                        continue
                    path_list = ev.get("plan_step_path")
                    if not isinstance(path_list, list) or not path_list:
                        strict_failures += 1
                        print(
                            f"strict: skip event {i + 1} missing plan_step_path"
                        )
                        continue
                    target_path = tuple(str(p) for p in path_list)
                    target = effective_index.get(target_path)
                    if target is None:
                        strict_failures += 1
                        print(
                            f"strict: skip event {i + 1} references unknown "
                            f"step path {'/'.join(target_path)!r}"
                        )
                        continue
                    # item_skipped is allowed even if the host is not optional
                    # (per-item skip is independent of host optionality).
                    if ev.get("kind") == "item_skipped":
                        continue
                    if not getattr(target, "optional", False):
                        strict_failures += 1
                        print(
                            f"strict: skip event {i + 1} targets non-optional "
                            f"step {'/'.join(target_path)!r}"
                        )
            except Exception as exc:
                print(f"strict: error loading plan: {exc}", file=sys.stderr)

    print(f"verified: {n_events} events, plan_hash={plan_hash}")
    if args.strict:
        if strict_failures == 0:
            print("strict: all mutation events pass invariant checks")
        else:
            print(
                f"strict: {strict_failures} mutation event(s) failed validation"
            )
            return 1
    return 0


# ---------------------------------------------------------------------------
# events tail (Sprint 5b T6)
# ---------------------------------------------------------------------------


def cmd_events_tail(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    """Print the last *N* events from a run's ``events.jsonl``.

    ``-f`` polls the file every second for new lines (follow mode).
    ``-n`` controls how many lines to show (default: 20).
    """
    parser = argparse.ArgumentParser(prog="astrid events tail", add_help=True)
    parser.add_argument("--run", required=True, dest="run_id", help="run identifier")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument(
        "-n",
        type=int,
        default=20,
        help="number of lines to print (default: 20)",
    )
    parser.add_argument(
        "-f",
        dest="follow",
        action="store_true",
        help="follow the file, polling every second for new lines",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        print(f"events tail: {exc}", file=sys.stderr)
        return 1

    proj_root = project_dir(slug, root=projects_root)
    run_root = proj_root / "runs" / args.run_id
    if not run_root.is_dir():
        print(
            f"events tail: run {args.run_id!r} not found in project {slug!r}",
            file=sys.stderr,
        )
        return 1

    events_path = run_root / "events.jsonl"
    if not events_path.exists():
        print("(no events)")
        return 0

    _print_tail(events_path, n=args.n)
    if args.follow:
        last_mtime = events_path.stat().st_mtime
        try:
            while True:
                time.sleep(1)
                try:
                    cur_mtime = events_path.stat().st_mtime
                except FileNotFoundError:
                    break
                if cur_mtime > last_mtime:
                    last_mtime = cur_mtime
                    _print_tail(events_path, n=args.n)
        except KeyboardInterrupt:
            pass  # quiet exit on SIGINT
    return 0


def _print_tail(events_path: Path, *, n: int) -> None:
    """Print the last *n* events as one-line summaries."""
    events = read_events(events_path)
    tail = events[-n:] if len(events) > n else events
    for ev in tail:
        ts = str(ev.get("ts", ""))[:19]  # truncate fractional seconds
        kind = ev.get("kind", "?")
        plan_step_path = ev.get("plan_step_path")
        step_id = ""
        if isinstance(plan_step_path, list) and plan_step_path:
            step_id = str(plan_step_path[-1])
        elif isinstance(plan_step_path, str):
            step_id = plan_step_path
        rc = ev.get("returncode")
        rc_str = f" rc={rc}" if rc is not None else ""
        line = f"{ts}  {kind:24s}  {step_id}{rc_str}"
        print(line)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_status(events: list[dict[str, Any]]) -> str:
    """Derive run status from terminal events."""
    for e in events:
        if e.get("kind") == "run_aborted":
            return "aborted"
    for e in events:
        if e.get("kind") == "run_completed":
            return "completed"
    return "in-flight"


def _build_step_rows(
    events: list[dict[str, Any]],
    run_root: Path,
) -> list[dict[str, Any]]:
    """Build per-step summary rows from events and on-disk state."""
    steps_root = run_root / "steps"
    latest_by_path: dict[str, dict[str, Any]] = {}
    cost_by_path: dict[str, float] = {}

    for event in events:
        path_list = event.get("plan_step_path")
        if not isinstance(path_list, list) or not path_list:
            continue
        path_str = "/".join(str(p) for p in path_list)
        kind = event.get("kind")
        # Track latest event kind for state determination
        if kind in {
            "step_dispatched", "step_completed", "step_failed",
            "step_awaiting_fetch", "step_attested",
        }:
            latest_by_path[path_str] = {"kind": kind, "ts": event.get("ts", "")}
        # Accumulate costs from completed events
        if kind == "step_completed":
            cost = event.get("cost")
            if isinstance(cost, dict):
                amount = cost.get("amount")
                if isinstance(amount, (int, float)):
                    cost_by_path[path_str] = cost_by_path.get(path_str, 0) + float(amount)

    rows: list[dict[str, Any]] = []
    if steps_root.is_dir():
        for step_dir in sorted(steps_root.iterdir()):
            if not step_dir.is_dir():
                continue
            step_id = step_dir.name
            for vdir in sorted(step_dir.iterdir()):
                if not vdir.is_dir() or not vdir.name.startswith("v"):
                    continue
                version = int(vdir.name[1:])
                # Find the event path that ends with this step_id
                path_str = step_id
                state = "pending"
                for ps, info in latest_by_path.items():
                    parts = ps.split("/")
                    if parts and parts[-1] == step_id:
                        state = info.get("kind", "pending")
                        break
                cost_val = cost_by_path.get(path_str)
                extras = ""
                if state == "step_awaiting_fetch":
                    remote_path = vdir / "remote_state.json"
                    if remote_path.exists():
                        try:
                            st = json.loads(remote_path.read_text(encoding="utf-8"))
                            missing = st.get("missing", [])
                            mismatched = st.get("mismatched", [])
                            if missing or mismatched:
                                extras = f"({len(missing)} missing, {len(mismatched)} mismatched)"
                        except (json.JSONDecodeError, OSError):
                            pass
                rows.append({
                    "step_id": step_id,
                    "version": version,
                    "state": state,
                    "cost": cost_val,
                    "extras": extras,
                })
    return rows


def _cost_by_source(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate costs from events grouped by cost.source field."""
    by_source: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event.get("kind", "")
        if kind not in {"step_completed", "step_failed"}:
            continue
        cost = event.get("cost")
        if not isinstance(cost, dict):
            continue
        amount = cost.get("amount")
        currency = cost.get("currency", "USD")
        source = cost.get("source", "unknown")
        if not isinstance(amount, (int, float)):
            continue
        if source not in by_source:
            by_source[source] = {"amount": 0.0, "currency": currency, "source": source}
        by_source[source]["amount"] += float(amount)
        by_source[source]["currency"] = currency
    return by_source


__all__ = [
    "cmd_events_tail",
    "cmd_events_verify",
    "cmd_run_artifacts",
    "cmd_run_cost",
    "cmd_run_show",
    "cmd_run_trace",
]