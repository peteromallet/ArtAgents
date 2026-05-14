"""Task-run environment helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping

TASK_RUN_ID_ENV = "ASTRID_TASK_RUN_ID"
TASK_PROJECT_ENV = "ASTRID_TASK_PROJECT"
TASK_STEP_ID_ENV = "ASTRID_TASK_STEP_ID"
TASK_ITEM_ID_ENV = "ASTRID_TASK_ITEM_ID"
TASK_ITERATION_ENV = "ASTRID_TASK_ITERATION"
ASTRID_ACTOR = "ASTRID_ACTOR"
ASTRID_AUTHOR_TEST = "ASTRID_AUTHOR_TEST"


def task_project_env() -> str | None:
    return os.environ.get(TASK_PROJECT_ENV)


def task_run_id_env() -> str | None:
    return os.environ.get(TASK_RUN_ID_ENV)


def task_step_id_env() -> str | None:
    return os.environ.get(TASK_STEP_ID_ENV)


def task_item_id_env() -> str | None:
    return os.environ.get(TASK_ITEM_ID_ENV)


def task_iteration_env() -> str | None:
    return os.environ.get(TASK_ITERATION_ENV)


def task_actor_env() -> str | None:
    return os.environ.get(ASTRID_ACTOR)


def is_author_test_mode() -> bool:
    return os.environ.get(ASTRID_AUTHOR_TEST) == "1"


def is_in_task_run(slug: str | None = None) -> bool:
    run_id = task_run_id_env()
    if not run_id:
        return False
    return slug is None or task_project_env() == slug


def apply_task_run_env(
    run_id: str,
    project_slug: str,
    step_id: str,
    *,
    item_id: str | None = None,
    iteration: int | None = None,
) -> None:
    os.environ[TASK_RUN_ID_ENV] = run_id
    os.environ[TASK_PROJECT_ENV] = project_slug
    os.environ[TASK_STEP_ID_ENV] = step_id
    if item_id is None:
        os.environ.pop(TASK_ITEM_ID_ENV, None)
    else:
        os.environ[TASK_ITEM_ID_ENV] = item_id
    if iteration is None:
        os.environ.pop(TASK_ITERATION_ENV, None)
    else:
        os.environ[TASK_ITERATION_ENV] = f"{int(iteration):03d}"


def child_subprocess_env(*, base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.pop(ASTRID_ACTOR, None)
    for key in (
        TASK_RUN_ID_ENV,
        TASK_PROJECT_ENV,
        TASK_STEP_ID_ENV,
        TASK_ITEM_ID_ENV,
        TASK_ITERATION_ENV,
    ):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env
