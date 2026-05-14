"""Shared helpers for Phase 5 lifecycle tests (T12-T20).

Not a test module (doesn't match test_*.py glob). Provides:
- ``make_pack``: write a tiny DSL pack module under packs/<pack>/<name>.py
- ``setup_packs_and_compile``: build packs root + compile a qualified id to JSON
- ``setup_run``: build packs + projects roots, compile, and call cmd_start
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from astrid.core.project.project import create_project
from astrid.core.task.lifecycle import cmd_start
from astrid.orchestrate.compile import compile_to_path


def migrate_v1_plan(plan: dict) -> dict:
    """Rewrite a Sprint 2 (v1) plan dict in place to the Sprint 3 (v2) collapsed schema.

    Reuses the production migration logic so legacy test fixtures keep working
    without per-test schema rewrites. Idempotent: v2 plans pass through unchanged.
    """
    import importlib.util
    import sys as _sys

    if plan.get("version") == 2:
        return plan
    _spec = importlib.util.spec_from_file_location(
        "_astrid_sprint3_migrate_plans",
        Path(__file__).resolve().parent.parent
        / "scripts" / "migrations" / "sprint-3" / "migrate_plans.py",
    )
    _mod = importlib.util.module_from_spec(_spec)
    _sys.modules[_spec.name] = _mod
    _spec.loader.exec_module(_mod)
    new_steps = [_mod._migrate_step(s) if isinstance(s, dict) else s for s in plan.get("steps", [])]
    return {"plan_id": plan.get("plan_id", "unknown"), "version": 2, "steps": new_steps}


def make_pack(packs_root: Path, pack: str, module_name: str, body: str) -> Path:
    pack_dir = packs_root / pack
    pack_dir.mkdir(parents=True, exist_ok=True)
    module_path = pack_dir / f"{module_name}.py"
    module_path.write_text(body, encoding="utf-8")
    return module_path


def setup_packs_and_compile(
    tmp_path: Path,
    pack: str,
    module_name: str,
    body: str,
    qualified_id: str,
) -> tuple[Path, Path]:
    """Returns (packs_root, projects_root). Compiles the qualified id."""
    packs = tmp_path / "packs"
    projects = tmp_path / "projects"
    packs.mkdir()
    projects.mkdir()
    make_pack(packs, pack, module_name, body)
    compile_to_path(qualified_id, packs_root=packs)
    return packs, projects


def setup_run(
    tmp_path: Path,
    pack: str,
    module_name: str,
    body: str,
    qualified_id: str,
    *,
    run_id: str,
    project: str = "p",
    start_actor: str = "bob",
) -> tuple[Path, Path]:
    """Compile + cmd_start. Returns (packs_root, projects_root). Sets
    ASTRID_ACTOR=start_actor before cmd_start so run_started.actor==start_actor.
    Caller is responsible for adjusting ASTRID_ACTOR before subsequent ack calls.
    """
    packs, projects = setup_packs_and_compile(tmp_path, pack, module_name, body, qualified_id)
    create_project(project, root=projects, exist_ok=True)
    os.environ["ASTRID_ACTOR"] = start_actor
    with redirect_stdout(io.StringIO()):
        rc = cmd_start(
            [qualified_id, "--project", project, "--name", run_id],
            packs_root=packs,
            projects_root=projects,
        )
    if rc != 0:
        raise RuntimeError(f"setup_run: cmd_start rc={rc}")
    return packs, projects
