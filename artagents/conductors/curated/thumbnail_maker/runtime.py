"""Runtime bridge for the built-in thumbnail maker conductor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from artagents import thumbnail_maker
from artagents.conductors.runner import ConductorRunRequest, ConductorRunResult, ConductorRunnerError


def run(request: ConductorRunRequest, conductor) -> ConductorRunResult:
    argv = _legacy_argv(request)
    _validate_merged_argv(argv)
    planned = (("thumbnail_maker.py", *argv),)
    if request.dry_run:
        return ConductorRunResult(
            conductor_id=conductor.id,
            kind=conductor.kind,
            runtime_kind="python",
            command=planned[0],
            planned_commands=planned,
            returncode=None,
            dry_run=True,
        )
    returncode = thumbnail_maker.main(argv)
    return ConductorRunResult(
        conductor_id=conductor.id,
        kind=conductor.kind,
        runtime_kind="python",
        command=planned[0],
        planned_commands=planned,
        returncode=returncode,
    )


def _legacy_argv(request: ConductorRunRequest) -> list[str]:
    argv = list(request.conductor_args)
    for key, value in request.inputs.items():
        option = "--" + str(key).replace("_", "-")
        if value is not None and not _has_option(argv, option):
            argv.extend([option, str(value)])
    if request.out is not None and not _has_option(argv, "--out"):
        argv.extend(["--out", str(Path(request.out))])
    if request.dry_run and "--dry-run" not in argv:
        argv.append("--dry-run")
    return argv


def _validate_merged_argv(argv: Sequence[str]) -> None:
    missing: list[str] = []
    for option, label in (("--video", "video"), ("--query", "query"), ("--out", "output directory")):
        value = _option_value(argv, option)
        if value is None or not str(value).strip():
            missing.append(label)
    if missing:
        raise ConductorRunnerError(
            "builtin.thumbnail_maker requires merged " + ", ".join(missing) + " values"
        )


def _has_option(argv: Sequence[str], option: str) -> bool:
    return option in argv or any(item.startswith(option + "=") for item in argv)


def _option_value(argv: Sequence[str], option: str) -> str | None:
    prefix = option + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == option:
            next_index = index + 1
            if next_index >= len(argv):
                return ""
            candidate = argv[next_index]
            if candidate.startswith("--"):
                return ""
            return candidate
    return None


__all__ = ["run"]
