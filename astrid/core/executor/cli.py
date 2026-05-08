"""Canonical command-line interface for Astrid executors."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from astrid.core.project.run import ProjectRunError

from astrid.core._search import (
    SearchRecord,
    search as run_search,
    short_description_or_truncated,
)

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
        prog="python3 -m astrid executors",
        description="List, inspect, validate, install, and run Astrid executors.",
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
    list_parser.add_argument("--no-describe", action="store_true", help="Omit the short_description column for legacy parsers.")
    list_parser.set_defaults(handler=_cmd_list)

    search_parser = subparsers.add_parser("search", help="Search executors by id, keywords, descriptions, and binaries.")
    search_parser.add_argument("terms", nargs="+", help="One or more search terms.")
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    search_parser.add_argument("--limit", type=int, default=25, help="Maximum number of hits (default 25).")
    search_parser.set_defaults(handler=_cmd_search)

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
    run_parser.add_argument(
        "--project",
        help=(
            "Project identifier. A project slug runs in cache-only/offline mode "
            "(local sources/ + runs/ provenance). A reigh-app project UUID "
            "(8-4-4-4-12 hex) routes the post-run timeline through "
            "SupabaseDataProvider; pair with --timeline-id."
        ),
    )
    run_parser.add_argument(
        "--timeline-id",
        dest="timeline_id",
        help="reigh-app timeline UUID; required when --project is a reigh-app UUID.",
    )
    run_parser.add_argument(
        "--service-role",
        action="store_true",
        help="Worker-only escape hatch when pushing back via SupabaseDataProvider.",
    )
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
    no_describe = bool(getattr(args, "no_describe", False))
    for executor in executors:
        if no_describe:
            print(f"{executor.id}\t{executor.kind}\t{executor.name}")
        else:
            short = short_description_or_truncated(executor.short_description, executor.description)
            print(f"{executor.id}\t{executor.kind}\t{executor.name}\t{short}")
    return 0


def _cmd_search(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    records = [_executor_search_record(executor) for executor in registry.list()]
    hits = run_search(records, list(args.terms), limit=int(args.limit))
    if args.json:
        payload = [
            {
                "id": hit.record.id,
                "kind": hit.record.kind,
                "score": round(hit.score, 3),
                "short_description": hit.record.short_description,
            }
            for hit in hits
        ]
        print(json.dumps({"hits": payload}, indent=2, sort_keys=True))
        return 0
    for hit in hits:
        print(f"{hit.score:.2f}\t{hit.record.id}\t{hit.record.kind}\t{hit.record.short_description}")
    return 0


def _executor_search_record(executor: ExecutorDefinition) -> SearchRecord:
    short = short_description_or_truncated(executor.short_description, executor.description)
    fields = {
        "id": executor.id,
        "name": executor.name,
        "short_description": executor.short_description,
        "description": executor.description,
        "keywords": " ".join(executor.keywords),
        "binaries": " ".join(executor.isolation.binaries),
    }
    return SearchRecord(id=executor.id, kind=executor.kind, short_description=short, fields=fields)


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
    if executor.short_description:
        print(f"short_description: {executor.short_description}")
    if executor.description:
        print(f"description: {executor.description}")
    if executor.keywords:
        print(f"keywords: {', '.join(executor.keywords)}")
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
    project_uuid = _project_uuid_or_none(args.project)
    if project_uuid is not None:
        # UUID mode: --project is a reigh-app UUID, runs need an --out for
        # local placeholders + a --timeline-id to address the row.
        if not getattr(args, "timeline_id", None):
            raise ValueError("--timeline-id is required when --project is a reigh-app UUID")
        if not args.out:
            raise ValueError("--out is required when --project is a reigh-app UUID")
        local_project: str | None = None
    else:
        local_project = args.project
        if local_project and args.out:
            raise ValueError("--project cannot be combined with --out; project runs own their output directory")
    if not args.out and local_project is None and project_uuid is None and _executor_needs_out(executor):
        raise ValueError("--out is required for this executor")
    request = ExecutorRunRequest(
        executor_id=args.executor_id,
        out=Path(args.out) if args.out else "",
        project=local_project,
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
    rc = int(result.returncode or 0)
    if rc == 0 and project_uuid is not None and not args.dry_run:
        rc = _push_run_to_supabase(
            project_id=project_uuid,
            timeline_id=args.timeline_id,
            out_dir=Path(args.out),
            service_role=bool(getattr(args, "service_role", False)),
        )
    return rc


_UUID_RE = __import__("re").compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _project_uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    return value if _UUID_RE.match(value) else None


def _push_run_to_supabase(
    *,
    project_id: str,
    timeline_id: str,
    out_dir: Path,
    service_role: bool,
) -> int:
    """Push the run's hype.timeline.json (if produced) via SupabaseDataProvider."""

    timeline_path = out_dir / "hype.timeline.json"
    if not timeline_path.is_file():
        print(
            f"executors: --project {project_id} requested but {timeline_path} not produced by run; skipping push",
            file=sys.stderr,
        )
        return 0

    from astrid.core.reigh import env as reigh_env
    from astrid.core.reigh.data_provider import SupabaseDataProvider
    from astrid.timeline import Timeline

    timeline_blob = Timeline.load(timeline_path).to_json_data()
    provider = SupabaseDataProvider.from_env()
    if service_role:
        auth = ("service_role", reigh_env.resolve_service_role_key())
    else:
        auth = ("pat", reigh_env.resolve_pat())
    _, current_version = provider.load_timeline(project_id, timeline_id)

    def _mutator(_config, _version):
        return timeline_blob

    result = provider.save_timeline(
        timeline_id,
        _mutator,
        project_id=project_id,
        auth=auth,
        expected_version=current_version,
        retries=3,
        force=False,
    )
    print(
        f"pushed timeline {timeline_id} project_id={project_id} "
        f"new_version={result.new_version} attempts={result.attempts}"
    )
    return 0


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

        from astrid._paths import REPO_ROOT
        from astrid.threads.index import ThreadIndexStore

        index = ThreadIndexStore(Path(os.environ.get("ARTAGENTS_REPO_ROOT", REPO_ROOT))).read()
    except Exception:
        print("active_thread: unavailable")
        print("thread_details: python3 -m astrid thread show @active")
        return
    active = index.get("active_thread_id")
    thread = index.get("threads", {}).get(active) if isinstance(active, str) else None
    if isinstance(thread, dict):
        print(f"active_thread: {thread.get('label') or 'unlabeled'} ({active})")
    else:
        print("active_thread: none")
    print("thread_details: python3 -m astrid thread show @active")


if __name__ == "__main__":
    raise SystemExit(main())
