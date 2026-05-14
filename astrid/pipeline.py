#!/usr/bin/env python3
"""Astrid top-level command gateway.

Sprint 1 wires the session CLI gate: every verb outside the unbound
allowlist requires ``ASTRID_SESSION_ID`` to resolve to a valid session
record. Unbound callers are pointed at ``astrid attach <project>``.

The unbound allowlist mirrors the brief: ``attach``, ``status``,
``projects ls``, ``projects create``, ``sessions ls``,
``sessions takeover``, ``sessions detach``, ``init`` (first-run
bootstrap), and the help flags. ``author test --project <slug>`` is also
a documented exception so workflow tests can run without an operator
session.

Subcommands dispatch to focused module CLIs. Brief / video flags fall
through to the ``builtin.hype`` orchestrator resolved through the
orchestrator registry.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable


# Phase 5 lifecycle verbs short-circuit the implicit task-mode gate at the top
# of main(): for these verbs the --project flag identifies the run, NOT a
# command to dispatch through plan[cursor]. cmd_ack approve re-enters the gate
# explicitly (see lifecycle_ack._ack_approve), so the short-circuit only
# bypasses the gate's command-match step.
LIFECYCLE_VERBS = {"start", "next", "ack", "skip", "abort", "status", "runs", "hook", "plan", "claim", "unclaim", "step"}


# Sprint 1 session-gate allowlist. A first-token (or two-token) match against
# this set lets the verb run without a bound session. Everything else needs
# ``ASTRID_SESSION_ID`` to resolve to a session record.
_UNBOUND_TOP_LEVEL = {
    "attach",
    "status",
    "sessions",  # sub-verbs handled below
    "init",
    "-h",
    "--help",
}
_UNBOUND_PROJECTS_SUBVERBS = {"ls", "create", "default"}
_UNBOUND_SESSIONS_SUBVERBS = {"ls", "takeover", "detach"}


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] in {"-h", "--help"}:
        _print_entrypoint_help()
        return 0
    # Nudge runs once per CLI invocation, before the command itself, but never
    # for the `skills` subcommand (would be silly) or help. Cheap state-file
    # read; bails early if no harness is detected or ASTRID_NO_NUDGE is set.
    try:
        from .skills import nudge_if_needed

        nudge_if_needed(argv=raw)
    except Exception:
        # Never let the nudge break a real command.
        pass

    # Session gate. Verbs outside the unbound allowlist require a resolvable
    # session record; print the documented hint and exit 2 otherwise.
    if not _verb_is_unbound_allowlisted(raw):
        from .core.session.binding import (
            ASTRID_SESSION_ID_ENV,  # noqa: F401 — referenced in the error path
            SessionBindingError,
            resolve_current_session,
        )

        try:
            session = resolve_current_session()
        except SessionBindingError as exc:
            print(f"session: {exc}", file=sys.stderr)
            return 2
        if session is None:
            project_hint = _extract_project_slug(raw)
            attach_hint = (
                f"`astrid attach {project_hint}`"
                if project_hint
                else "`astrid attach <project>`"
            )
            print(
                f"no session bound — run `astrid status` to list projects, then {attach_hint} "
                "(or `astrid attach` if a default project is configured)",
                file=sys.stderr,
            )
            return 2

    if raw and raw[0] in LIFECYCLE_VERBS:
        return _dispatch(raw)
    project_slug = _extract_project_slug(raw)
    if project_slug is None:
        return _dispatch(raw)

    from .core.task import gate as task_gate

    try:
        decision = task_gate.gate_command(project_slug, task_gate.command_for_argv(raw), raw)
    except task_gate.TaskRunGateError as exc:
        print(f"task-mode gate rejected: {exc.reason}\nrecovery: {exc.recovery}", file=sys.stderr)
        return 1
    if not decision.active:
        return _dispatch(raw)

    returncode = -1
    try:
        # Sprint 3 (T14): adapter-aware dispatch. For code steps with an adapter
        # (local/manual), the adapter's dispatch() was already called inside
        # gate_command.  Skip _dispatch(raw) to avoid double-execution.
        if decision.step_kind == "code" and decision.adapter:
            returncode = _wait_adapter(decision)
        else:
            returncode = _dispatch(raw)
        return returncode
    finally:
        # T9 extends GateDecision with a `.session` field so the post-dispatch
        # record helpers can flow through a fresh WriterContext. Until that
        # lands, guard the wrapper with hasattr() so existing callers that
        # don't carry a session keep working unchanged.
        if hasattr(decision, "session") and getattr(decision, "session", None) is not None:
            from .core.session.writer import writer_context_from_decision

            try:
                with writer_context_from_decision(decision):
                    task_gate.record_dispatch_complete(decision, returncode)
            except Exception:
                # Fall back to the unwrapped path on any writer-auth failure;
                # T9's lifecycle migration is the layer that makes this hard.
                task_gate.record_dispatch_complete(decision, returncode)
        else:
            task_gate.record_dispatch_complete(decision, returncode)


def _verb_is_unbound_allowlisted(raw: list[str]) -> bool:
    """Decide whether the invocation may run without a bound session.

    The allowlist is the canonical Sprint 1 set (brief §CLI gate):

    * ``attach``, ``init``, ``-h`` / ``--help`` (full-verb).
    * ``status`` — both the new session breadcrumb (no ``--project``) and
      the legacy ``astrid status --project <slug>``.
    * ``projects ls``, ``projects create``, and ``projects default``.
    * ``sessions ls`` / ``sessions takeover`` / ``sessions detach``.
    * ``author test --project <slug>`` — documented exception for the
      workflow test runner.
    """

    if not raw:
        return True  # empty argv → entrypoint help

    top = raw[0]
    if "-h" in raw or "--help" in raw:
        return True
    if top in {"attach", "init", "status"}:
        return True
    if top == "projects" and len(raw) >= 2 and raw[1] in _UNBOUND_PROJECTS_SUBVERBS:
        return True
    if top == "timelines" and len(raw) >= 2 and raw[1] == "ls":
        return True
    if top == "sessions" and len(raw) >= 2 and raw[1] in _UNBOUND_SESSIONS_SUBVERBS:
        return True
    if top == "runpod":
        # --help anywhere in the runpod subcommand tree is always allowed.
        if "--help" in raw or "-h" in raw or len(raw) == 1:
            return True
        # `runpod volumes ls/create` and `runpod ensure-storage` operate on RunPod
        # cloud state only — no Astrid run/lease/event mutation, so unbound is fine.
        if len(raw) >= 2 and raw[1] == "volumes":
            return True
        if len(raw) >= 2 and raw[1] == "ensure-storage":
            return True
        # `runpod sweep` writes pod_terminated_by_sweep events to owning runs'
        # events.jsonl — requires a bound session per the S4 brief.
        return False
    # `author test --project <slug>` exception. The orchestrate.cli wires the
    # `test` sub-verb regardless of whether a session is bound, so we open the
    # gate explicitly to match.
    if top == "author" and "test" in raw[1:] and "--project" in raw:
        return True
    return False


def _dispatch(raw: list[str]) -> int:
    if raw and raw[0] == "attach":
        from .core.session.cli import build_parser as _sb
        from .core.session.cli import cmd_attach

        args = _sb().parse_args(["attach", *raw[1:]])
        return int(cmd_attach(args))
    if raw and raw[0] == "sessions":
        return _dispatch_sessions(raw[1:])
    if raw and raw[0] == "start":
        from .core.task.lifecycle import cmd_start

        return cmd_start(raw[1:])
    if raw and raw[0] == "next":
        from .core.task.lifecycle import cmd_next

        return cmd_next(raw[1:])
    if raw and raw[0] == "ack":
        from .core.task.lifecycle import cmd_ack

        return cmd_ack(raw[1:])
    if raw and raw[0] == "skip":
        from .core.task.lifecycle import cmd_skip

        return cmd_skip(raw[1:])
    if raw and raw[0] == "abort":
        from .core.task.lifecycle import cmd_abort

        return cmd_abort(raw[1:])
    if raw and raw[0] == "status":
        # The new session-status verb fires when no --project is given; the
        # legacy lifecycle status verb keeps working with --project.
        if "--project" in raw[1:]:
            from .core.task.lifecycle import cmd_status

            return cmd_status(raw[1:])
        from .core.session.cli import build_parser as _sb
        from .core.session.cli import cmd_status as session_status

        status_args = ["status", *[arg for arg in raw[1:] if arg in {"-h", "--help"}]]
        args = _sb().parse_args(status_args)
        return int(session_status(args))
    if raw and raw[0] == "runs":
        return _dispatch_runs(raw[1:])
    if raw and raw[0] == "run":
        return _dispatch_run(raw[1:])
    if raw and raw[0] == "step":
        return _dispatch_step(raw[1:])
    if raw and raw[0] == "hook":
        return _dispatch_hook(raw[1:])
    if raw and raw[0] == "plan":
        return _dispatch_plan_verbs(raw[1:])
    if raw and raw[0] == "claim":
        from .core.task.claim import cmd_claim
        return cmd_claim(raw[1:])
    if raw and raw[0] == "unclaim":
        from .core.task.claim import cmd_unclaim
        return cmd_unclaim(raw[1:])
    if raw and raw[0] == "publish":
        from .packs.builtin.publish import run as publish

        return publish.main(raw[1:])
    if raw and raw[0] == "publish-youtube":
        from .packs.upload.youtube import run as publish_youtube

        return publish_youtube.main(raw[1:])
    if raw and raw[0] == "upload-youtube":
        from .packs.upload.youtube import run as publish_youtube

        return publish_youtube.main(raw[1:])
    if raw and raw[0] == "skills":
        from .skills import cli as skills_cli

        return skills_cli.main(raw[1:])
    if raw and raw[0] == "executors":
        from .core.executor import cli as executors_cli

        return executors_cli.main(raw[1:])
    if raw and raw[0] == "orchestrators":
        from .core.orchestrator import cli as orchestrators_cli

        return orchestrators_cli.main(raw[1:])
    if raw and raw[0] == "author":
        from .orchestrate import cli as author_cli

        return author_cli.main(raw[1:])
    if raw and raw[0] == "elements":
        from .core.element import cli as elements_cli

        return elements_cli.main(raw[1:])
    # TODO(Sprint 5b): astrid projects timeline is a legacy reigh-app subcommand
    # that collides with the new Sprint 2 timeline concept.  Rename to
    # `astrid projects reigh-timeline` or document the collision once the
    # reigh-app integration path is clearer.  Deferred — out of scope for 5b.
    if raw and raw[0] == "projects":
        from .core.project import cli as projects_cli

        return projects_cli.main(raw[1:])
    if raw and raw[0] == "timelines":
        from .core.timeline import cli as timelines_cli

        return timelines_cli.main(raw[1:])
    if raw and raw[0] == "modalities":
        from . import modalities

        return modalities.main(raw[1:])
    if raw and raw[0] == "runpod":
        return _dispatch_runpod(raw[1:])
    if raw and raw[0] == "doctor":
        from . import doctor

        return doctor.main(raw[1:])
    if raw and raw[0] == "setup":
        from . import setup_cli

        return setup_cli.main(raw[1:])
    if raw and raw[0] == "audit":
        from . import audit

        return audit.main(raw[1:])
    if raw and raw[0] == "events":
        return _dispatch_events(raw[1:])
    if raw and raw[0] == "reigh-data":
        from .packs.builtin.reigh_data import run as reigh_data

        return reigh_data.main(raw[1:])
    if raw and raw[0] == "worker":
        from .core.worker import banodoco_worker

        return banodoco_worker.main(raw[1:])
    return _run_default_brief_orchestrator(raw)


def _dispatch_sessions(args: list[str]) -> int:
    if not args:
        print(
            "usage: astrid sessions {ls,detach,takeover} ...",
            file=sys.stderr,
        )
        return 2
    from .core.session.cli import (
        build_parser,
        cmd_sessions_detach,
        cmd_sessions_ls,
        cmd_sessions_takeover,
    )

    sub = args[0]
    parser = build_parser()
    if sub == "ls":
        parsed = parser.parse_args(["ls"])
        return int(cmd_sessions_ls(parsed))
    if sub == "detach":
        parsed = parser.parse_args(["detach", *args[1:]])
        return int(cmd_sessions_detach(parsed))
    if sub == "takeover":
        parsed = parser.parse_args(["takeover", *args[1:]])
        return int(cmd_sessions_takeover(parsed))
    print(
        f"sessions: unknown sub-verb {sub!r}; expected one of ls / detach / takeover",
        file=sys.stderr,
    )
    return 2


def _dispatch_runs(args: list[str]) -> int:
    if not args:
        print("usage: astrid runs ls [--project <slug>]", file=sys.stderr)
        return 2
    sub = args[0]
    if sub == "ls":
        from .core.task.lifecycle import cmd_runs_ls

        return cmd_runs_ls(args[1:])
    print(
        f"runs: unknown sub-verb {sub!r}; only 'runs ls' is implemented in Phase 5",
        file=sys.stderr,
    )
    return 2


def _dispatch_run(args: list[str]) -> int:
    """Dispatch ``astrid run {show,artifacts,trace,cost}`` sub-verbs."""
    if not args:
        print(
            "usage: astrid run {show,artifacts,trace,cost} ...",
            file=sys.stderr,
        )
        return 2
    from astrid.core.task.run_audit import (
        cmd_run_artifacts,
        cmd_run_cost,
        cmd_run_show,
        cmd_run_trace,
    )

    sub = args[0]
    if sub == "show":
        return cmd_run_show(args[1:])
    if sub == "artifacts":
        return cmd_run_artifacts(args[1:])
    if sub == "trace":
        return cmd_run_trace(args[1:])
    if sub == "cost":
        return cmd_run_cost(args[1:])
    print(
        f"run: unknown sub-verb {sub!r}; expected one of show / artifacts / trace / cost",
        file=sys.stderr,
    )
    return 2


def _dispatch_step(args: list[str]) -> int:
    """Dispatch ``astrid step {retry-fetch}`` sub-verbs."""
    if not args:
        print(
            "usage: astrid step {retry-fetch} ...",
            file=sys.stderr,
        )
        return 2
    from astrid.core.task.lifecycle import cmd_step_retry_fetch

    sub = args[0]
    if sub == "retry-fetch":
        return cmd_step_retry_fetch(args[1:])
    print(
        f"step: unknown sub-verb {sub!r}; expected retry-fetch",
        file=sys.stderr,
    )
    return 2


def _dispatch_hook(args: list[str]) -> int:
    if not args or args[0] != "stop":
        print("usage: astrid hook stop", file=sys.stderr)
        return 2
    from .core.task.hook import cmd_hook_stop

    return cmd_hook_stop(args[1:])


def _dispatch_plan_verbs(args: list[str]) -> int:
    """Delegate plan sub-verbs to plan_verbs.cmd_plan (T8/T17)."""
    from .core.task.plan_verbs import cmd_plan

    return cmd_plan(args)


def _dispatch_events(args: list[str]) -> int:
    """Dispatch ``astrid events {verify,tail}`` top-level verbs (Sprint 5b).

    Both verbs read run state (events.jsonl) and require ASTRID_SESSION_ID.
    They are NOT listed in ``_verb_is_unbound_allowlisted``.
    """
    if not args:
        print(
            "usage: astrid events {verify,tail} ...",
            file=sys.stderr,
        )
        return 2
    from astrid.core.task.run_audit import cmd_events_verify, cmd_events_tail

    sub = args[0]
    if sub == "verify":
        return cmd_events_verify(args[1:])
    if sub == "tail":
        return cmd_events_tail(args[1:])
    print(
        f"events: unknown sub-verb {sub!r}; expected one of verify / tail",
        file=sys.stderr,
    )
    return 2


def _dispatch_runpod(args: list[str]) -> int:
    """Dispatch ``astrid runpod {sweep,volumes,ensure-storage} ...`` sub-verbs."""
    if not args:
        print(
            "usage: astrid runpod {sweep,volumes,ensure-storage} ...",
            file=sys.stderr,
        )
        return 2

    sub = args[0]
    if sub == "sweep":
        from .core.runpod.sweeper import sweep as run_sweep

        # Parse --hard and --dry-run from remaining args
        mode: str = "default"
        dry_run = False
        projects_root_arg: str | None = None
        i = 1
        while i < len(args):
            if args[i] == "--hard":
                mode = "hard"
                i += 1
            elif args[i] == "--dry-run":
                dry_run = True
                i += 1
            elif args[i] == "--projects-root" and i + 1 < len(args):
                projects_root_arg = args[i + 1]
                i += 2
            else:
                i += 1

        from pathlib import Path

        from .core.project.paths import resolve_projects_root

        projects_root = Path(projects_root_arg) if projects_root_arg else resolve_projects_root()
        summary = run_sweep(projects_root, mode=mode, dry_run=dry_run)  # type: ignore[arg-type]
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if sub == "volumes":
        return _dispatch_runpod_volumes(args[1:])

    if sub == "ensure-storage":
        return _dispatch_runpod_ensure_storage(args[1:])

    print(
        f"runpod: unknown sub-verb {sub!r}; expected one of sweep / volumes / ensure-storage",
        file=sys.stderr,
    )
    return 2


def _dispatch_runpod_volumes(args: list[str]) -> int:
    """Dispatch ``astrid runpod volumes ls``."""
    if not args or args[0] != "ls":
        print("usage: astrid runpod volumes ls", file=sys.stderr)
        return 2
    from .core.runpod.storage import list_volumes

    try:

        async def _volumes_ls() -> None:
            volumes = await list_volumes()
            print(json.dumps(volumes, indent=2, default=str))

        import asyncio

        asyncio.run(_volumes_ls())
        return 0
    except Exception as exc:
        print(f"runpod volumes: {exc}", file=sys.stderr)
        return 1


def _dispatch_runpod_ensure_storage(args: list[str]) -> int:
    """Dispatch ``astrid runpod ensure-storage <name> [--size <GB>] [--datacenter <id>]``."""
    import argparse

    parser = argparse.ArgumentParser(prog="astrid runpod ensure-storage")
    parser.add_argument("name", help="Volume name to find or create.")
    parser.add_argument("--size", type=int, default=50, help="Size in GB for new volumes (default: 50).")
    parser.add_argument("--datacenter", dest="datacenter_id", default=None, help="RunPod datacenter ID.")
    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return 2

    from .core.runpod.storage import ensure_storage

    try:

        async def _ensure() -> None:
            result = await ensure_storage(
                parsed.name,
                size_gb=parsed.size,
                datacenter_id=parsed.datacenter_id,
            )
            print(json.dumps(result, indent=2, default=str))

        import asyncio

        asyncio.run(_ensure())
        return 0
    except Exception as exc:
        print(f"ensure-storage: {exc}", file=sys.stderr)
        return 1


def _wait_adapter(decision: Any) -> int:
    """Wait for an adapter-dispatched step to complete. Returns a returncode.

    For local adapter: poll the subprocess until it exits, capture returncode.
    For manual adapter: the agent does work out-of-band; return 0 immediately.
    For remote-artifact adapter: poll the remote job in a loop until done/failed.
    The actual completion is detected by record_dispatch_complete via the adapter.
    """
    adapter_kind = getattr(decision, "adapter", None)
    if adapter_kind == "local":
        return _wait_local_subprocess(decision)
    if adapter_kind == "manual":
        # Manual steps: dispatch payload already written; agent works out-of-band.
        # Completion arrives via ack or inbox — not a subprocess exit code.
        return 0
    if adapter_kind == "remote-artifact":
        return _wait_remote_artifact(decision)
    # Legacy / unknown: fall through to 0 (adapter handles it in record_dispatch_complete).
    return 0


def _wait_local_subprocess(decision: Any) -> int:
    """Block until the local-adapter subprocess exits. Return its exit code."""
    import os
    import time

    pid = getattr(decision, "pid", None)
    if pid is None:
        return -1
    try:
        while True:
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
                if wpid == pid:
                    if os.WIFEXITED(status):
                        return os.WEXITSTATUS(status)
                    if os.WIFSIGNALED(status):
                        return -abs(os.WTERMSIG(status))
                    return -1
            except ChildProcessError:
                # Already reaped — check returncode sidecar.
                return _read_returncode_sidecar(decision)
            except ProcessLookupError:
                return _read_returncode_sidecar(decision)
            time.sleep(0.1)
    except KeyboardInterrupt:
        # Forward the interrupt to the child but don't crash.
        try:
            os.kill(pid, 2)  # SIGINT
        except OSError:
            pass
        return -1


def _wait_remote_artifact(decision: Any) -> int:
    """Poll the remote-artifact adapter until the subprocess exits.

    Loads ``remote_state.json`` from the step directory and polls the
    adapter's poll() method in a loop, sleeping ``poll_interval_seconds``
    between checks.  Returns 0 on ``done``, 1 on ``failed``.
    """
    import json
    import time
    from pathlib import Path

    from astrid.core.adapter.remote_artifact import RemoteArtifactAdapter

    project_root = getattr(decision, "project_root", None)
    run_id = getattr(decision, "run_id", None)
    path_tuple = getattr(decision, "plan_step_path", ())
    step_version = getattr(decision, "step_version", 1)
    if not project_root or not run_id or not path_tuple:
        return 1

    step_dir = project_root / "runs" / run_id / "steps"
    for seg in path_tuple:
        step_dir = step_dir / seg
    step_dir = step_dir / f"v{step_version}"

    remote_state_path = step_dir / "remote_state.json"
    if not remote_state_path.exists():
        return 1

    try:
        state = json.loads(remote_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 1

    poll_interval = state.get("poll_interval_seconds", 30) or 30
    adapter = RemoteArtifactAdapter()

    while True:
        try:
            wpid, status = os.waitpid(decision.pid, os.WNOHANG) if getattr(decision, "pid", None) else (0, 0)
        except (ChildProcessError, OSError):
            wpid = 0

        poll_result = adapter.poll(None, _make_run_ctx_for_poll(
            project_root, run_id, path_tuple, step_version
        ))
        if poll_result.status == "done":
            return 0
        if poll_result.status == "failed":
            return 1
        time.sleep(poll_interval)


def _make_run_ctx_for_poll(
    project_root: Any, run_id: Any, path_tuple: Any, step_version: Any
) -> Any:
    """Build a minimal RunContext for adapter.poll() calls."""
    from astrid.core.adapter import RunContext

    return RunContext(
        slug="",
        run_id=str(run_id),
        project_root=Path(project_root) if not isinstance(project_root, Path) else project_root,
        plan_step_path=tuple(path_tuple),
        step_version=int(step_version),
    )


def _read_returncode_sidecar(decision: Any) -> int:
    """If the subprocess pid is gone, try to read the returncode sidecar file."""
    from pathlib import Path

    project_root = getattr(decision, "project_root", None)
    run_id = getattr(decision, "run_id", None)
    path_tuple = getattr(decision, "plan_step_path", ())
    step_version = getattr(decision, "step_version", 1)
    if not project_root or not run_id or not path_tuple:
        return -1
    step_dir = project_root / "runs" / run_id / "steps"
    for seg in path_tuple:
        step_dir = step_dir / seg
    step_dir = step_dir / f"v{step_version}"
    rc_path = step_dir / "returncode"
    if rc_path.exists():
        try:
            return int(rc_path.read_text().strip())
        except (ValueError, OSError):
            pass
    return -1


def _extract_project_slug(raw: list[str]) -> str | None:
    for index, token in enumerate(raw):
        if token == "--project":
            return raw[index + 1] if index + 1 < len(raw) else None
        if token.startswith("--project="):
            value = token.split("=", 1)[1]
            return value or None
    return None


def _run_default_brief_orchestrator(argv: list[str]) -> int:
    from importlib import import_module

    from .core.orchestrator.registry import load_default_registry

    registry = load_default_registry()
    orchestrator = registry.get("builtin.hype")
    runtime_module = orchestrator.metadata.get("runtime_module")
    runtime_entrypoint = orchestrator.metadata.get("runtime_entrypoint", "main")
    if not isinstance(runtime_module, str) or not runtime_module:
        raise RuntimeError("builtin.hype manifest is missing metadata.runtime_module")
    module = import_module(runtime_module)
    entrypoint = getattr(module, runtime_entrypoint)
    return int(entrypoint(argv))


def _print_entrypoint_help() -> None:
    print(
        """Astrid command gateway

