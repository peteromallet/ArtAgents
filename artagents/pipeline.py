#!/usr/bin/env python3
"""ArtAgents top-level command gateway.

Subcommands dispatch to focused module CLIs (executors, orchestrators,
elements, projects, threads, modalities, doctor, setup, audit). Brief / video
flags fall through to the ``builtin.hype`` orchestrator resolved through the
orchestrator registry.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] in {"-h", "--help"}:
        _print_entrypoint_help()
        return 0
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
    return _run_default_brief_orchestrator(raw)


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
  python3 -m artagents executors {list,inspect,validate,install,run} ...
  python3 -m artagents elements {list,inspect,fork,install} ...
  python3 -m artagents projects {create,show,source,timeline,materialize} ...
  python3 -m artagents thread {new,list,show,archive,reopen,backfill,keep,dismiss,group} ...
  python3 -m artagents modalities {list,inspect} ...
  python3 -m artagents reigh-data --project-id PROJECT_ID [--out PATH]
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
