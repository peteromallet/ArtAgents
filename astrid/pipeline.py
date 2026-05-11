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

import sys
from typing import Iterable


# Phase 5 lifecycle verbs short-circuit the implicit task-mode gate at the top
# of main(): for these verbs the --project flag identifies the run, NOT a
# command to dispatch through plan[cursor]. cmd_ack approve re-enters the gate
# explicitly (see lifecycle_ack._ack_approve), so the short-circuit only
# bypasses the gate's command-match step.
LIFECYCLE_VERBS = {"start", "next", "ack", "abort", "status", "runs", "hook"}


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
_UNBOUND_PROJECTS_SUBVERBS = {"ls", "create"}
_UNBOUND_SESSIONS_SUBVERBS = {"ls", "takeover", "detach"}


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] in {"-h", "--help"}:
        _print_entrypoint_help()
        return 0
    # Nudge runs once per CLI invocation, before the command itself, but never
    # for the `skills` subcommand (would be silly) or help. Cheap state-file
    # read; bails early if no harness is detected or ARTAGENTS_NO_NUDGE is set.
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
            print(
                "no session bound — run `astrid attach <project>`",
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
    * ``projects ls`` and ``projects create``.
    * ``sessions ls`` / ``sessions takeover`` / ``sessions detach``.
    * ``author test --project <slug>`` — documented exception for the
      workflow test runner.
    """

    if not raw:
        return True  # empty argv → entrypoint help

    top = raw[0]
    if top in {"-h", "--help"}:
        return True
    if top in {"attach", "init", "status"}:
        return True
    if top == "projects" and len(raw) >= 2 and raw[1] in _UNBOUND_PROJECTS_SUBVERBS:
        return True
    if top == "timelines" and len(raw) >= 2 and raw[1] == "ls":
        return True
    if top == "sessions" and len(raw) >= 2 and raw[1] in _UNBOUND_SESSIONS_SUBVERBS:
        return True
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

        args = _sb().parse_args(["status"])
        return int(session_status(args))
    if raw and raw[0] == "runs":
        return _dispatch_runs(raw[1:])
    if raw and raw[0] == "hook":
        return _dispatch_hook(raw[1:])
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
    if raw and raw[0] == "projects":
        from .core.project import cli as projects_cli

        return projects_cli.main(raw[1:])
    if raw and raw[0] == "timelines":
        from .core.timeline import cli as timelines_cli

        return timelines_cli.main(raw[1:])
    if raw and raw[0] == "modalities":
        from . import modalities

        return modalities.main(raw[1:])
    if raw and raw[0] == "doctor":
        from . import doctor

        return doctor.main(raw[1:])
    if raw and raw[0] == "setup":
        from . import setup_cli

        return setup_cli.main(raw[1:])
    if raw and raw[0] == "audit":
        from . import audit

        return audit.main(raw[1:])
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


def _dispatch_hook(args: list[str]) -> int:
    if not args or args[0] != "stop":
        print("usage: astrid hook stop", file=sys.stderr)
        return 2
    from .core.task.hook import cmd_hook_stop

    return cmd_hook_stop(args[1:])


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
  Task-mode agent-facing verbs (mid-run):
    python3 -m astrid next --project <slug>
    python3 -m astrid ack <step> --project <slug> --decision {approve,retry,iterate,abort} [--agent <id> | --actor <name>] [--evidence path] [--feedback "..."] [--item id]
    python3 -m astrid hook stop   # Claude Code Stop-hook entry point; see docs/HOOKS.md
  Session verbs (Sprint 1):
    python3 -m astrid attach <project> [--timeline <slug>] [--session <id>] [--as agent:<id>]
    python3 -m astrid status
    python3 -m astrid sessions {ls,detach,takeover} ...
  python3 -m astrid skills {list,install,uninstall,sync,doctor} ...
  python3 -m astrid executors {list,inspect,validate,install,run} ...
  python3 -m astrid elements {list,inspect,fork,install} ...
  python3 -m astrid projects {create,show,source} ...
  python3 -m astrid timelines {ls,create,show,rename,finalize,tombstone,purge,set-default} ...
  python3 -m astrid modalities {list,inspect} ...
  python3 -m astrid reigh-data --project-id PROJECT_ID [--out PATH]
  python3 -m astrid worker --pool banodoco [--worker-id ID] [--max-iterations N]
  python3 -m astrid audit --run RUN_DIR
  python3 -m astrid --video SRC --brief BRIEF --out runs/name [--render]
  python3 -m astrid --brief BRIEF --out runs/name --target-duration SECONDS [--render]
Start here:
  python3 -m astrid attach <project>
  python3 -m astrid status
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
