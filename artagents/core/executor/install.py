"""Explicit installation helpers for ArtAgents executors."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from json import loads
from pathlib import Path

from .schema import ExecutorDefinition, ExecutorValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]


class ExecutorInstallError(ExecutorValidationError):
    """Raised when executor dependency installation cannot be prepared."""


@dataclass(frozen=True)
class GitExecutorSource:
    repo_url: str
    manifest_path: str
    expected_executor_id: str
    commit_sha: str | None = None
    tag: str | None = None
    branch: str | None = None
    source_ref: str | None = None
    install_subdir: str | None = None


@dataclass(frozen=True)
class ExecutorInstallPlan:
    executor_id: str
    kind: str
    environment_path: Path | None
    python_path: Path | None
    commands: tuple[tuple[str, ...], ...] = ()
    noop_reason: str = ""


@dataclass(frozen=True)
class ExecutorInstallResult:
    plan: ExecutorInstallPlan
    dry_run: bool = False
    returncode: int = 0


def executor_environment_path(executor: ExecutorDefinition) -> Path:
    """Return the deterministic repo-local virtualenv path for a executor."""

    return REPO_ROOT / ".artagents" / "executors" / _safe_executor_id(_executor_install_id(executor)) / "venv"


def executor_python_path(executor: ExecutorDefinition) -> Path:
    """Return the Python executable path inside a executor virtualenv."""

    env_path = executor_environment_path(executor)
    if sys.platform == "win32":
        return env_path / "Scripts" / "python.exe"
    return env_path / "bin" / "python"


def build_executor_install_plan(executor: ExecutorDefinition) -> ExecutorInstallPlan:
    """Build uv commands for explicit executor installation."""

    if executor.kind == "built_in":
        return ExecutorInstallPlan(
            executor_id=executor.id,
            kind=executor.kind,
            environment_path=None,
            python_path=None,
            noop_reason="built-in executors use the host Python environment",
        )
    if executor.kind != "external":
        raise ExecutorInstallError(f"unsupported executor kind {executor.kind!r}")

    env_path = executor_environment_path(executor)
    python_path = executor_python_path(executor)
    commands: list[tuple[str, ...]] = [("uv", "venv", str(env_path))]
    dependency_command = _dependency_install_command(executor, python_path)
    if dependency_command is not None:
        commands.append(dependency_command)
    return ExecutorInstallPlan(
        executor_id=executor.id,
        kind=executor.kind,
        environment_path=env_path,
        python_path=python_path,
        commands=tuple(commands),
    )


def install_executor(executor: ExecutorDefinition, *, dry_run: bool = False) -> ExecutorInstallResult:
    """Install dependencies for a executor, or return the dry-run plan."""

    plan = build_executor_install_plan(executor)
    if dry_run or not plan.commands:
        return ExecutorInstallResult(plan=plan, dry_run=dry_run)
    for command in plan.commands:
        completed = subprocess.run(list(command), check=False)
        if completed.returncode != 0:
            return ExecutorInstallResult(plan=plan, dry_run=False, returncode=completed.returncode)
    return ExecutorInstallResult(plan=plan, dry_run=False)


def fetch_git_executor_manifest(
    source: GitExecutorSource,
    *,
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> dict:
    """Fetch a git-backed executor manifest and verify its catalog identity."""

    return _fetch_git_manifest(
        _GitManifestSource(
            repo_url=source.repo_url,
            manifest_path=source.manifest_path,
            expected_id=source.expected_executor_id,
            commit_sha=source.commit_sha,
            tag=source.tag,
            branch=source.branch,
            source_ref=source.source_ref,
            install_subdir=source.install_subdir,
        ),
        cache_root=cache_dir or (REPO_ROOT / ".artagents" / "banodoco-executors"),
        refresh=refresh,
        label="executor",
    )


@dataclass(frozen=True)
class _GitManifestSource:
    repo_url: str
    manifest_path: str
    expected_id: str
    commit_sha: str | None = None
    tag: str | None = None
    branch: str | None = None
    source_ref: str | None = None
    install_subdir: str | None = None


def _fetch_git_manifest(
    source: _GitManifestSource,
    *,
    cache_root: Path,
    refresh: bool,
    label: str,
) -> dict:
    _validate_git_manifest_source(source, label=label)
    checkout = cache_root / _safe_manifest_source_dir(source)
    if refresh and checkout.exists():
        shutil.rmtree(checkout.parent)
    checkout.parent.mkdir(parents=True, exist_ok=True)

    if not checkout.exists():
        _clone_git_manifest_source(source, checkout)
    elif refresh:
        _run_git(("git", "-C", str(checkout), "fetch", "--tags", "--prune"))
        _checkout_git_manifest_ref(source, checkout)

    manifest_path = _safe_child_path(checkout, source.manifest_path)
    if not manifest_path.is_file():
        raise ExecutorInstallError(f"git {label} manifest not found: {manifest_path}")
    try:
        manifest = loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ExecutorInstallError(f"invalid git {label} manifest JSON: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ExecutorInstallError(f"git {label} manifest must be a JSON object")
    manifest_id = manifest.get("id")
    if manifest_id != source.expected_id:
        raise ExecutorInstallError(
            f"git {label} identity mismatch: expected {source.expected_id!r}, fetched {manifest_id!r}"
        )
    return manifest


def _dependency_install_command(executor: ExecutorDefinition, python_path: Path) -> tuple[str, ...] | None:
    pyproject_file = _metadata_path(executor, "pyproject_file")
    if pyproject_file is not None:
        install_target = _metadata_path(executor, "executor_root") or pyproject_file.parent
        return ("uv", "pip", "install", "--python", str(python_path), str(install_target))

    requirements_file = _metadata_path(executor, "requirements_file")
    if requirements_file is not None:
        return ("uv", "pip", "install", "--python", str(python_path), "-r", str(requirements_file))

    if executor.isolation.requirements:
        return ("uv", "pip", "install", "--python", str(python_path), *executor.isolation.requirements)
    return None


def _metadata_path(executor: ExecutorDefinition, key: str) -> Path | None:
    raw = executor.metadata.get(key)
    if not isinstance(raw, str) or not raw:
        return None
    return Path(raw).expanduser().resolve()


def _safe_executor_id(executor_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", executor_id)


def _executor_install_id(executor: ExecutorDefinition) -> str:
    pack_id = executor.metadata.get("pack_id")
    if isinstance(pack_id, str) and pack_id:
        return pack_id
    return executor.id


def _validate_git_manifest_source(source: _GitManifestSource, *, label: str) -> None:
    refs = [source.commit_sha, source.tag, source.branch, source.source_ref]
    if sum(1 for ref in refs if ref) != 1:
        raise ExecutorInstallError(f"git {label} source must specify exactly one of commit_sha, tag, branch, or source_ref")
    if not source.repo_url.strip():
        raise ExecutorInstallError(f"git {label} source repo_url is required")
    _safe_relative_path(source.manifest_path, "manifest_path")
    if source.install_subdir:
        _safe_relative_path(source.install_subdir, "install_subdir")


def _safe_manifest_source_dir(source: _GitManifestSource) -> Path:
    ref = source.commit_sha or source.tag or source.branch or source.source_ref or ""
    digest = sha256(f"{source.repo_url}\n{ref}\n{source.manifest_path}".encode("utf-8")).hexdigest()[:16]
    return Path(_safe_executor_id(source.expected_id)) / digest / "repo"


def _clone_git_manifest_source(source: _GitManifestSource, checkout: Path) -> None:
    checkout.parent.mkdir(parents=True, exist_ok=True)
    if source.commit_sha:
        _run_git(("git", "clone", "--filter=blob:none", source.repo_url, str(checkout)))
        _checkout_git_manifest_ref(source, checkout)
        return
    ref = source.tag or source.branch or source.source_ref
    assert ref is not None
    _run_git(("git", "clone", "--depth", "1", "--branch", ref, source.repo_url, str(checkout)))


def _checkout_git_manifest_ref(source: _GitManifestSource, checkout: Path) -> None:
    ref = source.commit_sha or source.tag or source.branch or source.source_ref
    assert ref is not None
    _run_git(("git", "-C", str(checkout), "checkout", "--detach", ref))


def _run_git(command: tuple[str, ...]) -> None:
    completed = subprocess.run(list(command), check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise ExecutorInstallError(f"command failed: {' '.join(command)}{suffix}")


def _safe_child_path(root: Path, relative: str) -> Path:
    relative_path = _safe_relative_path(relative, "manifest_path")
    child = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if root_resolved != child and root_resolved not in child.parents:
        raise ExecutorInstallError("manifest_path escapes git checkout")
    return child


def _safe_relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ExecutorInstallError(f"{label} must be a non-empty relative path")
    return path


__all__ = [
    "ExecutorInstallError",
    "GitExecutorSource",
    "ExecutorInstallPlan",
    "ExecutorInstallResult",
    "build_executor_install_plan",
    "fetch_git_executor_manifest",
    "install_executor",
    "executor_environment_path",
    "executor_python_path",
]
