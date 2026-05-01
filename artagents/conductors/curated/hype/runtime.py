"""Runtime bridge for the built-in hype pipeline conductor."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from artagents import pipeline
from artagents.conductors.runner import ConductorRunRequest, ConductorRunResult


def run(request: ConductorRunRequest, conductor) -> ConductorRunResult:
    argv = _legacy_argv(request)
    if request.dry_run:
        args = pipeline.resolve_args(argv)
        planned = tuple(tuple(step.build_cmd(args)) for step in _planned_steps(args))
        return ConductorRunResult(
            conductor_id=conductor.id,
            kind=conductor.kind,
            runtime_kind="python",
            planned_commands=planned,
            returncode=None,
            dry_run=True,
        )
    returncode = pipeline.main(argv)
    return ConductorRunResult(
        conductor_id=conductor.id,
        kind=conductor.kind,
        runtime_kind="python",
        returncode=returncode,
    )


def _legacy_argv(request: ConductorRunRequest) -> list[str]:
    argv = list(request.conductor_args)
    if request.brief is not None and not _has_option(argv, "--brief") and not _has_option(argv, "--plan"):
        argv = ["--brief", str(Path(request.brief)), *argv]
    if not _has_option(argv, "--out"):
        argv = ["--out", str(Path(request.out)), *argv]
    if request.python_exec is not None and not _has_option(argv, "--python"):
        argv = ["--python", request.python_exec, *argv]
    if request.verbose and "--verbose" not in argv:
        argv = ["--verbose", *argv]
    for key, value in request.inputs.items():
        option = "--" + str(key).replace("_", "-")
        if not _has_option(argv, option):
            argv.extend([option, str(value)])
    return argv


def _planned_steps(args) -> list[pipeline.Step]:
    skipped = set(args.skip)
    steps = [step for step in pipeline.build_steps(args) if step.name not in skipped]
    if getattr(args, "from_step", None):
        from_index = pipeline.STEP_ORDER.index(args.from_step)
        steps = [step for step in steps if pipeline.STEP_ORDER.index(step.name) >= from_index]
    if not args.render:
        steps = [step for step in steps if step.name not in {"refine", "render", "editor_review", "validate"}]
    return steps


def _has_option(argv: Sequence[str], option: str) -> bool:
    return option in argv or any(item.startswith(option + "=") for item in argv)
