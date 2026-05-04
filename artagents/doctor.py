"""Environment diagnostics for ArtAgents."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from artagents._paths import REPO_ROOT


Status = str


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: Status
    detail: str
    required: bool = True

    def failed(self, *, strict_optional: bool = False) -> bool:
        if self.status == "fail":
            return True
        return strict_optional and not self.required and self.status == "warn"


def run_checks(*, optional_binaries: tuple[str, ...] = ("ffmpeg", "npx", "uv", "npm")) -> tuple[DoctorCheck, ...]:
    checks: list[DoctorCheck] = []
    checks.append(_check_python_version())
    checks.append(_check_required_imports())
    executor_registry = _capture_check("executor registry", _check_executor_registry)
    checks.append(executor_registry)
    checks.append(_capture_check("orchestrator registry", _check_orchestrator_registry))
    checks.append(_capture_check("element registry", _check_element_registry))
    checks.append(_capture_check("repo structure", _check_repo_structure))
    checks.append(_capture_check("vibecomfy metadata", _check_vibecomfy_metadata))
    checks.append(_capture_check("remotion config", _check_remotion_config))
    checks.append(_capture_check("timeline catalog", _check_timeline_catalog))
    checks.append(_check_projects_root())
    for binary in optional_binaries:
        checks.append(_check_optional_binary(binary))
    return tuple(checks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m artagents doctor", description="Check the ArtAgents environment.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable diagnostics.")
    parser.add_argument(
        "--strict-optional",
        action="store_true",
        help="Treat missing optional external binaries as failures.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = run_checks()
    failed = any(check.failed(strict_optional=args.strict_optional) for check in checks)
    if args.json:
        payload = {
            "ok": not failed,
            "checks": [asdict(check) for check in checks],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("ArtAgents doctor")
        for check in checks:
            print(f"[{check.status}] {check.name}: {check.detail}")
    return 1 if failed else 0


def _capture_check(name: str, fn: Callable[[], str]) -> DoctorCheck:
    try:
        return DoctorCheck(name=name, status="ok", detail=fn())
    except Exception as exc:  # pragma: no cover - detail shape is tested through mocks.
        return DoctorCheck(name=name, status="fail", detail=str(exc) or exc.__class__.__name__)


def load_executor_registry():
    from artagents.core.executor.registry import load_default_registry

    return load_default_registry()


def load_orchestrator_registry(*, executor_registry=None):
    from artagents.core.orchestrator.registry import load_default_registry

    return load_default_registry(executor_registry=executor_registry)


def load_element_registry(*, project_root: Path):
    from artagents.core.element.registry import load_default_registry

    return load_default_registry(project_root=project_root)


def _check_python_version() -> DoctorCheck:
    version = sys.version_info
    required = (3, 10)
    if version < required:
        return DoctorCheck(
            name="python",
            status="fail",
            detail=f"Python {required[0]}.{required[1]}+ required; found {version.major}.{version.minor}.{version.micro}",
        )
    return DoctorCheck(name="python", status="ok", detail=f"{version.major}.{version.minor}.{version.micro}")


def _check_required_imports() -> DoctorCheck:
    modules = (
        "artagents.timeline",
        "artagents.core.element.registry",
        "artagents.core.executor.registry",
        "artagents.core.orchestrator.registry",
        "artagents.core.project",
    )
    for module in modules:
        importlib.import_module(module)
    return DoctorCheck(name="required imports", status="ok", detail=f"{len(modules)} import(s) ok")


def _check_executor_registry() -> str:
    registry = load_executor_registry()
    count = len(registry.list())
    if count == 0:
        raise RuntimeError("no executors discovered")
    return f"{count} executor(s)"


def _check_orchestrator_registry() -> str:
    executor_registry = load_executor_registry()
    registry = load_orchestrator_registry(executor_registry=executor_registry)
    count = len(registry.list())
    if count == 0:
        raise RuntimeError("no orchestrators discovered")
    return f"{count} orchestrator(s)"


def _check_element_registry() -> str:
    registry = load_element_registry(project_root=REPO_ROOT)
    counts = {kind: len(registry.list(kind=kind)) for kind in ("effects", "animations", "transitions")}
    missing = [kind for kind, count in counts.items() if count == 0]
    if missing:
        raise RuntimeError(f"no elements discovered for: {', '.join(missing)}")
    return ", ".join(f"{kind}={count}" for kind, count in counts.items())


def _check_repo_structure() -> str:
    from artagents.structure import validate_repo_structure

    report = validate_repo_structure(REPO_ROOT)
    if not report.ok:
        raise RuntimeError("; ".join(report.errors))
    return "canonical folders ok"


def _check_vibecomfy_metadata() -> str:
    registry = load_executor_registry()
    run = registry.get("external.vibecomfy.run")
    metadata = run.metadata
    required = {
        "pack_id": "vibecomfy",
        "homepage": "https://github.com/peteromallet/VibeComfy",
        "catalog_source": "none_declared",
    }
    for key, expected in required.items():
        if metadata.get(key) != expected:
            raise RuntimeError(f"metadata[{key!r}] is {metadata.get(key)!r}, expected {expected!r}")
    if metadata.get("workflows") != [] or metadata.get("nodes") != [] or metadata.get("prompts") != []:
        raise RuntimeError("VibeComfy catalog metadata must be explicit empty lists when none are declared")
    if metadata.get("workflow_input_contract", {}).get("name") != "workflow":
        raise RuntimeError("missing workflow input contract")
    if not run.isolation.network:
        raise RuntimeError("VibeComfy run executor should declare network access")
    return "external.vibecomfy.run metadata visible"


def _check_remotion_config() -> str:
    paths = (
        REPO_ROOT / "remotion" / "remotion.config.ts",
        REPO_ROOT / "remotion" / "webpack-alias.mjs",
        REPO_ROOT / "remotion" / "tsconfig.json",
    )
    missing = [str(path.relative_to(REPO_ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing Remotion config: {', '.join(missing)}")
    return f"{len(paths)} file(s) present"


def _check_timeline_catalog() -> str:
    from artagents.core.element.catalog import list_animation_ids, list_effect_ids, list_transition_ids

    effects = set(list_effect_ids())
    animations = set(list_animation_ids())
    transitions = set(list_transition_ids())
    expected = [
        ("effect", "text-card", effects),
        ("animation", "fade", animations),
        ("transition", "cross-fade", transitions),
    ]
    missing = [f"{kind}:{item}" for kind, item, values in expected if item not in values]
    if missing:
        raise RuntimeError(f"missing timeline catalog ids: {', '.join(missing)}")
    return f"effects={len(effects)}, animations={len(animations)}, transitions={len(transitions)}"


def _check_projects_root() -> DoctorCheck:
    from artagents.core.project.paths import PROJECTS_ROOT_ENV, resolve_projects_root

    projects_root = resolve_projects_root()
    detail = f"{projects_root} ({PROJECTS_ROOT_ENV} override supported)"
    if projects_root.is_dir():
        return DoctorCheck(name="projects root", status="ok", detail=detail, required=False)
    return DoctorCheck(
        name="projects root",
        status="warn",
        detail=f"{detail}; run `python3 -m artagents setup --apply` to create it",
        required=False,
    )


def _check_optional_binary(binary: str) -> DoctorCheck:
    found = shutil.which(binary)
    if found is None:
        return DoctorCheck(name=f"optional binary {binary}", status="warn", detail="not found on PATH", required=False)
    return DoctorCheck(name=f"optional binary {binary}", status="ok", detail=str(Path(found)), required=False)


if __name__ == "__main__":
    raise SystemExit(main())
