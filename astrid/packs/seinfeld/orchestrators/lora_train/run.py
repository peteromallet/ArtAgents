#!/usr/bin/env python3
"""seinfeld.lora_train — orchestrator: provision → stage → train → eval → human gate → resume → teardown → register.

Subcommands:
  default (no subcommand): run pipeline up through human gate, exit 0 with last_run.json status=PAUSED.
  resume: read last_run.json + --pick <step>, write chosen_checkpoint.json, teardown pod, register LoRA.

See ./STAGE.md for the full step list.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_IMAGE = "ostris/aitoolkit:latest"
DEFAULT_PORTS = "8675/http,22/tcp"
DEFAULT_STORAGE = "seinfeld-dataset"
DEFAULT_GPU = "NVIDIA RTX 6000 Ada Generation"
DEFAULT_CONTAINER_DISK_GB = 200
DEFAULT_MAX_RUNTIME = 43200  # 12h ceiling
DEFAULT_BASE_MODEL = "Lightricks/LTX-2.3/ltx-2.3-22b-dev.safetensors"
PACK_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[5]


def _abs(p: str | Path) -> str:
    return str(Path(p).resolve())


def _run(argv: list[str], cwd: Path | None = None) -> int:
    print(f"$ {' '.join(argv)}", flush=True)
    return subprocess.run(argv, cwd=cwd or REPO_ROOT).returncode


def _preflight(args: argparse.Namespace) -> int:
    if yaml is None:
        print("ERROR: PyYAML required (pip install pyyaml)", file=sys.stderr)
        return 3
    manifest_path = Path(args.manifest)
    vocab_path = Path(args.vocabulary)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 3
    if not vocab_path.exists():
        print(f"ERROR: vocabulary not found: {vocab_path}", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: manifest is not valid JSON: {exc}", file=sys.stderr)
        return 3
    try:
        yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: vocabulary YAML parse failed: {exc}", file=sys.stderr)
        return 3

    clips = manifest.get("clips") or []
    if args.smoke and len(clips) < 5:
        print(f"ERROR: --smoke requires ≥5 clips; found {len(clips)}", file=sys.stderr)
        return 3
    if not clips:
        print("ERROR: manifest has no clips", file=sys.stderr)
        return 3

    manifest_dir = manifest_path.parent
    missing: list[str] = []
    for clip in clips:
        clip_file = clip.get("clip_file") or clip.get("path")
        clip_id = clip.get("clip_id") or (Path(clip_file).stem if clip_file else None)
        if not clip_file or not clip_id:
            missing.append(f"<bad-entry {clip}>")
            continue
        cf = Path(clip_file)
        if not cf.is_absolute():
            # Manifest stores repo-root-relative paths (per dataset_build/run.py).
            cf_repo = (REPO_ROOT / cf).resolve()
            cf_mdir = (manifest_dir / cf).resolve()
            cf = cf_repo if cf_repo.exists() else cf_mdir
        if not cf.exists():
            missing.append(f"clip_file missing: {cf}")
            continue
        caption = cf.parent / f"{clip_id}.caption.json"
        if not caption.exists():
            missing.append(f"caption sidecar missing: {caption}")
    if missing:
        print("ERROR: preflight failed:", file=sys.stderr)
        for m in missing[:10]:
            print(f"  - {m}", file=sys.stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
        return 3

    if not os.environ.get("RUNPOD_API_KEY") and not args.dry_run:
        print(
            "ERROR: RUNPOD_API_KEY is not set. Source one of:\n"
            "  source $PWD/.env.local\n"
            "  source $PWD/.env\n"
            "  source /Users/peteromalley/Documents/reigh-workspace/runpod-lifecycle/.env\n"
            "  source ~/.config/astrid/.env",
            file=sys.stderr,
        )
        return 3
    return 0


def _invoke_repo_setup(out: Path) -> int:
    produces = out / "repo_setup"
    produces.mkdir(parents=True, exist_ok=True)
    return _run([
        sys.executable, "-m", "astrid.packs.seinfeld.executors.repo_setup.run",
        "--produces-dir", _abs(produces),
    ])


def _provision(args: argparse.Namespace, out: Path) -> tuple[int, Path | None]:
    produces = out / "provision"
    produces.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "provision",
        "--produces-dir", _abs(produces),
        "--image", args.image,
        "--ports", args.ports,
        "--gpu-type", args.gpu,
        "--container-disk-gb", str(args.container_disk_gb),
        "--max-runtime-seconds", str(args.max_runtime_seconds),
    ]
    if args.storage_name:
        argv.extend(["--storage-name", args.storage_name])
    rc = _run(argv)
    handle = produces / "pod_handle.json"
    return rc, (handle if handle.exists() else None)


def _stage(args: argparse.Namespace, out: Path, pod_handle: Path) -> int:
    produces = out / "stage"
    produces.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable, "-m", "astrid.packs.seinfeld.executors.aitoolkit_stage.run",
        "--manifest", _abs(args.manifest),
        "--vocabulary", _abs(args.vocabulary),
        "--produces-dir", _abs(produces),
        "--pod-handle", _abs(pod_handle),
        "--base-model", args.base_model_name,
        "--seed", str(args.seed),
        "--dataset-remote-path", args.dataset_remote_path,
    ]
    if args.steps is not None:
        argv += ["--steps", str(args.steps)]
    if args.smoke:
        argv.append("--smoke")
    rc = _run(argv)
    ui_url = produces / "ui_url.txt"
    if ui_url.exists():
        url = ui_url.read_text(encoding="utf-8").strip()
        if url:
            print(f"\n========== AI Toolkit UI ==========\n{url}\n===================================\n", flush=True)
    return rc


def _train(args: argparse.Namespace, out: Path, pod_handle: Path) -> int:
    produces = out / "train"
    produces.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable, "-m", "astrid.packs.seinfeld.executors.aitoolkit_train.run",
        "--pod-handle", _abs(pod_handle),
        "--produces-dir", _abs(produces),
    ]
    return _run(argv)


def _samples_collage(
    args: argparse.Namespace, out: Path, pod_handle: Path, staged_config: Path,
) -> int:
    """Pull training-time sample mp4s from the pod, optionally caption with video_understand,
    build the per-step / per-prompt HTML grid the human gate uses to pick a checkpoint."""
    produces = out / "samples_collage"
    produces.mkdir(parents=True, exist_ok=True)
    remote_output = f"/workspace/output/{args.lora_id}"
    argv = [
        sys.executable, "-m", "astrid.packs.seinfeld.samples_collage.run",
        "--pod-handle", _abs(pod_handle),
        "--remote-output-dir", remote_output,
        "--out", _abs(produces),
        "--staged-config", _abs(staged_config),
        "--produces-dir", _abs(produces),
    ]
    if not args.skip_understand:
        argv.append("--understand")
        argv.extend(["--understand-mode", args.understand_mode])
    return _run(argv)


def _eval_grid(
    args: argparse.Namespace, out: Path, pod_handle: Path,
    checkpoint_manifest: Path, staged_config: Path,
) -> int:
    produces = out / "eval_grid"
    produces.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable, "-m", "astrid.packs.seinfeld.executors.lora_eval_grid.run",
        "--pod-handle", _abs(pod_handle),
        "--checkpoint-manifest", _abs(checkpoint_manifest),
        "--vocabulary", _abs(args.vocabulary),
        "--produces-dir", _abs(produces),
    ]
    if args.smoke:
        argv.append("--smoke")
    return _run(argv)


def _teardown(out: Path, pod_handle: Path) -> int:
    produces = out / "teardown"
    produces.mkdir(parents=True, exist_ok=True)
    return _run([
        sys.executable, "-m", "astrid.packs.external.runpod.run", "teardown",
        "--produces-dir", _abs(produces),
        "--pod-handle", _abs(pod_handle),
    ])


def _register(args: argparse.Namespace, out: Path, chosen: Path, lora_source: Path, staged_config: Path) -> int:
    produces = out / "register"
    produces.mkdir(parents=True, exist_ok=True)
    return _run([
        sys.executable, "-m", "astrid.packs.seinfeld.executors.lora_register.run",
        "--chosen-checkpoint", _abs(chosen),
        "--lora-source", _abs(lora_source),
        "--staged-config", _abs(staged_config),
        "--vocabulary", _abs(args.vocabulary),
        "--produces-dir", _abs(produces),
        "--base-model", args.base_model_name,
        "--lora-id", args.lora_id,
    ])


def _write_last_run(out: Path, payload: dict) -> None:
    (out / "last_run.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Train a Seinfeld LoRA on LTX 2.3 via ai-toolkit on RunPod."
    )
    sub = p.add_subparsers(dest="subcommand")

    def _add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--out", required=True, type=Path)

    # Default run subcommand (also runnable as bare flags for orchestrator framework)
    p.add_argument("--manifest")
    p.add_argument("--vocabulary")
    p.add_argument("--base-model-name", dest="base_model_name", default=DEFAULT_BASE_MODEL)
    p.add_argument("--lora-id", default="seinfeld-scene-v1")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--gpu", default=DEFAULT_GPU)
    p.add_argument("--image", default=DEFAULT_IMAGE)
    p.add_argument("--ports", default=DEFAULT_PORTS)
    p.add_argument("--storage-name", default=DEFAULT_STORAGE)
    p.add_argument("--container-disk-gb", type=int, default=DEFAULT_CONTAINER_DISK_GB)
    p.add_argument("--max-runtime-seconds", type=int, default=DEFAULT_MAX_RUNTIME)
    p.add_argument("--dataset-remote-path", default="/workspace/dataset")
    p.add_argument("--skip-understand", action="store_true",
                   help="Skip video_understand calls on each sample (still pulls + collages).")
    p.add_argument("--understand-mode", default="fast", choices=["fast", "best"],
                   help="video_understand model: fast=Gemini Flash, best=Gemini Pro.")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--produces-dir", dest="produces_dir", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)

    # resume
    sp_resume = sub.add_parser("resume", help="Resume from PAUSED state: pick a checkpoint, teardown, register.")
    sp_resume.add_argument("--out", required=True, type=Path)
    sp_resume.add_argument("--pick", type=int, required=True, help="Checkpoint step to register.")
    sp_resume.add_argument("--notes", default="", help="Human pick notes.")
    sp_resume.add_argument("--skip-teardown", action="store_true")

    return p


def _resolve_out(args: argparse.Namespace) -> Path:
    out = args.out or args.produces_dir
    if not out:
        print("ERROR: --out (or --produces-dir) is required", file=sys.stderr)
        sys.exit(2)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def cmd_run(args: argparse.Namespace) -> int:
    if not args.manifest or not args.vocabulary:
        print("ERROR: --manifest and --vocabulary are required", file=sys.stderr)
        return 2
    out = _resolve_out(args)

    rc = _preflight(args)
    if rc != 0:
        return rc

    rc = _invoke_repo_setup(out)
    if rc != 0:
        print(f"ERROR: seinfeld.repo_setup failed (rc={rc})", file=sys.stderr)
        return rc

    if args.dry_run:
        # Run stage in dry-run only — no pod work.
        produces = out / "stage"
        produces.mkdir(parents=True, exist_ok=True)
        stage_argv = [
            sys.executable, "-m", "astrid.packs.seinfeld.executors.aitoolkit_stage.run",
            "--manifest", _abs(args.manifest),
            "--vocabulary", _abs(args.vocabulary),
            "--produces-dir", _abs(produces),
            "--base-model", args.base_model_name,
            "--seed", str(args.seed),
            "--dataset-remote-path", args.dataset_remote_path,
            "--dry-run",
        ]
        if args.steps is not None:
            stage_argv += ["--steps", str(args.steps)]
        if args.smoke:
            stage_argv.append("--smoke")
        rc = _run(stage_argv)
        if rc != 0:
            return rc
        _write_last_run(out, {
            "status": "DRY_RUN",
            "image": args.image,
            "ports": args.ports,
            "gpu": args.gpu,
            "smoke": args.smoke,
            "staged_config": _abs(produces / "staged_config.yaml"),
        })
        print(f"lora_train: dry-run complete → {out / 'last_run.json'}")
        return 0

    rc, pod_handle = _provision(args, out)
    if rc != 0 or pod_handle is None:
        print(f"ERROR: provision failed (rc={rc})", file=sys.stderr)
        return rc or 4

    try:
        rc = _stage(args, out, pod_handle)
        if rc != 0:
            return rc
        staged_config = (out / "stage" / "staged_config.yaml").resolve()

        rc = _train(args, out, pod_handle)
        if rc != 0:
            return rc
        checkpoint_manifest = (out / "train" / "checkpoint_manifest.json").resolve()

        # Pull training-time samples + (optionally) caption each with video_understand.
        # Best-effort — collage failures should not block the human gate.
        rc_collage = _samples_collage(args, out, pod_handle, staged_config)
        collage_index = (out / "samples_collage" / "index.html").resolve()
        if rc_collage != 0:
            print(f"WARN: samples_collage rc={rc_collage} (continuing anyway)", file=sys.stderr)

        rc = _eval_grid(args, out, pod_handle, checkpoint_manifest, staged_config)
        if rc != 0:
            return rc
        eval_index = (out / "eval_grid" / "index.html").resolve()
    except Exception:
        # Best-effort teardown on unexpected failure.
        _teardown(out, pod_handle)
        raise

    _write_last_run(out, {
        "status": "PAUSED",
        "pod_handle": _abs(pod_handle),
        "staged_config": str(staged_config),
        "checkpoint_manifest": str(checkpoint_manifest),
        "samples_collage_index": str(collage_index) if collage_index.exists() else None,
        "eval_grid_index": str(eval_index),
        "vocabulary": _abs(args.vocabulary),
        "base_model_name": args.base_model_name,
        "lora_id": args.lora_id,
        "out": _abs(out),
    })
    print(
        "\n========== HUMAN GATE ==========\n"
        f"Training samples (per-step × per-prompt with auto-captions): {collage_index}\n"
        f"Eval grid (inference clips on candidate checkpoints): {eval_index}\n"
        f"\nWhen ready, run:\n"
        f"  python3 -m astrid.packs.seinfeld.orchestrators.lora_train.run resume "
        f"--out {out} --pick <step> --notes '<why this step>'\n"
        "================================\n",
        flush=True,
    )
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    state_path = out / "last_run.json"
    if not state_path.exists():
        print(f"ERROR: no last_run.json at {state_path}", file=sys.stderr)
        return 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("status") != "PAUSED":
        print(f"ERROR: last_run.json status is {state.get('status')!r}, expected PAUSED", file=sys.stderr)
        return 2

    cm_path = Path(state["checkpoint_manifest"])
    cm = json.loads(cm_path.read_text(encoding="utf-8"))
    match = next((c for c in cm.get("checkpoints", []) if int(c.get("step", -1)) == args.pick), None)
    if not match:
        print(f"ERROR: step {args.pick} not in checkpoint_manifest", file=sys.stderr)
        return 2

    chosen = {
        "step": args.pick,
        "remote_path": match["remote_path"],
        "notes": args.notes,
    }
    chosen_path = out / "chosen_checkpoint.json"
    chosen_path.write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")

    pod_handle = Path(state["pod_handle"])
    # Pull the chosen .safetensors off the pod into <out>/register-src/ before teardown.
    register_src = out / "register-src"
    register_src.mkdir(parents=True, exist_ok=True)
    local_lora = register_src / Path(match["remote_path"]).name
    pull_argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "exec",
        "--pod-handle", _abs(pod_handle),
        "--produces-dir", _abs(register_src),
        "--remote-script", f"cat {match['remote_path']}",
        "--download", f"{match['remote_path']}:{_abs(local_lora)}",
    ]
    # The exec executor does not necessarily support --download; if missing, the user
    # must copy the file via scp from the SSH address in pod_handle.json. Best effort:
    rc = subprocess.run(pull_argv, cwd=REPO_ROOT).returncode
    if rc != 0 or not local_lora.exists():
        print(
            f"WARNING: could not auto-pull checkpoint from pod; copy manually before teardown:\n"
            f"  scp -P <port> root@<ip>:{match['remote_path']} {local_lora}\n"
            f"(SSH details in {pod_handle})",
            file=sys.stderr,
        )
        if not local_lora.exists():
            print("ERROR: lora source missing; aborting before teardown to preserve pod.", file=sys.stderr)
            return 5

    if not args.skip_teardown:
        rc = _teardown(out, pod_handle)
        if rc != 0:
            print(f"WARNING: teardown rc={rc} — continuing to register", file=sys.stderr)

    # Reconstruct an args-like namespace for _register.
    reg_args = argparse.Namespace(
        vocabulary=state["vocabulary"],
        base_model_name=state.get("base_model_name", DEFAULT_BASE_MODEL),
        lora_id=state.get("lora_id", "seinfeld-scene-v1"),
    )
    rc = _register(reg_args, out, chosen_path, local_lora, Path(state["staged_config"]))
    if rc != 0:
        return rc

    _write_last_run(out, {**state, "status": "REGISTERED", "chosen_checkpoint": _abs(chosen_path)})
    print(f"lora_train: registered → {out / 'register' / 'registered_lora.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand == "resume":
        return cmd_resume(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
