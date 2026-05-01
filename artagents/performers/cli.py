"""Command-line interface for ArtAgents performers."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .banodoco_catalog import BanodocoCatalogConfig
from .install import install_performer
from .registry import PerformerRegistry, load_default_registry
from .runner import PerformerRunRequest, check_performer_binaries, run_performer
from .schema import PerformerDefinition, PerformerValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_default_registry(_banodoco_config_from_args(args))
        return int(args.handler(args, registry))
    except (KeyError, PerformerValidationError, ValueError) as exc:
        print(f"performers: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.py performers", description="List, inspect, validate, and run ArtAgents performers.")
    parser.add_argument("--banodoco-agent-performers", action="store_true", help="Opt in to loading agent performers from the Banodoco website catalog.")
    parser.add_argument("--banodoco-catalog-url", help="Banodoco website agent-performer catalog Edge Function URL.")
    parser.add_argument("--banodoco-cache-dir", help="Cache directory for git-backed Banodoco agent performers.")
    parser.add_argument("--banodoco-refresh", action="store_true", help="Refresh cached git checkouts before loading Banodoco agent performers.")
    parser.add_argument("--no-banodoco-defaults", action="store_true", help="Skip Banodoco catalog performers marked default.")
    parser.add_argument("--no-banodoco-mandatory", action="store_true", help="Skip Banodoco catalog performers marked mandatory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available performers.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=("built_in", "external"), help="Filter performers by kind.")
    list_parser.set_defaults(handler=_cmd_list)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one performer.")
    inspect_parser.add_argument("performer_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate performer metadata.")
    validate_parser.add_argument("performer_id", nargs="?")
    validate_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    validate_parser.set_defaults(handler=_cmd_validate)

    install_parser = subparsers.add_parser("install", help="Install dependencies for one performer.")
    install_parser.add_argument("performer_id")
    install_parser.add_argument("--dry-run", action="store_true", help="Print install commands without executing them.")
    install_parser.set_defaults(handler=_cmd_install)

    run_parser = subparsers.add_parser("run", help="Run or dry-run one performer.")
    run_parser.add_argument("performer_id")
    run_parser.add_argument("--out", help="Output directory for runtime placeholders.")
    run_parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Performer input value; may be repeated.")
    run_parser.add_argument("--brief", help="Brief path for built-in legacy context synthesis.")
    run_parser.add_argument("--dry-run", action="store_true", help="Build and print the command without executing it.")
    run_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    run_parser.add_argument("--python-exec", help="Python executable for {python_exec} placeholders.")
    run_parser.add_argument("--verbose", action="store_true", help="Stream subprocess output for built-in legacy steps.")
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
    enabled = bool(args.banodoco_agent_performers or env_config.enabled)
    return BanodocoCatalogConfig(
        enabled=enabled,
        catalog_url=args.banodoco_catalog_url or env_config.catalog_url,
        include_defaults=False if args.no_banodoco_defaults else env_config.include_defaults,
        include_mandatory=False if args.no_banodoco_mandatory else env_config.include_mandatory,
        cache_dir=Path(args.banodoco_cache_dir).expanduser() if args.banodoco_cache_dir else env_config.cache_dir,
        refresh=bool(args.banodoco_refresh or env_config.refresh),
        timeout_seconds=env_config.timeout_seconds,
    )


def _cmd_list(args: argparse.Namespace, registry: PerformerRegistry) -> int:
    performers = registry.list(kind=args.kind)
    if args.json:
        print(registry.to_json(kind=args.kind))
        return 0
    for performer in performers:
        print(f"{performer.id}\t{performer.kind}\t{performer.name}")
    return 0


def _cmd_inspect(args: argparse.Namespace, registry: PerformerRegistry) -> int:
    performer = registry.get(args.performer_id)
    if args.json:
        print(performer.to_json())
        return 0
    print(f"id: {performer.id}")
    print(f"name: {performer.name}")
    print(f"kind: {performer.kind}")
    print(f"version: {performer.version}")
    if performer.description:
        print(f"description: {performer.description}")
    _print_ports("inputs", performer.inputs)
    _print_outputs(performer)
    if performer.command is not None:
        print(f"command: {shlex.join(performer.command.argv)}")
    print(f"cache: {performer.cache.mode}")
    if performer.cache.sentinels:
        print(f"cache_sentinels: {', '.join(performer.cache.sentinels)}")
    if performer.isolation.binaries:
        print(f"binaries: {', '.join(performer.isolation.binaries)}")
    return 0


def _cmd_validate(args: argparse.Namespace, registry: PerformerRegistry) -> int:
    registry.validate_all()
    performers = [registry.get(args.performer_id)] if args.performer_id else registry.list()
    missing_by_performer: dict[str, tuple[str, ...]] = {}
    if args.check_binaries:
        for performer in performers:
            missing = check_performer_binaries(performer)
            if missing:
                missing_by_performer[performer.id] = missing
    if missing_by_performer:
        for performer_id, missing in missing_by_performer.items():
            print(f"{performer_id}: missing binaries: {', '.join(missing)}", file=sys.stderr)
        return 1
    if args.performer_id:
        print(f"{args.performer_id}: ok")
    else:
        print(f"{len(performers)} performer(s): ok")
    return 0


def _cmd_install(args: argparse.Namespace, registry: PerformerRegistry) -> int:
    performer = registry.get(args.performer_id)
    result = install_performer(performer, dry_run=bool(args.dry_run))
    plan = result.plan
    if plan.noop_reason:
        print(f"{performer.id}: no install needed: {plan.noop_reason}")
        return result.returncode
    if plan.environment_path is not None:
        print(f"env: {plan.environment_path}")
    if plan.python_path is not None:
        print(f"python: {plan.python_path}")
    for command in plan.commands:
        print(shlex.join(command))
    return result.returncode


def _cmd_run(args: argparse.Namespace, registry: PerformerRegistry) -> int:
    if args.performer_id != "upload.youtube" and not args.out:
        raise ValueError("--out is required for this performer")
    request = PerformerRunRequest(
        performer_id=args.performer_id,
        out=Path(args.out) if args.out else "",
        inputs=_run_inputs(args),
        brief=Path(args.brief) if args.brief else None,
        dry_run=bool(args.dry_run),
        check_binaries=bool(args.check_binaries),
        python_exec=args.python_exec,
        verbose=bool(args.verbose),
    )
    result = run_performer(request, registry)
    if result.missing_binaries:
        print(f"{args.performer_id}: missing binaries: {', '.join(result.missing_binaries)}", file=sys.stderr)
        return 1
    if result.skipped:
        print(f"{args.performer_id}: skipped: {result.skipped_reason}")
        return 0
    if result.command:
        print(shlex.join(result.command))
    if result.payload:
        print(json.dumps(dict(result.payload), separators=(",", ":"), sort_keys=True))
    return int(result.returncode or 0)


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


def _print_ports(label: str, ports: tuple[Any, ...]) -> None:
    if not ports:
        return
    print(f"{label}:")
    for port in ports:
        required = "required" if port.required else "optional"
        print(f"  - {port.name} ({port.type}, {required})")


def _print_outputs(performer: PerformerDefinition) -> None:
    if not performer.outputs:
        return
    print("outputs:")
    for output in performer.outputs:
        placeholder = f", placeholder={output.placeholder}" if output.placeholder else ""
        print(f"  - {output.name} ({output.type}, {output.mode}{placeholder})")


if __name__ == "__main__":
    raise SystemExit(main())
