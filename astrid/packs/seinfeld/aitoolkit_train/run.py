#!/usr/bin/env python3
"""seinfeld.aitoolkit_train — start training on pod, mirror logs, emit checkpoint manifest."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FAILURE_PATTERNS = [
    "CUDA out of memory",
    "NaN detected",
    "RuntimeError",
    "torch.cuda.OutOfMemoryError",
]
CHECKPOINT_RE = re.compile(r"step[_-]?(\d+).*\.safetensors$", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run ai-toolkit training on a pod and mirror logs.")
    p.add_argument("--pod-handle", type=Path, required=True)
    p.add_argument("--produces-dir", type=Path, required=True)
    p.add_argument("--config-path", default="/workspace/config.yaml")
    p.add_argument("--output-dir", default="/workspace/output")
    p.add_argument("--remote-log", default="/workspace/training.log")
    p.add_argument("--dry-run", action="store_true")
    return p


def _scan_failures(log_text: str) -> str | None:
    for pat in FAILURE_PATTERNS:
        if pat in log_text:
            return pat
    return None


def _parse_checkpoint_listing(listing: str, output_dir: str) -> list[dict]:
    out: list[dict] = []
    for raw in listing.splitlines():
        line = raw.strip()
        if not line.endswith(".safetensors"):
            continue
        m = CHECKPOINT_RE.search(line)
        step = int(m.group(1)) if m else -1
        name = line.split()[-1]
        out.append({"step": step, "remote_path": f"{output_dir}/{name}"})
    out.sort(key=lambda c: c["step"])
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    produces = args.produces_dir
    produces.mkdir(parents=True, exist_ok=True)
    training_log = produces / "training.log"
    manifest_path = produces / "checkpoint_manifest.json"

    if args.dry_run:
        manifest_path.write_text(
            json.dumps({"status": "dry_run", "checkpoints": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        training_log.write_text("(dry-run)\n", encoding="utf-8")
        return 0

    repo_root = Path(__file__).resolve().parents[4]

    # Kick off training (blocking — ai-toolkit streams its log to stdout, which we capture).
    train_cmd = (
        "cd /app/ai-toolkit && "
        f"python3 run.py {args.config_path} --log {args.remote_log}"
    )
    exec_produces = produces / "_exec_train"
    exec_produces.mkdir(parents=True, exist_ok=True)
    # Use an empty staging dir as --local-root so cmd_exec doesn't upload the cwd
    # (training only needs to run a remote command; config + dataset are already on the pod).
    empty_local_root = produces / "_empty_local_root"
    empty_local_root.mkdir(parents=True, exist_ok=True)
    exec_argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "exec",
        "--produces-dir", str(exec_produces),
        "--pod-handle", str(args.pod_handle),
        "--local-root", str(empty_local_root),
        "--remote-script", train_cmd,
    ]
    rv = subprocess.run(exec_argv, cwd=repo_root)

    # Mirror remote stdout into local training.log from exec_result.json.
    result_json = exec_produces / "exec_result.json"
    if result_json.exists():
        try:
            result_data = json.loads(result_json.read_text(encoding="utf-8"))
            training_log.write_text(result_data.get("stdout", "") + result_data.get("stderr", ""), encoding="utf-8")
        except Exception:
            pass
    log_text = training_log.read_text(encoding="utf-8") if training_log.exists() else ""
    failure = _scan_failures(log_text)

    if failure or rv.returncode != 0:
        tail = "\n".join(log_text.splitlines()[-200:])
        (produces / "training.failure.log").write_text(tail, encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {"status": "failed", "reason": failure or f"exit_{rv.returncode}", "checkpoints": []},
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"aitoolkit_train: FAILED ({failure or f'exit {rv.returncode}'})", file=sys.stderr)
        return rv.returncode or 4

    # Enumerate checkpoints on the pod.
    list_produces = produces / "_exec_list"
    list_produces.mkdir(parents=True, exist_ok=True)
    list_argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "exec",
        "--produces-dir", str(list_produces),
        "--pod-handle", str(args.pod_handle),
        "--local-root", str(empty_local_root),
        "--remote-script", f"ls -1 {args.output_dir}/*.safetensors 2>/dev/null || true",
    ]
    subprocess.run(list_argv, cwd=repo_root)
    list_result = list_produces / "exec_result.json"
    listing = ""
    if list_result.exists():
        try:
            listing = json.loads(list_result.read_text(encoding="utf-8")).get("stdout", "")
        except Exception:
            pass
    checkpoints = _parse_checkpoint_listing(listing, args.output_dir)
    manifest_path.write_text(
        json.dumps({"status": "ok", "checkpoints": checkpoints}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"aitoolkit_train: {len(checkpoints)} checkpoint(s) → {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