Usage:
  python3 -m astrid doctor
  python3 -m astrid setup [--apply]
  python3 -m astrid orchestrators {list,inspect,validate,run} ...
  python3 -m astrid author {new,check,describe,compile,test,explain} <pack>.<name>
  Task-mode operator verbs:
    python3 -m astrid start <pack>.<name> --project <slug> [--name <run-id>]
    python3 -m astrid abort --project <slug>
    python3 -m astrid status --project <slug>
    python3 -m astrid runs ls [--project <slug>]
  Plan-mutation verbs (Sprint 3):
    python3 -m astrid plan add-step --project <slug> --run-id <id> --step-id <id> --command '...' [--adapter local|manual] [--after|--before|--into <path>]
    python3 -m astrid plan edit-step <path> --project <slug> --run-id <id> [--command '...'] [--assignee ...]
    python3 -m astrid plan remove-step <path> --project <slug> --run-id <id>
    python3 -m astrid plan supersede-step <path> --project <slug> --run-id <id> --scope {all,future-iterations,future-items}
    python3 -m astrid claim <step> --project <slug> --run-id <id> [--for agent:<id>|human:<name>]
    python3 -m astrid unclaim <step> --project <slug> --run-id <id> [--for agent:<id>|human:<name>]
  Task-mode agent-facing verbs (mid-run):
    python3 -m astrid next --project <slug>
    python3 -m astrid ack <step> --project <slug> --decision {approve,retry,iterate,abort} [--agent <id> | --actor <name>] [--evidence path] [--feedback "..."] [--item id]
    python3 -m astrid hook stop   # Claude Code Stop-hook entry point; see docs/HOOKS.md
  Session verbs (Sprint 1):
    python3 -m astrid attach [<project>] [--default] [--timeline <slug>] [--session <id>] [--as agent:<id>]
    python3 -m astrid status
    python3 -m astrid sessions {ls,detach,takeover} ...
  python3 -m astrid skills {list,install,uninstall,sync,doctor} ...
  python3 -m astrid executors {list,inspect,validate,install,run} ...
  python3 -m astrid elements {list,inspect,fork,install} ...
  python3 -m astrid projects {ls,default,create,show,source} ...
  python3 -m astrid timelines {ls,create,show,rename,finalize,tombstone,purge,set-default} ...
  python3 -m astrid modalities {list,inspect} ...
  python3 -m astrid reigh-data --project-id PROJECT_ID [--out PATH]
  python3 -m astrid worker --pool banodoco [--worker-id ID] [--max-iterations N]
  python3 -m astrid events {verify,tail} --run <id> --project <slug>
  python3 -m astrid audit --run RUN_DIR
  python3 -m astrid runpod sweep [--hard] [--dry-run] [--projects-root PATH]
  python3 -m astrid runpod volumes ls
  python3 -m astrid runpod ensure-storage <name> [--size <GB>] [--datacenter <id>]
  python3 -m astrid --video SRC --brief BRIEF --out runs/name [--render]
  python3 -m astrid --brief BRIEF --out runs/name --target-duration SECONDS [--render]
Start here:
  python3 -m astrid status
  python3 -m astrid attach [<project>]
  python3 -m astrid projects ls
  python3 -m astrid orchestrators list
  python3 -m astrid executors list
  python3 -m astrid elements list
  python3 -m astrid projects show --project PROJECT
  python3 -m astrid modalities list

Inspect before running:
  python3 -m astrid orchestrators inspect builtin.hype --json
  python3 -m astrid executors inspect builtin.render --json
  python3 -m astrid elements inspect effects text-card --json
  python3 -m astrid modalities inspect generic_card --json

Run any tool through this gateway:
  python3 -m astrid orchestrators run ORCHESTRATOR_ID ...
  python3 -m astrid executors run EXECUTOR_ID ...

Notes:
  python3 -m astrid is the package entry point.
  Use orchestrators for workflows, executors for concrete work, and elements for render building blocks.
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
