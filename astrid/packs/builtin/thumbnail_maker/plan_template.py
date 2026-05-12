"""Thumbnail-maker plan-template for Sprint 5b — emits a plan v2 for five-step pipeline."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def build_plan_v2(
    *,
    python_exec: str,
    run_root: str | Path,
    source: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a plan v2 dict for the thumbnail_maker pipeline.

    Steps:
      resolve-video → plan-evidence → discover-video-evidence →
      build-reference-pack → generate-thumbnails

    All steps use ``adapter: local``. Cost is $0 (local-only operations).
    """
    run_root = Path(run_root)
    plan_id = f"thumbnail-maker-{run_id or uuid.uuid4().hex[:12]}"

    cmd_resolve = _build_resolve_cmd(python_exec, run_root, source)
    cmd_plan = _build_plan_cmd(python_exec, run_root)
    cmd_discover = _build_discover_cmd(python_exec, run_root)
    cmd_build_ref = _build_build_ref_cmd(python_exec, run_root)
    cmd_generate = _build_generate_cmd(python_exec, run_root)

    plan: dict[str, Any] = {
        "plan_id": plan_id,
        "version": 2,
        "steps": [
            {
                "id": "resolve-video",
                "adapter": "local",
                "command": cmd_resolve,
                "produces": {
                    "resolve_output": {
                        "path": "video-resolution.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "plan-evidence",
                "adapter": "local",
                "command": cmd_plan,
                "produces": {
                    "evidence_plan_output": {
                        "path": "evidence/evidence-plan.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "discover-video-evidence",
                "adapter": "local",
                "command": cmd_discover,
                "produces": {
                    "candidates_output": {
                        "path": "evidence/candidates.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "build-reference-pack",
                "adapter": "local",
                "command": cmd_build_ref,
                "produces": {
                    "reference_pack_output": {
                        "path": "evidence/reference-pack.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "generate-thumbnails",
                "adapter": "local",
                "command": cmd_generate,
                "produces": {
                    "thumbnail_output": {
                        "path": "thumbnail-manifest.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    return plan


def emit_plan_json(plan: dict[str, Any], path: str | Path) -> None:
    """Write a plan dict as canonical JSON to *path*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8")


def _build_resolve_cmd(
    python_exec: str, run_root: Path, source: str | Path | None
) -> str:
    out = run_root / "steps" / "resolve-video" / "v1" / "produces"
    src = str(Path(source).resolve()) if source else ""
    return (
        f"{python_exec} -m astrid.packs.builtin.thumbnail_maker.run "
        f"--video {src} --out {out} --query auto --dry-run"
    )


def _build_plan_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "plan-evidence" / "v1" / "produces"
    evidence = (
        run_root
        / "steps"
        / "resolve-video"
        / "v1"
        / "produces"
        / "video-resolution.json"
    )
    return (
        f"{python_exec} -m astrid.packs.builtin.thumbnail_maker.run "
        f"--video {evidence} --out {out} --query auto --dry-run"
    )


def _build_discover_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "discover-video-evidence" / "v1" / "produces"
    evidence_plan = (
        run_root
        / "steps"
        / "plan-evidence"
        / "v1"
        / "produces"
        / "evidence"
        / "evidence-plan.json"
    )
    return (
        f"{python_exec} -m astrid.packs.builtin.thumbnail_maker.run "
        f"--out {out} --query auto --dry-run "
        f"--previous-manifest {evidence_plan}"
    )


def _build_build_ref_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "build-reference-pack" / "v1" / "produces"
    candidates = (
        run_root
        / "steps"
        / "discover-video-evidence"
        / "v1"
        / "produces"
        / "evidence"
        / "candidates.json"
    )
    return (
        f"{python_exec} -m astrid.packs.builtin.thumbnail_maker.run "
        f"--out {out} --query auto --dry-run "
        f"--previous-manifest {candidates}"
    )


def _build_generate_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "generate-thumbnails" / "v1" / "produces"
    ref_pack = (
        run_root
        / "steps"
        / "build-reference-pack"
        / "v1"
        / "produces"
        / "evidence"
        / "reference-pack.json"
    )
    return (
        f"{python_exec} -m astrid.packs.builtin.thumbnail_maker.run "
        f"--out {out} --query auto --dry-run "
        f"--previous-manifest {ref_pack}"
    )