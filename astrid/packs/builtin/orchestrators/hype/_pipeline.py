"""In-process step machinery for the hype orchestrator.

Moved out of `astrid.core.executor.runner` during Sprint 9 Phase 2 so that the
runner no longer hardcodes a builtin pack import. The runner now imports these
helpers from inside the hype orchestrator package itself; in Phase 4 the
in-process dispatch will retire entirely and external executors will run via
subprocess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from astrid.core.executor.runner import (
    ExecutorRunRequest,
    ExecutorRunnerError,
    _as_string_list,
    _default_brief_slug,
    _normalize_extra_args,
    _optional_float,
    _optional_path,
    _request_values,
)
from astrid.core.executor.schema import ExecutorDefinition

from . import run as pipeline


def _builtin_steps_by_name() -> Mapping[str, Any]:
    steps = {step.name: step for step in pipeline.build_pool_steps()}
    missing = [name for name in pipeline.STEP_ORDER if name not in steps]
    if missing:
        raise ValueError(
            f"build_pool_steps() is missing STEP_ORDER entries: {', '.join(missing)}"
        )
    return MappingProxyType(steps)


def _step_for_executor(executor: ExecutorDefinition) -> Any:
    step_name = executor.metadata.get("pipeline_step")
    if not isinstance(step_name, str):
        raise ExecutorRunnerError(
            f"built-in executor {executor.id!r} is missing metadata.pipeline_step"
        )
    steps = _builtin_steps_by_name()
    if step_name not in steps:
        raise ExecutorRunnerError(
            f"built-in executor {executor.id!r} references unknown pipeline step {step_name!r}"
        )
    return steps[step_name]


def _optional_asset_path(value: Any) -> Path | str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if pipeline.asset_cache.is_url(text):
        return text
    return Path(text).expanduser().resolve()


def _parse_asset_pairs(values: list[str]) -> list[tuple[str, Path | str]]:
    pairs: list[tuple[str, Path | str]] = []
    for raw in values:
        if "=" not in raw:
            raise ExecutorRunnerError(f"invalid asset value {raw!r}; expected KEY=PATH")
        key, path_text = raw.split("=", 1)
        key = key.strip()
        path_text = path_text.strip()
        if not key or not path_text:
            raise ExecutorRunnerError(f"invalid asset value {raw!r}; expected KEY=PATH")
        if pipeline.asset_cache.is_url(path_text):
            pairs.append((key, path_text))
        else:
            pairs.append((key, Path(path_text).expanduser().resolve()))
    return pairs


def build_pipeline_context(
    request: ExecutorRunRequest,
    executor: ExecutorDefinition | None = None,
) -> argparse.Namespace:
    values = _request_values(request)
    out = Path(request.out).expanduser().resolve()
    brief = _optional_path(values.get("brief") or request.brief)
    if brief is None:
        brief = (out / "brief.txt").resolve()
    audio_value = values.get("audio")
    video_value = values.get("video")
    video = _optional_asset_path(video_value)
    audio = _optional_asset_path(audio_value if audio_value is not None else video_value)
    env_file = _optional_path(values.get("env_file"))
    theme_raw = values.get("theme")
    theme_explicit = theme_raw is not None
    theme = (
        pipeline._resolve_theme_arg(theme_raw)
        if theme_explicit
        else pipeline._resolve_theme_arg(
            pipeline.WORKSPACE_ROOT / "themes" / "banodoco-default" / "theme.json"
        )
    )
    brief_slug = str(values.get("brief_slug") or _default_brief_slug(brief, out))
    brief_out = (out / "briefs" / brief_slug).resolve()
    skip = _as_string_list(values.get("skip"))
    asset_values = _as_string_list(values.get("asset") or values.get("assets"))
    args = argparse.Namespace(
        audio=audio,
        video=video,
        out=out,
        brief=brief,
        brief_out=brief_out,
        brief_copy=brief_out / "brief.txt",
        skip=skip,
        asset=asset_values,
        asset_pairs=_parse_asset_pairs(asset_values),
        primary_asset=values.get("primary_asset"),
        theme=theme,
        theme_explicit=theme_explicit,
        source_slug=str(values.get("source_slug") or out.name),
        brief_slug=brief_slug,
        env_file=env_file,
        extra_args=_normalize_extra_args(values.get("extra_args")),
        target_duration=_optional_float(values.get("target_duration")),
        python_exec=str(values.get("python_exec") or request.python_exec or sys.executable),
        render=bool(values.get("render", False)),
        verbose=bool(values.get("verbose", request.verbose)),
        no_prefetch=bool(values.get("no_prefetch", False)),
        keep_downloads=bool(values.get("keep_downloads", False)),
        cache_dir=_optional_path(values.get("cache_dir")),
        drift=str(values.get("drift") or "strict"),
        from_step=values.get("from_step"),
        max_editor_passes=int(values.get("max_editor_passes", 2)),
        editor_iteration=int(values.get("editor_iteration", 1)),
    )
    if executor is not None:
        args.executor_id = executor.id
    return args


def run_builtin_executor(executor: ExecutorDefinition, request: ExecutorRunRequest):
    """Execute a builtin executor in-process via its hype pipeline step.

    Returns an `ExecutorRunResult`. Caller passes an already-resolved
    `ExecutorRunRequest`; this function builds the per-step argv via
    `build_pipeline_context()` and dispatches through `pipeline.run_step()`.
    """
    from astrid.core.executor.runner import ExecutorRunResult

    step = _step_for_executor(executor)
    args = build_pipeline_context(request, executor)
    command = tuple(step.build_cmd(args))
    if request.dry_run:
        return ExecutorRunResult(
            executor_id=executor.id,
            kind=executor.kind,
            command=command,
            payload={
                "executor_id": executor.id,
                "missing_binaries": [],
                "returncode": None,
                "skipped": False,
                "skipped_reason": "",
            },
            dry_run=True,
        )
    if args.brief.exists():
        pipeline.prepare_brief_artifacts(args)
    returncode = pipeline.run_step(step, list(command), args)
    return ExecutorRunResult(
        executor_id=executor.id,
        kind=executor.kind,
        command=command,
        payload={
            "executor_id": executor.id,
            "missing_binaries": [],
            "returncode": returncode,
            "skipped": False,
            "skipped_reason": "",
        },
        returncode=returncode,
    )


__all__ = [
    "build_pipeline_context",
    "run_builtin_executor",
]
