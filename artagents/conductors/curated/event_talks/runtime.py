"""Runtime bridge for the built-in event talks conductor."""

from __future__ import annotations

from artagents import event_talks
from artagents.conductors.runner import ConductorRunRequest, ConductorRunResult, ConductorRunnerError


SUPPORTED_SUBCOMMANDS = {"ados-sunday-template", "search-transcript", "find-holding-screens", "render"}


def run(request: ConductorRunRequest, conductor) -> ConductorRunResult:
    argv = list(request.conductor_args)
    _validate_subcommand(argv)
    planned = (("event_talks.py", *argv),)
    if request.dry_run:
        return ConductorRunResult(
            conductor_id=conductor.id,
            kind=conductor.kind,
            runtime_kind="python",
            planned_commands=planned,
            returncode=None,
            dry_run=True,
        )
    returncode = event_talks.main(argv)
    return ConductorRunResult(
        conductor_id=conductor.id,
        kind=conductor.kind,
        runtime_kind="python",
        planned_commands=planned,
        returncode=returncode,
    )


def _validate_subcommand(argv: list[str]) -> None:
    if not argv:
        raise ConductorRunnerError(
            "builtin.event_talks requires a passthrough subcommand after --: "
            + ", ".join(sorted(SUPPORTED_SUBCOMMANDS))
        )
    if argv[0] not in SUPPORTED_SUBCOMMANDS:
        raise ConductorRunnerError(f"unknown event_talks subcommand {argv[0]!r}")
