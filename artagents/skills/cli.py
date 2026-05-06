"""CLI for ``python3 -m artagents skills``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import doctor as doctor_fn
from . import install as install_fn
from . import list_state, sync as sync_fn, uninstall as uninstall_fn
from .harnesses import ADAPTERS

HARNESS_CHOICES = ("claude", "codex", "hermes", "all")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args))
    except (KeyError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"skills: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m artagents skills",
        description="Install the ArtAgents skills layer into supported agent harnesses (claude, codex, hermes).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List installable packs and per-harness install state.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(handler=_cmd_list)

    install_parser = subparsers.add_parser("install", help="Install pack(s) into harness(es).")
    install_parser.add_argument("pack", nargs="?", help="Pack id, or omit with --all.")
    install_parser.add_argument("--all", action="store_true", help="Install every available pack.")
    install_parser.add_argument("--harness", action="append", choices=HARNESS_CHOICES, help="One or more harnesses (default: all).")
    install_parser.add_argument("--mechanism", choices=("symlink", "external-dir"), default="symlink", help="Hermes-only mechanism (default: symlink).")
    install_parser.add_argument("--force", action="store_true", help="Overwrite existing non-symlink targets.")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    install_parser.set_defaults(handler=_cmd_install)

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove pack(s) from harness(es).")
    uninstall_parser.add_argument("pack", nargs="?")
    uninstall_parser.add_argument("--all", action="store_true")
    uninstall_parser.add_argument("--harness", action="append", choices=HARNESS_CHOICES)
    uninstall_parser.add_argument("--dry-run", action="store_true")
    uninstall_parser.add_argument("--json", action="store_true")
    uninstall_parser.set_defaults(handler=_cmd_uninstall)

    sync_parser = subparsers.add_parser("sync", help="Re-install every pack into every detected harness; prune orphans.")
    sync_parser.add_argument("--mechanism", choices=("symlink", "external-dir"), default="symlink")
    sync_parser.add_argument("--force", action="store_true")
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--json", action="store_true")
    sync_parser.set_defaults(handler=_cmd_sync)

    doctor_parser = subparsers.add_parser("doctor", help="Verify symlinks, fenced block, frontmatter, and lint.")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument(
        "--heal",
        action="store_true",
        help="Rewrite the state file from filesystem reality where they disagree.",
    )
    doctor_parser.set_defaults(handler=_cmd_doctor)

    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    report = list_state()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    detected = ", ".join(report["detected"]) or "(none)"
    print(f"detected harnesses: {detected}")
    for item in report["packs"]:
        states = []
        for harness in ADAPTERS:
            entry = item["harnesses"][harness]
            if entry.get("drift"):
                mark = "~"
            elif entry["installed"]:
                mark = "x"
            elif entry["detected"]:
                mark = "-"
            else:
                mark = " "
            states.append(f"{harness}[{mark}]")
        print(f"  {item['pack_id']:<12} {' '.join(states)}  {item['short_description']}")
    return 0


def _resolve_packs(args: argparse.Namespace) -> list[str] | None:
    if getattr(args, "all", False):
        return None
    if not args.pack:
        raise ValueError("specify a pack id or pass --all")
    return [args.pack]


def _resolve_harness_arg(args: argparse.Namespace) -> list[str] | None:
    raw = getattr(args, "harness", None) or []
    if not raw or "all" in raw:
        return None
    return list(raw)


def _cmd_install(args: argparse.Namespace) -> int:
    pack_ids = _resolve_packs(args)
    harness_names = _resolve_harness_arg(args)
    report = install_fn(
        pack_ids=pack_ids,
        harness_names=harness_names,
        mechanism=args.mechanism,
        force=args.force,
        dry_run=args.dry_run,
    )
    return _emit_report(report, args)


def _cmd_uninstall(args: argparse.Namespace) -> int:
    pack_ids = _resolve_packs(args)
    harness_names = _resolve_harness_arg(args)
    report = uninstall_fn(pack_ids=pack_ids, harness_names=harness_names, dry_run=args.dry_run)
    return _emit_report(report, args)


def _cmd_sync(args: argparse.Namespace) -> int:
    report = sync_fn(mechanism=args.mechanism, force=args.force, dry_run=args.dry_run)
    return _emit_report(report, args)


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor_fn(heal=getattr(args, "heal", False))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        detected = ", ".join(report["detected"]) or "(none)"
        print(f"detected: {detected}")
        for finding in report["lint"]:
            print(f"lint  {finding['pack']}: {finding['finding']}")
        for drift in report.get("drift", []):
            print(f"  [drift] {drift['harness']:<7} {drift['pack']:<12} {drift['message']}")
        for healed in report.get("healed", []):
            print(f"  [heal]  {healed['harness']:<7} {healed['pack']:<12} {healed['action']}")
        for entry in report["results"]:
            mark = "ok" if entry["ok"] else "FAIL"
            print(f"  [{mark}] {entry['harness']:<7} {entry['pack']:<12} {entry['message']}")
    failures = sum(1 for r in report["results"] if not r["ok"]) + len(report["lint"])
    # Drift not yet healed counts as a soft failure; healed drift does not.
    if not getattr(args, "heal", False):
        failures += len(report.get("drift", []))
    return 0 if failures == 0 else 1


def _emit_report(report: dict[str, Any], args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if not report["actions"]:
        print("no detected harnesses; nothing to do")
        return 0
    for action in report["actions"]:
        print(f"[{action['harness']}]")
        for step in action["steps"]:
            print(f"  {step['description']}")
    return 0


__all__ = ["build_parser", "main"]
