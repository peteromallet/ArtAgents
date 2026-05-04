#!/usr/bin/env python3
"""ArtAgents top-level command gateway.

Subcommands dispatch to focused module CLIs (executors, orchestrators,
elements, projects, threads, modalities, doctor, setup, audit). Brief / video
flags fall through to the ``builtin.hype`` orchestrator resolved through the
orchestrator registry.
"""

from __future__ import annotations

import sys


# Phase 5 lifecycle verbs short-circuit the implicit task-mode gate at the top
# of main(): for these verbs the --project flag identifies the run, NOT a
# command to dispatch through plan[cursor]. cmd_ack approve re-enters the gate
# explicitly (see lifecycle_ack._ack_approve), so the short-circuit only
# bypasses the gate's command-match step.
LIFECYCLE_VERBS = {"start", "next", "ack", "abort", "status", "runs", "hook"}


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] in {"-h", "--help"}:
        _print_entrypoint_help()
        return 0
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
        task_gate.record_dispatch_complete(decision, returncode)


def _dispatch(raw: list[str]) -> int:
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
        from .core.task.lifecycle import cmd_status

        return cmd_status(raw[1:])
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
    if raw and raw[0] == "thread":
        from .threads import cli as thread_cli

        return thread_cli.main(raw[1:])
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


def _dispatch_runs(args: list[str]) -> int:
    if not args:
        print("usage: artagents runs ls [--project <slug>]", file=sys.stderr)
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
        print("usage: artagents hook stop", file=sys.stderr)
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
        """ArtAgents command gateway

Usage:
  python3 -m artagents doctor
  python3 -m artagents setup [--apply]
  python3 -m artagents orchestrators {list,inspect,validate,run} ...
  python3 -m artagents author {new,check,describe,compile,test,explain} <pack>.<name>
  Task-mode operator verbs:
    python3 -m artagents start <pack>.<name> --project <slug> [--name <run-id>]
    python3 -m artagents abort --project <slug>
    python3 -m artagents status --project <slug>
    python3 -m artagents runs ls [--project <slug>]
  Task-mode agent-facing verbs (mid-run):
    python3 -m artagents next --project <slug>
    python3 -m artagents ack <step> --project <slug> --decision {approve,retry,iterate,abort} [--agent <id> | --actor <name>] [--evidence path] [--feedback "..."] [--item id]
    python3 -m artagents hook stop   # Claude Code Stop-hook entry point; see docs/HOOKS.md
  python3 -m artagents executors {list,inspect,validate,install,run} ...
  python3 -m artagents elements {list,inspect,fork,install} ...
  python3 -m artagents projects {create,show,source,timeline,materialize} ...
  python3 -m artagents thread {new,list,show,archive,reopen,backfill,keep,dismiss,group} ...
  python3 -m artagents modalities {list,inspect} ...
  python3 -m artagents reigh-data --project-id PROJECT_ID [--out PATH]
  python3 -m artagents worker --pool banodoco [--worker-id ID] [--max-iterations N]
  python3 -m artagents audit --run RUN_DIR
  python3 -m artagents --video SRC --brief BRIEF --out runs/name [--render]
  python3 -m artagents --brief BRIEF --out runs/name --target-duration SECONDS [--render]
Start here:
  python3 -m artagents doctor
  python3 -m artagents orchestrators list
  python3 -m artagents executors list
  python3 -m artagents elements list
  python3 -m artagents projects show --project PROJECT
  python3 -m artagents thread list
  python3 -m artagents modalities list

Inspect before running:
  python3 -m artagents orchestrators inspect builtin.hype --json
  python3 -m artagents executors inspect builtin.render --json
  python3 -m artagents elements inspect effects text-card --json
  python3 -m artagents modalities inspect generic_card --json

Run any tool through this gateway:
  python3 -m artagents orchestrators run ORCHESTRATOR_ID ...
  python3 -m artagents executors run EXECUTOR_ID ...

Notes:
  python3 -m artagents is the package entry point.
  Use orchestrators for workflows, executors for concrete work, and elements for render building blocks.
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
