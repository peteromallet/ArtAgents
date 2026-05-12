#!/usr/bin/env python3
"""seinfeld.aitoolkit_stage — generate ai-toolkit config, bootstrap.sh, and (live) stage onto a pod."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

HIVEMIND_DEFAULTS = {
    "resolution": 512,
    "num_frames": 97,
    "fps": 24,
    "lr": 2.0e-5,
    "steps_default": 2000,
    "steps_smoke": 100,
    "rank": 32,
    "save_every": 250,
    "sample_every": 250,
    "batch_size": 1,
    "grad_accum": 4,
    "seed_default": 42,
    "trigger_word": "seinfeld scene",
    "base_model_default": "Lightricks/LTX-2.3",
}

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "lora_train" / "config_template.yaml"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_yaml(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML required (pip install pyyaml)")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dump_yaml(obj: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, sort_keys=False, default_flow_style=False)


def _build_sample_prompts(vocab: dict, n: int = 4) -> list[str]:
    """Build a small list of inference prompts from the vocabulary."""
    scenes = list((vocab.get("scenes") or {}).items())
    chars = list((vocab.get("characters") or {}).keys())
    shots = list((vocab.get("shot_types") or {}).keys())
    prompts: list[str] = []
    for i in range(n):
        scene_id = scenes[i % max(len(scenes), 1)][0] if scenes else "jerrys_apt"
        char = chars[i % max(len(chars), 1)] if chars else "jerry"
        shot = shots[i % max(len(shots), 1)] if shots else "medium"
        prompts.append(
            f"{HIVEMIND_DEFAULTS['trigger_word']}, A {shot} shot in {scene_id}. "
            f"{char.capitalize()} talking. Seinfeld sitcom style, 90s NBC lighting."
        )
    return prompts


def build_config(
    *,
    manifest: dict,
    vocabulary: dict,
    smoke: bool,
    steps: int | None,
    seed: int,
    base_model: str,
    run_name: str,
    dataset_dir: str,
    output_dir: str,
) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    cfg = yaml.safe_load(template_text)

    final_steps = steps if steps is not None else (
        HIVEMIND_DEFAULTS["steps_smoke"] if smoke else HIVEMIND_DEFAULTS["steps_default"]
    )
    prompts = _build_sample_prompts(vocabulary, n=3 if smoke else 4)

    process = cfg["config"]["process"][0]
    process["training_folder"] = output_dir
    process["trigger_word"] = HIVEMIND_DEFAULTS["trigger_word"]
    process["network"]["linear"] = HIVEMIND_DEFAULTS["rank"]
    process["network"]["linear_alpha"] = HIVEMIND_DEFAULTS["rank"]
    process["save"]["save_every"] = HIVEMIND_DEFAULTS["save_every"]
    process["datasets"][0]["folder_path"] = dataset_dir
    process["datasets"][0]["num_frames"] = HIVEMIND_DEFAULTS["num_frames"]
    process["datasets"][0]["fps"] = HIVEMIND_DEFAULTS["fps"]
    process["datasets"][0]["resolution"] = [HIVEMIND_DEFAULTS["resolution"]]
    process["datasets"][0]["bucketing"] = True
    process["train"]["batch_size"] = HIVEMIND_DEFAULTS["batch_size"]
    process["train"]["steps"] = final_steps
    process["train"]["gradient_accumulation_steps"] = HIVEMIND_DEFAULTS["grad_accum"]
    process["train"]["lr"] = HIVEMIND_DEFAULTS["lr"]
    process["train"]["seed"] = seed
    process["model"]["name_or_path"] = base_model
    process["model"]["is_ltx"] = True
    process["sample"]["sample_every"] = HIVEMIND_DEFAULTS["sample_every"]
    process["sample"]["width"] = HIVEMIND_DEFAULTS["resolution"]
    process["sample"]["height"] = 768
    process["sample"]["num_frames"] = HIVEMIND_DEFAULTS["num_frames"]
    process["sample"]["fps"] = HIVEMIND_DEFAULTS["fps"]
    process["sample"]["seed"] = seed
    process["sample"]["prompts"] = prompts
    cfg["config"]["name"] = run_name
    cfg.setdefault("meta", {})["name"] = run_name
    return cfg


BOOTSTRAP_TEMPLATE = """#!/usr/bin/env bash
set -euo pipefail

