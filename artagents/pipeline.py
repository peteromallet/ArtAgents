#!/usr/bin/env python3
"""ArtAgents package command gateway.

Hype orchestration lives in :mod:`artagents.orchestrators.hype.run`.
This module keeps the historical top-level CLI and import surface stable.
"""

from __future__ import annotations

import sys

from ._paths import REPO_ROOT as _REPO_ROOT
from .orchestrators.hype import run as _hype


# Compatibility exports for older tests, wrappers, and external callers that
# imported hype pipeline helpers from artagents.pipeline.
STEP_ORDER = _hype.STEP_ORDER
PER_SOURCE_SENTINELS = _hype.PER_SOURCE_SENTINELS
PER_BRIEF_SENTINELS = _hype.PER_BRIEF_SENTINELS
Step = _hype.Step
usage_error = _hype.usage_error
_resolve_theme_arg = _hype._resolve_theme_arg
build_parser = _hype.build_parser
load_config = _hype.load_config
normalize_config = _hype.normalize_config
parse_asset_entry = _hype.parse_asset_entry
normalize_many = _hype.normalize_many
normalize_extra_args = _hype.normalize_extra_args
resolve_args = _hype.resolve_args
step_argv = _hype.step_argv
add_extra_args = _hype.add_extra_args
asset_args = _hype.asset_args
probe_audio_duration = _hype.probe_audio_duration
prepare_brief_artifacts = _hype.prepare_brief_artifacts
parse_brief_frontmatter = _hype.parse_brief_frontmatter
build_pool_cut_cmd = _hype.build_pool_cut_cmd
build_pool_steps = _hype.build_pool_steps
select_steps = _hype.select_steps
step_output_root = _hype.step_output_root
log_dir_for_step = _hype.log_dir_for_step
sentinel_paths = _hype.sentinel_paths
should_rerun = _hype.should_rerun
print_log_tail = _hype.print_log_tail
run_step = _hype.run_step
cmd_safe = _hype.cmd_safe
write_skip_log = _hype.write_skip_log
pool_main = _hype.pool_main
asset_cache = _hype.asset_cache
WORKSPACE_ROOT = _hype.WORKSPACE_ROOT
REPO_ROOT = _REPO_ROOT


def _sync_hype_aliases() -> None:
    """Propagate monkey-patched legacy aliases before delegating to hype."""
    _hype.run_step = run_step
    _hype.print_log_tail = print_log_tail
    _hype.probe_audio_duration = probe_audio_duration
    _hype.select_steps = select_steps
    _hype.build_pool_steps = build_pool_steps
    _hype.build_pool_cut_cmd = build_pool_cut_cmd
    _hype.prepare_brief_artifacts = prepare_brief_artifacts
    _hype.pool_main = pool_main


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
    _sync_hype_aliases()
    return _hype.main(raw)


def _print_entrypoint_help() -> None:
    print(
        """ArtAgents command gateway

Usage:
  python3 -m artagents doctor
  python3 -m artagents setup [--apply]
  python3 -m artagents orchestrators {list,inspect,validate,run} ...
  python3 -m artagents executors {list,inspect,validate,install,run} ...
  python3 -m artagents elements {list,inspect,sync,fork,install,update} ...
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
