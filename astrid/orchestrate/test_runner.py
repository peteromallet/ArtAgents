"""Author-test fixture replay driver.

``run_fixture`` drives a compiled orchestrator plan through the gate inside a
scratch projects root with ARTAGENTS_AUTHOR_TEST=1, auto-approving attested
steps. The resulting events.jsonl path is returned for the diff/regenerate
caller in ``orchestrate.cli``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from astrid.core.task.active_run import read_active_run
from astrid.core.task.env import (
    ARTAGENTS_ACTOR,
    ARTAGENTS_AUTHOR_TEST,
    TASK_ITEM_ID_ENV,
    TASK_ITERATION_ENV,
    TASK_PROJECT_ENV,
    TASK_RUN_ID_ENV,
    TASK_STEP_ID_ENV,
    child_subprocess_env,
)
from astrid.core.task.events import read_events
from astrid.core.task.gate import (
    TaskRunGateError,
    gate_command,
    peek_current_step,
    record_dispatch_complete,
)
from astrid.core.task.lifecycle import cmd_start
from astrid.core.task.lifecycle_ack import cmd_ack
from astrid.core.task.plan import (
    STEP_PATH_SEP,
    is_attested_kind,
    is_code_kind,
    load_plan,
)


_MAX_ITERATIONS = 200

# Env vars that gate dispatch (apply_task_run_env) injects into os.environ.
# We snapshot these before run_fixture mutates anything and restore in finally
# so a fixture replay never leaks task-run state into the surrounding test
# process or shell.
_MANAGED_ENV_VARS = (
    ARTAGENTS_AUTHOR_TEST,
    ARTAGENTS_ACTOR,
    TASK_RUN_ID_ENV,
    TASK_PROJECT_ENV,
    TASK_STEP_ID_ENV,
    TASK_ITEM_ID_ENV,
    TASK_ITERATION_ENV,
)


def _snapshot_env(names: tuple[str, ...]) -> dict[str, Optional[str]]:
    return {name: os.environ.get(name) for name in names}


def _restore_env(snapshot: dict[str, Optional[str]]) -> None:
    for name, value in snapshot.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def run_fixture(
    *,
    qualified_id: str,
    fixture_dir: Optional[Path],
    packs_root: Path,
    projects_root: Path,
    project_slug: str = "author_test",
    run_id: str = "fixture_run",
) -> Path:
    """Replay the orchestrator plan against the fixture inside ``projects_root``.

    Returns the path to ``events.jsonl`` for the resulting run. Raises
    ``RuntimeError`` if the loop fails to make progress within the cap, or if
    the gate / lifecycle helpers reject a step (the original error is wrapped).
    """
    snapshot = _snapshot_env(_MANAGED_ENV_VARS)
    os.environ[ARTAGENTS_AUTHOR_TEST] = "1"
    os.environ[ARTAGENTS_ACTOR] = "author_test"
    try:
        project_root = projects_root / project_slug
        if fixture_dir is not None and Path(fixture_dir).exists():
            shutil.copytree(fixture_dir, project_root, dirs_exist_ok=True)
        project_root.mkdir(parents=True, exist_ok=True)

        rc = cmd_start(
            [qualified_id, "--project", project_slug, "--name", run_id],
            packs_root=packs_root,
            projects_root=projects_root,
        )
        if rc != 0:
            raise RuntimeError(
                f"author test: cmd_start failed with rc={rc} for {qualified_id}"
            )

        plan_path = project_root / "plan.json"
        events_path = project_root / "runs" / run_id / "events.jsonl"

        for _ in range(_MAX_ITERATIONS):
            active = read_active_run(project_slug, root=projects_root)
            if active is None:
                break
            plan = load_plan(plan_path)
            events = read_events(events_path)
            peek = peek_current_step(
                plan,
                events,
                project_slug,
                project_root=project_root,
                run_id=run_id,
            )
            if peek.exhausted or peek.step is None:
                break

            step = peek.step
            path_str = STEP_PATH_SEP.join(peek.path_tuple)

            if is_code_kind(step):
                cmd_str = step.command
                cmd_argv = shlex.split(cmd_str)
                try:
                    decision = gate_command(
                        project_slug,
                        cmd_str,
                        cmd_argv,
                        root=projects_root,
                    )
                except TaskRunGateError as exc:
                    raise RuntimeError(
                        f"author test: gate rejected code step {path_str!r}: {exc.reason}"
                    ) from exc
                completed = subprocess.run(
                    cmd_argv,
                    env={**os.environ, **child_subprocess_env()},
                    check=False,
                )
                record_dispatch_complete(decision, completed.returncode)
                continue

            if is_attested_kind(step):
                if step.ack is not None and step.ack.kind == "agent":
                    flag_pair = ["--agent", "author_test"]
                else:
                    flag_pair = ["--actor", "author_test"]
                rc = cmd_ack(
                    [
                        path_str,
                        "--project",
                        project_slug,
                        "--decision",
                        "approve",
                        *flag_pair,
                    ],
                    projects_root=projects_root,
                )
                if rc != 0:
                    raise RuntimeError(
                        f"author test: cmd_ack failed for attested step {path_str!r} "
                        f"(rc={rc})"
                    )
                continue

            raise RuntimeError(
                f"author test: unsupported peek step kind {type(step).__name__} "
                f"at {path_str!r}"
            )
        else:
            raise RuntimeError(
                f"author test: exceeded {_MAX_ITERATIONS} iterations without "
                f"reaching plan completion (likely an author bug; check plan)"
            )

        return events_path
    finally:
        _restore_env(snapshot)