# AI Toolkit bootstrap - runs on the RunPod pod.
WORKSPACE=/workspace
TOOLKIT_ROOT=/app/ai-toolkit
UI_ROOT="$TOOLKIT_ROOT/ui"
UI_PORT=8675

mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

if [ -f /etc/rp_environment ]; then
  set -a
  # RunPod's image startup writes platform env here for later SSH sessions.
  # shellcheck disable=SC1091
  source /etc/rp_environment
  set +a
fi

echo "Checking CUDA visibility..."
nvidia-smi

if [ ! -d "$TOOLKIT_ROOT" ]; then
  echo "ERROR: AI Toolkit root not found at $TOOLKIT_ROOT" >&2
  exit 2
fi

if [ ! -f "$TOOLKIT_ROOT/run.py" ]; then
  echo "ERROR: AI Toolkit training entrypoint missing: $TOOLKIT_ROOT/run.py" >&2
  exit 2
fi

hf_token_value="${HF_TOKEN:-}"
if [ -z "$hf_token_value" ] && [ -r /proc/1/environ ]; then
  hf_token_value="$(tr '\0' '\n' </proc/1/environ | awk -F= '$1=="HF_TOKEN"{sub(/^[^=]*=/,""); print; exit}')"
fi
if [ -z "$hf_token_value" ]; then
  echo "ERROR: HF_TOKEN is not available in the pod environment; cannot train gated LTX 2.3." >&2
  exit 5
fi
umask 077
if [ -f "$TOOLKIT_ROOT/.env" ]; then
  grep -v '^HF_TOKEN=' "$TOOLKIT_ROOT/.env" > "$TOOLKIT_ROOT/.env.tmp" || true
else
  : > "$TOOLKIT_ROOT/.env.tmp"
fi
printf 'HF_TOKEN=%s\n' "$hf_token_value" >> "$TOOLKIT_ROOT/.env.tmp"
mv "$TOOLKIT_ROOT/.env.tmp" "$TOOLKIT_ROOT/.env"
export HF_TOKEN="$hf_token_value"
unset hf_token_value

if [ ! -f "$WORKSPACE/config.yaml" ]; then
  echo "ERROR: expected config at $WORKSPACE/config.yaml" >&2
  exit 3
fi

# Dataset upload runs as the next stage exec call, after this bootstrap script.

ui_up=0
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:${UI_PORT}" >/dev/null 2>&1; then
    ui_up=1
  fi
fi

if [ "$ui_up" -eq 1 ]; then
  echo "AI Toolkit UI already running on :${UI_PORT}"
else
  if [ ! -d "$UI_ROOT" ]; then
    echo "ERROR: AI Toolkit UI root not found at $UI_ROOT" >&2
    exit 4
  fi
  echo "Starting AI Toolkit UI on :${UI_PORT}..."
  cd "$UI_ROOT"
  nohup npm run start >"$WORKSPACE/ui.log" 2>&1 &
  echo $! >"$WORKSPACE/ui.pid"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${UI_PORT}" >/dev/null 2>&1; then
      echo "AI Toolkit UI started on :${UI_PORT} (pid=$(cat "$WORKSPACE/ui.pid"))"
      exit 0
    fi
    sleep 2
  done
  echo "ERROR: AI Toolkit UI did not become ready on :${UI_PORT}" >&2
  exit 4
