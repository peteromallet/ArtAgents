"""Command-line interface for ArtAgents elements."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from artagents._paths import REPO_ROOT
from artagents.core._search import (
    SearchRecord,
    search as run_search,
    short_description_or_truncated,
)

from .install import install_element
from .registry import ElementRegistryError, load_default_registry
from .schema import ELEMENT_KINDS, ElementDefinition, ElementValidationError


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
        prog="python3 -m artagents elements",
        description="List, inspect, validate, fork, and install ArtAgents render elements.",
    )
    parser.add_argument("--theme", help="Active theme id, theme directory, or path to theme.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available elements.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=ELEMENT_KINDS, help="Filter by element kind.")
    list_parser.add_argument("--no-describe", action="store_true", help="Omit the short_description column for legacy parsers.")
    list_parser.set_defaults(handler=_cmd_list)

    search_parser = subparsers.add_parser("search", help="Search elements by id, keywords, and descriptions.")
    search_parser.add_argument("terms", nargs="+", help="One or more search terms.")
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    search_parser.add_argument("--limit", type=int, default=25, help="Maximum number of hits (default 25).")
    search_parser.set_defaults(handler=_cmd_search)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one element.")
    inspect_parser.add_argument("kind", choices=ELEMENT_KINDS)
    inspect_parser.add_argument("element_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate element metadata.")
    validate_parser.add_argument("kind", choices=ELEMENT_KINDS, nargs="?")
    validate_parser.add_argument("element_id", nargs="?")
    validate_parser.set_defaults(handler=_cmd_validate)

    fork_parser = subparsers.add_parser("fork", help="Fork an element into the local pack (artagents/packs/local).")
    fork_parser.add_argument("kind", choices=ELEMENT_KINDS)
    fork_parser.add_argument("element_id")
    fork_parser.add_argument("--overwrite", action="store_true", help="Replace an existing local fork.")
    fork_parser.set_defaults(handler=_cmd_fork)

    install_parser = subparsers.add_parser("install", help="Plan or apply local dependency install for one element.")
    install_parser.add_argument("kind", choices=ELEMENT_KINDS)
    install_parser.add_argument("element_id")
    install_parser.add_argument("--apply", action="store_true", help="Run the local install commands. Default is dry-run.")
    install_parser.set_defaults(handler=_cmd_install)

    return parser


def _cmd_list(args: argparse.Namespace, registry: Any) -> int:
    elements = registry.list(kind=args.kind)
    if args.json:
        print(json.dumps({"elements": [element.to_dict() for element in elements]}, indent=2, sort_keys=True))
        return 0
    no_describe = bool(getattr(args, "no_describe", False))
    for element in elements:
        editability = "editable" if element.editable else "managed"
        if no_describe:
            print(f"{element.kind}\t{element.id}\t{element.source}\t{editability}")
        else:
            short = short_description_or_truncated(element.short_description, element.description)
            print(f"{element.kind}\t{element.id}\t{element.source}\t{editability}\t{short}")
    return 0


def _cmd_search(args: argparse.Namespace, registry: Any) -> int:
    records = [_element_search_record(element) for element in registry.list()]
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


def _element_search_record(element: ElementDefinition) -> SearchRecord:
    short = short_description_or_truncated(element.short_description, element.description)
    fields = {
        "id": element.id,
        "name": str(element.metadata.get("name") or element.metadata.get("label") or element.id),
        "short_description": element.short_description,
        "description": element.description,
        "keywords": " ".join(element.keywords),
    }
    return SearchRecord(id=element.id, kind=element.kind, short_description=short, fields=fields)


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
    if element.short_description:
        print(f"short_description: {element.short_description}")
    if element.description:
        print(f"description: {element.description}")
    if element.keywords:
        print(f"keywords: {', '.join(element.keywords)}")
    return 0


def _cmd_validate(args: argparse.Namespace, registry: Any) -> int:
    if args.kind and args.element_id:
        registry.get(args.kind, args.element_id)
        print(f"{args.kind}/{args.element_id}: ok")
        return 0
    elements = registry.list(kind=args.kind)
    print(f"{len(elements)} element(s): ok")
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


if __name__ == "__main__":
    raise SystemExit(main())
