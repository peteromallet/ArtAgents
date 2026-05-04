"""Canonical command-line interface for ArtAgents executors."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from artagents.core.project.run import ProjectRunError

from .banodoco_catalog import BanodocoCatalogConfig
from .registry import ExecutorRegistry, load_default_registry
from .schema import ExecutorDefinition, ExecutorValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_default_registry(_banodoco_config_from_args(args))
        return int(args.handler(args, registry))
    except (KeyError, ExecutorValidationError, ProjectRunError, ValueError) as exc:
        print(f"executors: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m artagents executors",
        description="List, inspect, validate, install, and run ArtAgents executors.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--banodoco-agent-executors", action="store_true", help="Opt in to loading executors from the Banodoco website catalog.")
    parser.add_argument("--banodoco-catalog-url", help="Banodoco website agent-executor catalog Edge Function URL.")
    parser.add_argument("--banodoco-cache-dir", help="Cache directory for git-backed Banodoco executors.")
    parser.add_argument("--banodoco-refresh", action="store_true", help="Refresh cached git checkouts before loading Banodoco executors.")
    parser.add_argument("--no-banodoco-defaults", action="store_true", help="Skip Banodoco catalog executors marked default.")
    parser.add_argument("--no-banodoco-mandatory", action="store_true", help="Skip Banodoco catalog executors marked mandatory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available executors.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=("built_in", "external"), help="Filter executors by kind.")
    list_parser.set_defaults(handler=_cmd_list)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one executor.")
    inspect_parser.add_argument("executor_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate executor metadata.")
    validate_parser.add_argument("executor_id", nargs="?")
    validate_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    validate_parser.set_defaults(handler=_cmd_validate)

    install_parser = subparsers.add_parser("install", help="Install dependencies for one executor.")
    install_parser.add_argument("executor_id")
    install_parser.add_argument("--dry-run", action="store_true", help="Print install commands without executing them.")
    install_parser.set_defaults(handler=_cmd_install)

    run_parser = subparsers.add_parser("run", help="Run or dry-run one executor.")
    run_parser.add_argument("executor_id")
    run_parser.add_argument("--out", help="Output directory for runtime placeholders.")
    run_parser.add_argument("--project", help="Project slug for a persistent project run.")
    run_parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Executor input value; may be repeated.")
    run_parser.add_argument("--brief", help="Brief path for built-in pipeline context synthesis.")
    run_parser.add_argument("--dry-run", action="store_true", help="Build and print the command without executing it.")
    run_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    run_parser.add_argument("--python-exec", help="Python executable for {python_exec} placeholders.")
    run_parser.add_argument("--verbose", action="store_true", help="Stream subprocess output for built-in pipeline steps.")
    run_parser.add_argument("--thread", help="Thread id, @new, or @none for this run.")
    run_parser.add_argument("--variants", type=int, help="Request a sibling variant count for variant-aware producers.")
    run_parser.add_argument("--from", dest="from_ref", help="Consume a specific prior run or variant, e.g. <run-id>:<n>.")
    run_parser.add_argument("--video-url", "--video", dest="video_url", help="Reachable http(s) video URL.")
    run_parser.add_argument("--title", help="YouTube video title.")
    run_parser.add_argument("--description", help="YouTube video description.")
    run_parser.add_argument("--tag", action="append", default=[], help="YouTube tag. May be repeated.")
    run_parser.add_argument("--tags", action="append", default=[], help="Comma-separated YouTube tags.")
    run_parser.add_argument("--privacy-status", default=None, help="YouTube privacy status: private, unlisted, or public.")
    run_parser.add_argument("--playlist-id", help="Optional YouTube playlist ID.")
    run_parser.add_argument("--made-for-kids", action="store_true", help="Mark the video as made for kids.")
    run_parser.set_defaults(handler=_cmd_run)
    return parser


def _banodoco_config_from_args(args: argparse.Namespace) -> BanodocoCatalogConfig:
    env_config = BanodocoCatalogConfig.from_env()
    enabled = bool(args.banodoco_agent_executors or env_config.enabled)
    return BanodocoCatalogConfig(
        enabled=enabled,
        catalog_url=args.banodoco_catalog_url or env_config.catalog_url,
        include_defaults=False if args.no_banodoco_defaults else env_config.include_defaults,
        include_mandatory=False if args.no_banodoco_mandatory else env_config.include_mandatory,
        cache_dir=Path(args.banodoco_cache_dir).expanduser() if args.banodoco_cache_dir else env_config.cache_dir,
        refresh=bool(args.banodoco_refresh or env_config.refresh),
        timeout_seconds=env_config.timeout_seconds,
    )


def _cmd_list(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    executors = registry.list(kind=args.kind)
    if args.json:
        print(json.dumps({"executors": [executor.to_dict() for executor in executors]}, indent=2, sort_keys=True))
        return 0
    for executor in executors:
        print(f"{executor.id}\t{executor.kind}\t{executor.name}")
    return 0


def _cmd_inspect(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    if args.json:
        print(executor.to_json())
        return 0
    print(f"id: {executor.id}")
    print(f"name: {executor.name}")
    print(f"kind: {executor.kind}")
    print(f"version: {executor.version}")
    if executor.description:
        print(f"description: {executor.description}")
    _print_ports("inputs", executor.inputs)
    _print_outputs(executor)
    if executor.command is not None:
        print(f"command: {shlex.join(executor.command.argv)}")
    print(f"cache: {executor.cache.mode}")
    if executor.cache.sentinels:
        print(f"cache_sentinels: {', '.join(executor.cache.sentinels)}")
    if executor.isolation.binaries:
        print(f"binaries: {', '.join(executor.isolation.binaries)}")
    _print_active_thread_footer()
    return 0


def _cmd_validate(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    registry.validate_all()
    if args.executor_id:
        _require_qualified_id(args.executor_id, "executor id")
    executors = [registry.get(args.executor_id)] if args.executor_id else registry.list()
    missing_by_executor: dict[str, tuple[str, ...]] = {}
    if args.check_binaries:
        from .runner import check_executor_binaries

        for executor in executors:
            missing = check_executor_binaries(executor)
            if missing:
                missing_by_executor[executor.id] = missing
    if missing_by_executor:
        for executor_id, missing in missing_by_executor.items():
            print(f"{executor_id}: missing binaries: {', '.join(missing)}", file=sys.stderr)
        return 1
    if args.executor_id:
        print(f"{args.executor_id}: ok")
    else:
        print(f"{len(executors)} executor(s): ok")
    return 0


def _cmd_install(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    from .install import install_executor

    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    result = install_executor(executor, dry_run=bool(args.dry_run))
    plan = result.plan
    if plan.noop_reason:
        print(f"{executor.id}: no install needed: {plan.noop_reason}")
        return result.returncode
    if plan.environment_path is not None:
        print(f"env: {plan.environment_path}")
    if plan.python_path is not None:
        print(f"python: {plan.python_path}")
    for command in plan.commands:
        print(shlex.join(command))
    return result.returncode


def _cmd_run(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    from .runner import ExecutorRunRequest, run_executor

    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    if args.project and args.out:
        raise ValueError("--project cannot be combined with --out; project runs own their output directory")
    if not args.out and not args.project and _executor_needs_out(executor):
        raise ValueError("--out is required for this executor")
    request = ExecutorRunRequest(
        executor_id=args.executor_id,
        out=Path(args.out) if args.out else "",
        project=args.project,
        inputs=_run_inputs(args),
        brief=Path(args.brief) if args.brief else None,
        dry_run=bool(args.dry_run),
        check_binaries=bool(args.check_binaries),
        python_exec=args.python_exec,
        verbose=bool(args.verbose),
        thread=args.thread,
        variants=args.variants,
        from_ref=args.from_ref,
    )
    result = run_executor(request, registry)
    if result.missing_binaries:
        print(f"{args.executor_id}: missing binaries: {', '.join(result.missing_binaries)}", file=sys.stderr)
        return 1
    if result.skipped:
        print(f"{args.executor_id}: skipped: {result.skipped_reason}")
        return 0
    if result.command:
        print(shlex.join(result.command))
    if result.payload:
        print(json.dumps(dict(result.payload), separators=(",", ":"), sort_keys=True))
    return int(result.returncode or 0)


def _executor_needs_out(executor: ExecutorDefinition) -> bool:
    if executor.id == "upload.youtube":
        return False
    if executor.kind == "built_in" and "pipeline_step" in executor.metadata:
        return True
    if executor.command is not None:
        parts = [*executor.command.argv]
        if executor.command.cwd:
            parts.append(executor.command.cwd)
        parts.extend(executor.command.env.values())
        if any("{out}" in part for part in parts):
            return True
    return any((output.path_template and "{out}" in output.path_template) for output in executor.outputs)


def _run_inputs(args: argparse.Namespace) -> dict[str, Any]:
    inputs = _parse_input_values(args.input)
    for key in ("video_url", "title", "description", "privacy_status", "playlist_id"):
        value = getattr(args, key)
        if value not in (None, ""):
            inputs[key] = value
    tags = [*getattr(args, "tag", []), *getattr(args, "tags", [])]
    if tags:
        inputs["tags"] = tags
    if getattr(args, "made_for_kids", False):
        inputs["made_for_kids"] = True
    return inputs


def _parse_input_values(raw_values: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        values[key] = value
    return values


def _require_qualified_id(value: str, label: str) -> None:
    if "." not in value or any(not part for part in value.split(".")):
        raise ValueError(f"{label} must be qualified as <pack>.<name>")


def _print_ports(label: str, ports: tuple[Any, ...]) -> None:
    if not ports:
        return
    print(f"{label}:")
    for port in ports:
        required = "required" if port.required else "optional"
        print(f"  - {port.name} ({port.type}, {required})")


def _print_outputs(executor: ExecutorDefinition) -> None:
    if not executor.outputs:
        return
    print("outputs:")
    for output in executor.outputs:
        placeholder = f", placeholder={output.placeholder}" if output.placeholder else ""
        print(f"  - {output.name} ({output.type}, {output.mode}{placeholder})")


def _print_active_thread_footer() -> None:
    try:
        import os

        from artagents._paths import REPO_ROOT
        from artagents.threads.index import ThreadIndexStore

        index = ThreadIndexStore(Path(os.environ.get("ARTAGENTS_REPO_ROOT", REPO_ROOT))).read()
    except Exception:
        print("active_thread: unavailable")
        print("thread_details: python3 -m artagents thread show @active")
        return
    active = index.get("active_thread_id")
    thread = index.get("threads", {}).get(active) if isinstance(active, str) else None
    if isinstance(thread, dict):
        print(f"active_thread: {thread.get('label') or 'unlabeled'} ({active})")
    else:
        print("active_thread: none")
    print("thread_details: python3 -m artagents thread show @active")


if __name__ == "__main__":
    raise SystemExit(main())
