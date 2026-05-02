"""Local-only install planning for element dependencies."""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from artagents._paths import REPO_ROOT

from .schema import ElementDefinition


class ElementInstallError(RuntimeError):
    """Raised when an element dependency install fails."""


@dataclass(frozen=True)
class ElementInstallPlan:
    element_id: str
    root: Path
    venv_path: Path | None
    node_prefix: Path | None
    commands: tuple[tuple[str, ...], ...]
    noop_reason: str | None = None

    def command_lines(self) -> tuple[str, ...]:
        return tuple(shlex.join(command) for command in self.commands)


@dataclass(frozen=True)
class ElementInstallResult:
    plan: ElementInstallPlan
    returncode: int = 0


def safe_element_install_id(element: ElementDefinition) -> str:
    raw = f"{element.kind}-{element.id}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-") or "element"


def build_element_install_plan(
    element: ElementDefinition,
    *,
    project_root: str | Path = REPO_ROOT,
) -> ElementInstallPlan:
    install_root = Path(project_root) / ".artagents" / "elements" / safe_element_install_id(element)
    commands: list[tuple[str, ...]] = []
    venv_path: Path | None = None
    node_prefix: Path | None = None
    if element.dependencies.python_requirements:
        venv_path = install_root / "venv"
        python_path = venv_path / "bin" / "python"
        commands.append(("uv", "venv", str(venv_path)))
        commands.append(("uv", "pip", "install", "--python", str(python_path), *element.dependencies.python_requirements))
    if element.dependencies.js_packages:
        node_prefix = install_root / "node"
        commands.append(("npm", "install", "--prefix", str(node_prefix), *element.dependencies.js_packages))
    if not commands:
        return ElementInstallPlan(
            element_id=element.id,
            root=install_root,
            venv_path=venv_path,
            node_prefix=node_prefix,
            commands=(),
            noop_reason="no dependencies declared",
        )
    return ElementInstallPlan(
        element_id=element.id,
        root=install_root,
        venv_path=venv_path,
        node_prefix=node_prefix,
        commands=tuple(commands),
    )


def install_element(
    element: ElementDefinition,
    *,
    project_root: str | Path = REPO_ROOT,
    dry_run: bool = True,
) -> ElementInstallResult:
    plan = build_element_install_plan(element, project_root=project_root)
    if dry_run or plan.noop_reason:
        return ElementInstallResult(plan=plan, returncode=0)
    plan.root.mkdir(parents=True, exist_ok=True)
    for command in plan.commands:
        completed = subprocess.run(command)
        if completed.returncode:
            raise ElementInstallError(f"element install command failed with {completed.returncode}: {shlex.join(command)}")
    return ElementInstallResult(plan=plan, returncode=0)
