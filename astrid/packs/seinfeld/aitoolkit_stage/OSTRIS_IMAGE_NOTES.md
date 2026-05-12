# Ostris AI Toolkit Image Notes

Probe date: 2026-05-12

Image: `ostris/aitoolkit:latest`

RunPod pod: `jib9xczr0j2y0v`

GPU: `NVIDIA A40`

Ports requested: `8675/http,22/tcp`

Termination: `/tmp/probe_pod_teardown/teardown_receipt.json` recorded `status: terminated` at `2026-05-12T16:39:24.079Z`.

## Container startup

`/proc/1/cmdline`:

```text
/sbin/docker-init -- /opt/nvidia/nvidia_entrypoint.sh /start.sh
```

`/start.sh` sets up SSH, appends selected `RUNPOD_*` environment values to `/etc/rp_environment`, then runs:

```bash
cd /app/ai-toolkit/ui && npm run start
```

Observed UI processes:

```text
npm run start
concurrently --restart-tries -1 --restart-after 1000 -n WORKER,UI "node dist/cron/worker.js" "next start --port 8675"
node dist/cron/worker.js
next-server (v15.5.9)
```

`curl -I http://127.0.0.1:8675` returned `HTTP/1.1 200 OK`. Port `3000` was not listening.

## Filesystem layout

`/workspace` did not exist on first boot without a network volume. The toolkit root is:

```text
/app/ai-toolkit
```

Relevant files:

```text
/app/ai-toolkit/run.py
/app/ai-toolkit/ui/package.json
/app/ai-toolkit/aitk_db.db
/app/ai-toolkit/output/
```

`/app/ai-toolkit/ui/package.json` defines:

```json
"start": "concurrently --restart-tries -1 --restart-after 1000 -n WORKER,UI \"node dist/cron/worker.js\" \"next start --port 8675\""
```

The UI path helpers resolve `TOOLKIT_ROOT` back to `/app/ai-toolkit`.

## Training entrypoint

`cd /app/ai-toolkit && python3 run.py --help` reported:

```text
usage: run.py [-h] [-r] [-n NAME] [-l LOG] config_file_list [config_file_list ...]
```

The verified command shape for Astrid training is:

```bash
cd /app/ai-toolkit && python3 run.py /workspace/config.yaml --log /workspace/training.log
```

`run.py --log` tees stdout/stderr internally through `toolkit.print.Logger`, so the remote exec wrapper can still capture stdout while the pod keeps `/workspace/training.log`.

## CUDA and Python

`nvidia-smi` reported:

```text
NVIDIA-SMI 550.127.05
CUDA Version: 12.8
GPU 0: NVIDIA A40, 46068 MiB
```

Python probe:

```text
Python 3.12.3
torch 2.9.1+cu128
cuda_available True
cuda_version 12.8
device_count 1
device_name_0 NVIDIA A40
```

## Environment behavior

PID 1 and `npm run start` had NVIDIA and RunPod SSH env values such as `CUDA_VERSION`, `NVIDIA_VISIBLE_DEVICES`, `NVIDIA_DRIVER_CAPABILITIES`, `TORCH_CUDA_ARCH_LIST`, and `RUNPOD_TCP_PORT_22`. No `HF_TOKEN` was present in the probed container environment.

Source references found in `/app/ai-toolkit`:

- `run.py` calls `load_dotenv()`, sets `HF_HUB_ENABLE_HF_TRANSFER` default `1`, sets `NO_ALBUMENTATIONS_UPDATE=1`, sets `DISABLE_TELEMETRY=YES`, and reads optional `SEED` and `DEBUG_TOOLKIT`.
- `extensions_built_in/diffusion_models/ltx2/ltx2.py` and `flux2_model.py` read `HF_TOKEN` for Hugging Face downloads.
- `toolkit/config.py` expands `${VAR_NAME}` placeholders from `os.environ`.
- `toolkit/paths.py` reads optional `COMFY_PATH` and `MODELS_PATH`.
- UI-launched jobs set `AITK_JOB_ID`, `CUDA_VISIBLE_DEVICES`, `IS_AI_TOOLKIT_UI`, and optional UI-stored `HF_TOKEN`.
- `toolkit/timer.py` checks `IS_AI_TOOLKIT_UI`.

Astrid should not write literal secrets into `bootstrap.sh`. If `HF_TOKEN` is needed, it must be present in the pod environment or an ai-toolkit `.env` before `run.py` starts.