fi
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Stage ai-toolkit config + bootstrap onto a RunPod pod.")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--vocabulary", type=Path, required=True)
    p.add_argument("--produces-dir", type=Path, required=True)
    p.add_argument("--pod-handle", type=Path, default=None, help="pod_handle.json from external.runpod.provision")
    p.add_argument(
        "--dataset-dir",
        default=None,
        help="Config dataset folder override. Defaults to --dataset-remote-path.",
    )
    p.add_argument(
        "--dataset-remote-path",
        default="/workspace/dataset",
        help="Remote pod folder where manifest clips + captions are uploaded.",
    )
    p.add_argument("--output-dir", default="/workspace/output")
    p.add_argument("--run-name", default="seinfeld-scene-v1")
    p.add_argument("--base-model", default=HIVEMIND_DEFAULTS["base_model_default"])
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seed", type=int, default=HIVEMIND_DEFAULTS["seed_default"])
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def _resolve_manifest_path(path_value: str, manifest_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    repo_path = (REPO_ROOT / path).resolve()
    if repo_path.exists():
        return repo_path
    return (manifest_dir / path).resolve()


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value) or "clips"


def _dataset_entries(manifest_path: Path, smoke: bool) -> list[tuple[str, Path, Path, str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_dir = manifest_path.parent
    clips = manifest.get("clips") or []
    if smoke:
        clips = clips[:5]

    entries: list[tuple[str, Path, Path, str]] = []
    for idx, clip in enumerate(clips):
        clip_file = clip.get("clip_file") or clip.get("path")
        clip_id = clip.get("clip_id") or clip.get("id") or (
            Path(clip_file).stem if clip_file else f"clip_{idx:03d}"
        )
        if not clip_file:
            raise ValueError(f"manifest clip {idx} is missing clip_file")

        clip_path = _resolve_manifest_path(str(clip_file), manifest_dir)
        caption_value = clip.get("caption_file")
        caption_path = (
            _resolve_manifest_path(str(caption_value), manifest_dir)
            if caption_value
            else clip_path.with_name(f"{clip_id}.caption.json")
        )
        if not clip_path.is_file():
            raise FileNotFoundError(f"clip_file missing: {clip_path}")
        if not caption_path.is_file():
            raise FileNotFoundError(f"caption_file missing: {caption_path}")

        bucket = _safe_path_part(str(clip.get("bucket") or clip_path.parent.name or "clips"))
        entries.append((str(clip_id), clip_path, caption_path, bucket))
    return entries


def _upload_dataset(args: argparse.Namespace, produces: Path, pod_handle: dict) -> int:
    """Copy manifest clips into a staging farm and upload them to the pod."""
    try:
        entries = _dataset_entries(args.manifest, args.smoke)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"aitoolkit_stage: dataset staging failed: {exc}", file=sys.stderr)
        return 3

    dataset_staging = produces / "_dataset_staging"
    if dataset_staging.exists():
        shutil.rmtree(dataset_staging)
    dataset_staging.mkdir(parents=True, exist_ok=True)

    for clip_id, clip_path, caption_path, bucket in entries:
        bucket_dir = dataset_staging / bucket
        bucket_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(clip_path, bucket_dir / f"{clip_id}{clip_path.suffix}")
        shutil.copy2(caption_path, bucket_dir / f"{clip_id}.caption.json")

    file_count = len(entries) * 2
    result = {
        "status": "dry_run" if args.dry_run else "staged",
        "strategy": "copy_farm",
        "clips": len(entries),
        "files": file_count,
        "local_root": str(dataset_staging.resolve()),
        "remote_root": args.dataset_remote_path,
        "pod_id": pod_handle.get("pod_id") or pod_handle.get("id"),
    }
    (produces / "dataset_upload.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )

    if args.dry_run:
        print(
            "aitoolkit_stage: dry-run would upload "
            f"{len(entries)} clips + captions from {dataset_staging} "
            f"to {args.dataset_remote_path}"
        )
        return 0

    exec_produces = produces / "_dataset_exec_produces"
    exec_produces.mkdir(parents=True, exist_ok=True)
    exec_argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "exec",
        "--produces-dir", str(exec_produces),
        "--pod-handle", str(args.pod_handle),
        "--local-root", str(dataset_staging),
        "--remote-root", args.dataset_remote_path,
        "--upload-mode", "sftp_walk",
        "--remote-script", f"echo dataset_staged {len(entries)} clips",
    ]
    rv = subprocess.run(exec_argv, cwd=REPO_ROOT)
    if rv.returncode != 0:
        print(f"aitoolkit_stage: dataset upload failed rc={rv.returncode}", file=sys.stderr)
        return rv.returncode
    print(f"aitoolkit_stage: uploaded {len(entries)} dataset clips to {args.dataset_remote_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dataset_dir is None:
        args.dataset_dir = args.dataset_remote_path
    else:
        args.dataset_remote_path = args.dataset_dir
    produces = args.produces_dir
    produces.mkdir(parents=True, exist_ok=True)

    if yaml is None:
        print("ERROR: PyYAML not installed", file=sys.stderr)
        return 3

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    vocabulary = _load_yaml(args.vocabulary)

    cfg = build_config(
        manifest=manifest,
        vocabulary=vocabulary,
        smoke=args.smoke,
        steps=args.steps,
        seed=args.seed,
        base_model=args.base_model,
        run_name=args.run_name,
        dataset_dir=args.dataset_dir,
        output_dir=args.output_dir,
    )

    staged_path = produces / "staged_config.yaml"
    bootstrap_path = produces / "bootstrap.sh"
    _dump_yaml(cfg, staged_path)
    bootstrap_path.write_text(BOOTSTRAP_TEMPLATE, encoding="utf-8")
    bootstrap_path.chmod(0o755)

    if args.dry_run or not args.pod_handle:
        if args.dry_run:
            rc = _upload_dataset(args, produces, {})
            if rc != 0:
                return rc
        ui_url = ""
        (produces / "ui_url.txt").write_text(ui_url + "\n", encoding="utf-8")
        result = {
            "status": "dry_run" if args.dry_run else "staged_local_only",
            "staged_config": str(staged_path.resolve()),
            "bootstrap": str(bootstrap_path.resolve()),
        }
        (produces / "stage_result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(f"aitoolkit_stage: wrote {staged_path}")
        return 0

    # Live mode: ship config + bootstrap to pod, run bootstrap, derive UI URL.
    pod_handle = json.loads(args.pod_handle.read_text(encoding="utf-8"))
    pod_id = pod_handle.get("pod_id") or pod_handle.get("id")
    ui_url = f"https://{pod_id}-8675.proxy.runpod.net" if pod_id else ""
    (produces / "ui_url.txt").write_text(ui_url + "\n", encoding="utf-8")
    print(f"aitoolkit_stage: AI Toolkit UI URL → {ui_url}")

    # Delegate file shipping + bootstrap exec to external.runpod.exec.
    # external.runpod.exec interface: --local-root <dir> + --remote-root <path>
    # + --remote-script <inline> + required --produces-dir.
    upload_dir = produces / "_upload_staging"
    upload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(staged_path, upload_dir / "config.yaml")
    shutil.copy(bootstrap_path, upload_dir / "bootstrap.sh")
    exec_produces = produces / "_exec_produces"
    exec_produces.mkdir(parents=True, exist_ok=True)
    exec_argv = [
        sys.executable, "-m", "astrid.packs.external.runpod.run", "exec",
        "--produces-dir", str(exec_produces),
        "--pod-handle", str(args.pod_handle),
        "--local-root", str(upload_dir),
        "--remote-root", "/workspace",
        "--remote-script", "bash /workspace/bootstrap.sh",
    ]
    rv = subprocess.run(exec_argv, cwd=REPO_ROOT)
    if rv.returncode != 0:
        print(f"aitoolkit_stage: external.runpod.exec failed rc={rv.returncode}", file=sys.stderr)
        return rv.returncode
    rv_dataset = _upload_dataset(args, produces, pod_handle)
    if rv_dataset != 0:
        return rv_dataset
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
