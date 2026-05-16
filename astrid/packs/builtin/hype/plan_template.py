"""Hype plan-template for Sprint 5a — emits a plan v2 with the leaner 6-stage spine."""

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
    brief: str | Path | None = None,
    theme: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a plan v2 dict for the hype pipeline.

    The plan follows the leaner S5a spine:
      transcribe → scenes → cut → render → editor_review → validate

    - All LLM/script calls use ``adapter: local``.
    - Render uses ``adapter: local`` calling ``external.runpod.session``.
    - ``editor_review`` uses ``adapter: manual`` for human-in-the-loop.
    - The top-level group step ``hype`` declares ``re_export`` per G1.
    - ``cut`` fans out across discovered scenes via
      ``repeat.for_each.from_ref: "scenes.produces.scenes_list"`` (G5).

    Dynamic discovery (shot count after cut) is handled by the orchestrator
    calling ``astrid plan add-step`` at runtime — not by this template.
    """
    run_root = Path(run_root)
    plan_id = f"hype-{run_id or uuid.uuid4().hex[:12]}"

    # Command interpolation: {python_exec}, {run_root}, {source} are resolved
    # at plan-emission time per G3.
    cmd_transcribe = _build_transcribe_cmd(python_exec, run_root, source)
    cmd_scenes = _build_scenes_cmd(python_exec, run_root)
    cmd_cut = _build_cut_cmd(python_exec, run_root)
    cmd_render = _build_render_cmd(python_exec, run_root)
    cmd_validate = _build_validate_cmd(python_exec, run_root)

    plan: dict[str, Any] = {
        "plan_id": plan_id,
        "version": 2,
        "steps": [
            {
                "id": "hype",
                "adapter": "local",
                "re_export": {
                    "final_video": "render.produces.video_output",
                    "timeline": "cut.produces.timeline_output",
                    "transcript": "transcribe.produces.transcript_output",
                    "scenes": "scenes.produces.scenes_list",
                },
                "children": [
                    {
                        "id": "transcribe",
                        "adapter": "local",
                        "command": cmd_transcribe,
                        "produces": {
                            "transcript_output": {
                                "path": "transcript.json",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                        "cost": {
                            "amount": 0.002,
                            "currency": "USD",
                            "source": "gemini",
                        },
                    },
                    {
                        "id": "scenes",
                        "adapter": "local",
                        "command": cmd_scenes,
                        "produces": {
                            "scenes_list": {
                                "path": "scenes.json",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                        "cost": {
                            "amount": 0.005,
                            "currency": "USD",
                            "source": "gemini",
                        },
                    },
                    {
                        "id": "cut",
                        "adapter": "local",
                        "command": cmd_cut,
                        "repeat": {
                            "for_each": {
                                "from": "scenes.produces.scenes_list"
                            }
                        },
                        "produces": {
                            "timeline_output": {
                                "path": "hype.timeline.json",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                        "cost": {
                            "amount": 0.010,
                            "currency": "USD",
                            "source": "claude",
                        },
                    },
                    {
                        "id": "render",
                        "adapter": "local",
                        "command": cmd_render,
                        "produces": {
                            "video_output": {
                                "path": "hype.mp4",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                        "cost": {
                            "amount": 0.50,
                            "currency": "USD",
                            "source": "runpod",
                        },
                    },
                    {
                        "id": "editor_review",
                        "adapter": "manual",
                        "command": "editor-review",
                        "instructions": (
                            "Review the rendered video at render/v1/produces/hype.mp4. "
                            "Approve with 'astrid ack editor_review --decision approve' "
                            "or request changes with 'astrid ack editor_review --decision revise'."
                        ),
                        "produces": {
                            "review_output": {
                                "path": "editor_review.json",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                    },
                    {
                        "id": "validate",
                        "adapter": "local",
                        "command": cmd_validate,
                        "produces": {
                            "validation_output": {
                                "path": "validation.json",
                                "check": {
                                    "check_id": "file_nonempty",
                                    "params": {},
                                    "sentinel": False,
                                },
                            }
                        },
                    },
                ],
            }
        ],
    }
    return plan


from astrid.core.orchestrator.plan_v2 import emit_plan_json  # noqa: F811 — shared helper


def _build_transcribe_cmd(
    python_exec: str, run_root: Path, source: str | Path | None
) -> str:
    src = str(Path(source).resolve()) if source else ""
    out = run_root / "steps" / "transcribe" / "v1" / "produces"
    return (
        f"{python_exec} -m astrid.packs.builtin.transcribe "
        f"--source {src} --out {out}"
    )


def _build_scenes_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "scenes" / "v1" / "produces"
    transcript = run_root / "steps" / "transcribe" / "v1" / "produces" / "transcript.json"
    return (
        f"{python_exec} -m astrid.packs.builtin.scenes "
        f"--transcript {transcript} --out {out}"
    )


def _build_cut_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "cut" / "v1" / "produces"
    scenes = run_root / "steps" / "scenes" / "v1" / "produces" / "scenes.json"
    return (
        f"{python_exec} -m astrid.packs.builtin.cut "
        f"--scenes {scenes} --out {out}"
    )


def _build_render_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "render" / "v1" / "produces"
    timeline = run_root / "steps" / "cut" / "v1" / "produces" / "hype.timeline.json"
    return (
        f"{python_exec} -m astrid.packs.external.executors.runpod session "
        f"--timeline {timeline} --out {out}"
    )


def _build_validate_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "validate" / "v1" / "produces"
    video = run_root / "steps" / "render" / "v1" / "produces" / "hype.mp4"
    return (
        f"{python_exec} -m astrid.packs.builtin.validate "
        f"--video {video} --out {out}"
    )