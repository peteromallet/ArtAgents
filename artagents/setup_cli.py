"""Local setup planner for ArtAgents."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from artagents._paths import REPO_ROOT
from artagents.elements.cli import _sync_managed_defaults
from artagents.elements.install import install_element
from artagents.elements.registry import load_default_registry as load_element_registry


@dataclass(frozen=True)
class SetupStep:
    name: str
    status: str
    detail: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m artagents setup", description="Plan or apply ArtAgents local setup.")
    parser.add_argument("--apply", action="store_true", help="Apply local setup mutations. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable setup output.")
    return parser


def plan_setup(*, apply: bool = False, project_root: str | Path | None = None) -> tuple[SetupStep, ...]:
    root = Path(project_root or REPO_ROOT)
    steps: list[SetupStep] = []
    steps.append(
        SetupStep(
            name="mode",
            status="apply" if apply else "dry-run",
            detail="local mutations enabled" if apply else "no files or dependencies will be changed",
        )
    )
    for action in _sync_managed_defaults(dry_run=not apply, overwrite=False, project_root=root):
        steps.append(SetupStep(name="elements sync", status="applied" if apply else "planned", detail=action))

    registry = load_element_registry(project_root=root)
    for element in registry.list():
        result = install_element(element, project_root=root, dry_run=not apply)
        plan = result.plan
        if plan.noop_reason:
            steps.append(SetupStep(name="elements install", status="skipped", detail=f"{element.kind}/{element.id}: {plan.noop_reason}"))
            continue
        status = "applied" if apply else "planned"
        details = "; ".join(plan.command_lines())
        steps.append(SetupStep(name="elements install", status=status, detail=f"{element.kind}/{element.id}: {details}"))
    return tuple(steps)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    steps = plan_setup(apply=bool(args.apply))
    if args.json:
        payload = {
            "applied": bool(args.apply),
            "steps": [asdict(step) for step in steps],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("ArtAgents setup")
    if not args.apply:
        print("dry-run: pass --apply to sync managed defaults and run local element install commands")
    for step in steps:
        print(f"[{step.status}] {step.name}: {step.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
