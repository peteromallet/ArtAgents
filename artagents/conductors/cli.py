"""Command-line interface for ArtAgents conductors."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .banodoco_catalog import BanodocoCatalogConfig
from .registry import ConductorRegistry, load_default_registry
from .runner import ConductorRunRequest, ConductorRunResult, ConductorRunnerError, run_conductor
from .schema import ConductorDefinition, ConductorValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parse_argv, passthrough = _split_run_passthrough(list(argv) if argv is not None else sys.argv[1:])
    args = parser.parse_args(parse_argv)
    if getattr(args, "command", None) == "run":
        args.conductor_args = passthrough
    try:
        registry = load_default_registry(banodoco_config=_banodoco_config_from_args(args))
        return int(args.handler(args, registry))
    except (KeyError, ConductorValidationError, ConductorRunnerError, ValueError) as exc:
        print(f"conductors: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py conductors",
        description="List, inspect, validate, and run ArtAgents conductors.",
    )
    parser.add_argument(
        "--banodoco-agent-conductors",
        action="store_true",
        help="Opt in to loading conductors from the Banodoco website catalog.",
    )
    parser.add_argument("--banodoco-catalog-url", help="Banodoco website catalog Edge Function URL.")
    parser.add_argument("--banodoco-cache-dir", help="Cache directory for git-backed Banodoco conductors.")
    parser.add_argument("--banodoco-refresh", action="store_true", help="Refresh cached git checkouts before loading Banodoco conductors.")
    parser.add_argument("--no-banodoco-defaults", action="store_true", help="Skip Banodoco catalog conductors marked default.")
    parser.add_argument("--no-banodoco-mandatory", action="store_true", help="Skip Banodoco catalog conductors marked mandatory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available conductors.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=("built_in", "external"), help="Filter conductors by kind.")
    list_parser.set_defaults(handler=_cmd_list)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one conductor.")
    inspect_parser.add_argument("conductor_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate conductor metadata.")
    validate_parser.add_argument("conductor_id", nargs="?")
    validate_parser.set_defaults(handler=_cmd_validate)

    run_parser = subparsers.add_parser("run", help="Run or dry-run one conductor.")
    run_parser.add_argument("conductor_id")
    run_parser.add_argument("--out", help="Output directory for runtime placeholders.")
    run_parser.add_argument("--brief", help="Brief path for runtime placeholders.")
    run_parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Conductor input value; may be repeated.")
    run_parser.add_argument("--dry-run", action="store_true", help="Plan commands without executing command runtimes.")
    run_parser.add_argument("--python-exec", help="Python executable for {python_exec} placeholders.")
    run_parser.add_argument("--verbose", action="store_true", help="Set verbose runtime context.")
    run_parser.set_defaults(handler=_cmd_run)
    return parser


def _banodoco_config_from_args(args: argparse.Namespace) -> BanodocoCatalogConfig:
    env_config = BanodocoCatalogConfig.from_env(conductors=True)
    enabled = bool(args.banodoco_agent_conductors or env_config.enabled)
    return BanodocoCatalogConfig(
        enabled=enabled,
        catalog_url=args.banodoco_catalog_url or env_config.catalog_url,
        include_defaults=False if args.no_banodoco_defaults else env_config.include_defaults,
        include_mandatory=False if args.no_banodoco_mandatory else env_config.include_mandatory,
        cache_dir=Path(args.banodoco_cache_dir).expanduser() if args.banodoco_cache_dir else env_config.cache_dir,
        refresh=bool(args.banodoco_refresh or env_config.refresh),
        timeout_seconds=env_config.timeout_seconds,
    )


def _cmd_list(args: argparse.Namespace, registry: ConductorRegistry) -> int:
    conductors = registry.list(kind=args.kind)
    if args.json:
        print(registry.to_json(kind=args.kind))
        return 0
    for conductor in conductors:
        print(f"{conductor.id}\t{conductor.kind}\t{conductor.name}")
    return 0


def _cmd_inspect(args: argparse.Namespace, registry: ConductorRegistry) -> int:
    conductor = registry.get(args.conductor_id)
    if args.json:
        print(conductor.to_json())
        return 0
    print(f"id: {conductor.id}")
    print(f"name: {conductor.name}")
    print(f"kind: {conductor.kind}")
    print(f"version: {conductor.version}")
    print(f"runtime: {conductor.runtime.kind}")
    if conductor.description:
        print(f"description: {conductor.description}")
    _print_ports("inputs", conductor.inputs)
    _print_outputs(conductor)
    if conductor.child_performers:
        print(f"child_performers: {', '.join(conductor.child_performers)}")
    if conductor.child_conductors:
        print(f"child_conductors: {', '.join(conductor.child_conductors)}")
    if conductor.runtime.command is not None:
        print(f"command: {shlex.join(conductor.runtime.command.argv)}")
    return 0


def _cmd_validate(args: argparse.Namespace, registry: ConductorRegistry) -> int:
    registry.validate_all()
    conductors = [registry.get(args.conductor_id)] if args.conductor_id else registry.list()
    if args.conductor_id:
        print(f"{args.conductor_id}: ok")
    else:
        print(f"{len(conductors)} conductor(s): ok")
    return 0


def _cmd_run(args: argparse.Namespace, registry: ConductorRegistry) -> int:
    request = ConductorRunRequest(
        conductor_id=args.conductor_id,
        out=Path(args.out) if args.out else None,
        inputs=_parse_input_values(args.input),
        brief=Path(args.brief) if args.brief else None,
        conductor_args=tuple(args.conductor_args),
        dry_run=bool(args.dry_run),
        python_exec=args.python_exec,
        verbose=bool(args.verbose),
    )
    result = run_conductor(request, registry)
    _print_run_result(result)
    return int(result.returncode or 0)


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


def _split_run_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    if not argv or argv[0] != "run" or "--" not in argv:
        return argv, []
    separator_index = argv.index("--")
    return argv[:separator_index], argv[separator_index + 1 :]


def _print_run_result(result: ConductorRunResult) -> None:
    commands = result.planned_commands or ((result.command,) if result.command else ())
    for command in commands:
        if command:
            print(shlex.join(command))
    if result.errors:
        for error in result.errors:
            print(f"{error.kind}: {error.message}", file=sys.stderr)


def _print_ports(label: str, ports: tuple[Any, ...]) -> None:
    if not ports:
        return
    print(f"{label}:")
    for port in ports:
        required = "required" if port.required else "optional"
        print(f"  - {port.name} ({port.type}, {required})")


def _print_outputs(conductor: ConductorDefinition) -> None:
    if not conductor.outputs:
        return
    print("outputs:")
    for output in conductor.outputs:
        placeholder = f", placeholder={output.placeholder}" if output.placeholder else ""
        print(f"  - {output.name} ({output.type}, {output.mode}{placeholder})")


if __name__ == "__main__":
    raise SystemExit(main())
