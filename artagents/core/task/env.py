"""Task-run environment helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping

TASK_RUN_ID_ENV = "ARTAGENTS_TASK_RUN_ID"
TASK_PROJECT_ENV = "ARTAGENTS_TASK_PROJECT"
TASK_STEP_ID_ENV = "ARTAGENTS_TASK_STEP_ID"


def task_project_env() -> str | None:
    return os.environ.get(TASK_PROJECT_ENV)


def task_run_id_env() -> str | None:
    return os.environ.get(TASK_RUN_ID_ENV)


def task_step_id_env() -> str | None:
    return os.environ.get(TASK_STEP_ID_ENV)


def is_in_task_run(slug: str | None = None) -> bool:
    run_id = task_run_id_env()
    if not run_id:
        return False
    return slug is None or task_project_env() == slug


def apply_task_run_env(run_id: str, project_slug: str, step_id: str) -> None:
    os.environ[TASK_RUN_ID_ENV] = run_id
    os.environ[TASK_PROJECT_ENV] = project_slug
    os.environ[TASK_STEP_ID_ENV] = step_id


def child_subprocess_env(*, base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in (TASK_RUN_ID_ENV, TASK_PROJECT_ENV, TASK_STEP_ID_ENV):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env
