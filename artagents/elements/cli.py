"""Command-line interface for ArtAgents elements."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from artagents._paths import REPO_ROOT

from .install import install_element
from .registry import ElementRegistryError, default_sources, load_default_registry
from .schema import ELEMENT_KINDS, ElementValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        registry = load_default_registry(active_theme=args.theme, project_root=REPO_ROOT)
        return int(args.handler(args, registry))
    except (KeyError, ElementRegistryError, ElementValidationError, ValueError) as exc:
        print(f"elements: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py elements",
        description="List, inspect, validate, sync, fork, install, and update ArtAgents render elements.",
    )
    parser.add_argument("--theme", help="Active theme id, theme directory, or path to theme.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available elements.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=ELEMENT_KINDS, help="Filter by element kind.")
    list_parser.set_defaults(handler=_cmd_list)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one element.")
    inspect_parser.add_argument("kind", choices=ELEMENT_KINDS)
    inspect_parser.add_argument("element_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate element metadata.")
    validate_parser.add_argument("kind", choices=ELEMENT_KINDS, nargs="?")
    validate_parser.add_argument("element_id", nargs="?")
    validate_parser.set_defaults(handler=_cmd_validate)

    sync_parser = subparsers.add_parser("sync", help="Materialize bundled defaults into .artagents/elements/managed.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Print actions without copying files.")
    sync_parser.set_defaults(handler=_cmd_sync)

    fork_parser = subparsers.add_parser("fork", help="Fork an element into .artagents/elements/overrides.")
    fork_parser.add_argument("kind", choices=ELEMENT_KINDS)
    fork_parser.add_argument("element_id")
    fork_parser.add_argument("--overwrite", action="store_true", help="Replace an existing override.")
    fork_parser.set_defaults(handler=_cmd_fork)

    install_parser = subparsers.add_parser("install", help="Plan or apply local dependency install for one element.")
    install_parser.add_argument("kind", choices=ELEMENT_KINDS)
    install_parser.add_argument("element_id")
    install_parser.add_argument("--apply", action="store_true", help="Run the local install commands. Default is dry-run.")
    install_parser.set_defaults(handler=_cmd_install)

    update_parser = subparsers.add_parser("update", help="Refresh managed defaults without overwriting overrides.")
    update_parser.add_argument("--dry-run", action="store_true", help="Print actions without copying files.")
    update_parser.set_defaults(handler=_cmd_update)
    return parser


def _cmd_list(args: argparse.Namespace, registry: Any) -> int:
    elements = registry.list(kind=args.kind)
    if args.json:
        print(json.dumps({"elements": [element.to_dict() for element in elements]}, indent=2, sort_keys=True))
        return 0
    for element in elements:
        print(f"{element.kind}\t{element.id}\t{element.source}\t{'editable' if element.editable else 'managed'}")
    return 0


def _cmd_inspect(args: argparse.Namespace, registry: Any) -> int:
    element = registry.get(args.kind, args.element_id)
    if args.json:
        print(element.to_json())
        return 0
    print(f"id: {element.id}")
    print(f"kind: {element.kind}")
    print(f"source: {element.source}")
    print(f"editable: {str(element.editable).lower()}")
    print(f"root: {element.root}")
    print(f"fork_target: {element.fork_target}")
    return 0


def _cmd_validate(args: argparse.Namespace, registry: Any) -> int:
    if args.kind and args.element_id:
        registry.get(args.kind, args.element_id)
        print(f"{args.kind}/{args.element_id}: ok")
        return 0
    elements = registry.list(kind=args.kind)
    print(f"{len(elements)} element(s): ok")
    return 0


def _cmd_sync(args: argparse.Namespace, registry: Any) -> int:
    del registry
    actions = _sync_managed_defaults(dry_run=bool(args.dry_run), overwrite=False)
    _print_actions(actions)
    return 0


def _cmd_update(args: argparse.Namespace, registry: Any) -> int:
    del registry
    actions = _sync_managed_defaults(dry_run=bool(args.dry_run), overwrite=True)
    _print_actions(actions)
    return 0


def _cmd_fork(args: argparse.Namespace, registry: Any) -> int:
    target = registry.fork(args.kind, args.element_id, project_root=REPO_ROOT, overwrite=bool(args.overwrite))
    print(f"forked: {target}")
    return 0


def _cmd_install(args: argparse.Namespace, registry: Any) -> int:
    element = registry.get(args.kind, args.element_id)
    result = install_element(element, project_root=REPO_ROOT, dry_run=not bool(args.apply))
    plan = result.plan
    if plan.noop_reason:
        print(f"{element.kind}/{element.id}: no install needed: {plan.noop_reason}")
        return result.returncode
    print(f"root: {plan.root}")
    if plan.venv_path is not None:
        print(f"venv: {plan.venv_path}")
    if plan.node_prefix is not None:
        print(f"node: {plan.node_prefix}")
    for line in plan.command_lines():
        print(line)
    if not args.apply:
        print("dry-run: pass --apply to run these local install commands")
    return result.returncode


def _sync_managed_defaults(*, dry_run: bool, overwrite: bool, project_root: Path | None = None) -> list[str]:
    project_root = project_root or REPO_ROOT
    bundled_root = None
    for source in default_sources(project_root=project_root):
        if source.name == "bundled":
            bundled_root = source.root
            break
    if bundled_root is None:
        raise ElementRegistryError("bundled element root is not configured")
    managed_root = project_root / ".artagents" / "elements" / "managed"
    override_root = project_root / ".artagents" / "elements" / "overrides"
    actions: list[str] = []
    for kind in ELEMENT_KINDS:
        source_kind = bundled_root / kind
        if not source_kind.is_dir():
            continue
        for source_element in sorted(source_kind.iterdir(), key=lambda path: path.name):
            if not source_element.is_dir():
                continue
            target = managed_root / kind / source_element.name
            override = override_root / kind / source_element.name
            if override.exists():
                actions.append(f"skip override: {override}")
                continue
            if target.exists() and not overwrite:
                actions.append(f"exists: {target}")
                continue
            if dry_run:
                actions.append(("update: " if target.exists() else "sync: ") + str(target))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source_element, target)
            actions.append(("updated: " if overwrite else "synced: ") + str(target))
    if not actions:
        actions.append("no managed defaults to sync")
    return actions


def _print_actions(actions: list[str]) -> None:
    for action in actions:
        print(action)


if __name__ == "__main__":
    raise SystemExit(main())
