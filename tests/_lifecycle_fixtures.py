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

from artagents.core.task.lifecycle import cmd_start
from artagents.orchestrate.compile import compile_to_path


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
    ARTAGENTS_ACTOR=start_actor before cmd_start so run_started.actor==start_actor.
    Caller is responsible for adjusting ARTAGENTS_ACTOR before subsequent ack calls.
    """
    packs, projects = setup_packs_and_compile(tmp_path, pack, module_name, body, qualified_id)
    os.environ["ARTAGENTS_ACTOR"] = start_actor
    with redirect_stdout(io.StringIO()):
        rc = cmd_start(
            [qualified_id, "--project", project, "--name", run_id],
            packs_root=packs,
            projects_root=projects,
        )
    if rc != 0:
        raise RuntimeError(f"setup_run: cmd_start rc={rc}")
    return packs, projects
