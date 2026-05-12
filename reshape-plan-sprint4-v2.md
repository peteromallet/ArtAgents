# Implementation Plan: Sprint 4 — Lift RunPod to a peer Astrid capability (Rev 2)

## Overview

Move the generic "ship work to a GPU pod" recipe from `vibecomfy/scripts/runpod_runner.py` (~1.2k lines) into `runpod-lifecycle` v0.2, shrink vibecomfy to a thin shim that re-exports the same public surface including every name the existing test suite imports, then build a first-class Astrid pack `external.runpod` with four executors (`provision`, `exec`, `teardown`, `session`) and a `sweep` safety-net verb.

**Three repos are touched in order: (1) runpod-lifecycle → (2) vibecomfy → (3) Astrid.** The vibecomfy stop-line is non-negotiable: do NOT start the Astrid pack until `pytest vibecomfy/tests/` passes with zero source changes AND the three vibecomfy scripts import cleanly.

**Branch**: `reshape/sprint-4` off `reshape/sprint-3`.
**Working dir**: `/Users/peteromalley/Documents/reigh-workspace/Astrid`.
**Cross-repo dirs**: `../runpod-lifecycle`, `../vibecomfy`.

### Critical codebase ground truth (verified against current repo state)

- **`launch` is at `lifecycle.py:64`**, NOT `runner.py` (which does not exist yet). The pre-resolved finding stating `runner.py` was incorrect — this plan creates `runner.py` as a NEW module that imports `launch` from `lifecycle.py`.
- **`Pod.is_idle(threshold_seconds)` at `pod.py:102-118`** — async method, queries GPU utilization via SSH. Used directly by the sweeper.
- **`append_event_locked` at `events.py:92-161`** — signature is `expected_writer_epoch: int` (NOT `int | None`). The brief's claim that `None` bypass exists is FALSE. This plan adds an explicit code change to support `expected_writer_epoch: int | None = None` with a bypass when `None`.
- **Cost consumed via sidecar** — `local.py:139-155` (`_read_cost_sidecar`) reads `produces/cost.json`. Subprocess executors write this file; there is NO stdout JSON parsing path. This plan uses sidecar files exclusively.
- **`discovery.list_pods` at `discovery.py:64`** — async, returns `list[PodSummary]`. `PodSummary` is a frozen dataclass at `discovery.py:19-31`.
- **`NETWORK_VOLUMES_URL` at `api.py:20`** — `https://api.runpod.io/v1/networkvolumes`. `create_network_volume` POSTs here.
- **Vibecomfy tests at `test_runpod_runner.py`** import: `should_skip` (L34), `_build_upload_tarball` (L50), `_preflight_upload_disk` (L62), `_runpod_config_kwargs` (L76), `_parse_tsv` (L95), `_png_info` (L105), `_finalize_artifacts` (L151), `_build_artifact_manifest` (L191), `PodGuard` (L212), `install_signal_handlers` (L213), `run_pod` (L215), `DEFAULT_UPLOAD_EXCLUDES` (L22).
- **Detached polling at `runpod_runner.py:375-424`** hardcodes vibecomfy-specific paths (`out/corpus_matrix/exit_code`, etc.). The generic `ship_and_run_detached` must parameterize these.
- **`doctor.py:164-182`** has `_check_vibecomfy_metadata` — NOT modified for runpod in this sprint (out of scope per brief).

## Phase 1: runpod-lifecycle v0.2 — Substrate Lift

### Step 1: Audit current lifecycle and vibecomfy seams
**Scope:** Small — read-only, no code changes.
**Repo:** `runpod-lifecycle`, `vibecomfy`

1. **Confirm** the existing surface area by reading every `.py` under `runpod-lifecycle/src/runpod_lifecycle/` (11 files). Key reference points:
   - `launch` at `lifecycle.py:64` (async, returns `Pod`)
   - `Pod.is_idle()` at `pod.py:102-118` (async)
   - `Pod.terminate()` at `pod.py:120-127` (async)
   - `api.create_pod`, `api.terminate_pod`, `api.get_pod_status`, `api.get_pod_ssh_details`, `api.get_network_volumes`, `api.find_gpu_type`
   - `discovery.list_pods(name_prefix=...)` at `discovery.py:64` (async)
   - `discovery.get_pod(pod_id, config)` at `discovery.py:111` (async, returns `Pod`)
   - `NETWORK_VOLUMES_URL = "https://api.runpod.io/v1/networkvolumes"` at `api.py:20`
   - `RunPodConfig` at `config.py`, `SSHClient` at `ssh.py`
2. **Map** the functions to lift from `vibecomfy/scripts/runpod_runner.py`:
   - `PodGuard` (L103-149) — watchdog + signal handlers
   - `install_signal_handlers` (L205-232) — opt-in signal handler registration
   - `UploadHeartbeat` (L79-100) — progress heartbeat
   - `should_skip` (L168-174) — exclude-set matcher
   - `upload_dir` (L177-202) — sftp_walk upload
   - `_build_upload_tarball` (L1150-1178) — plus helpers `_iter_upload_files` (L1107), `_estimate_upload_payload` (L1120), `_preflight_upload_disk` (L1136), `_upload_tmpdir` (L1100)
   - `_upload_tarball` (L1052-1097) — tarball upload flow
   - `_upload_remote_script` (L466-488) — upload + chmod the remote script
   - `_download_artifacts` (L491-545) — pull + extract artifact archive
   - `run_pod` (L243-306) — sync exec
   - `run_pod_detached` (L308-453) — detached-with-poll exec
   - Helper functions: `_format_bytes` (L59), `_log_phase` (L69), `_log_pod_identity` (L74)
3. **Read** `vibecomfy/tests/test_runpod_runner.py` end-to-end (224 lines) and record every import:
   - `should_skip`, `_build_upload_tarball`, `_preflight_upload_disk`, `_runpod_config_kwargs`, `_parse_tsv`, `_png_info`, `_finalize_artifacts`, `_build_artifact_manifest`, `PodGuard`, `install_signal_handlers`, `run_pod`, `DEFAULT_UPLOAD_EXCLUDES`
   - These ALL must be re-exported by the post-shrink shim.

### Step 2: Add `guard.py` + `shipping.py` to runpod-lifecycle
**Scope:** Medium — new code, mostly lifted verbatim.
**Repo:** `runpod-lifecycle`

1. **Create `runpod-lifecycle/src/runpod_lifecycle/guard.py`** containing:
   - `PodGuard` lifted from `runpod_runner.py:103-149`, with additions:
     - Constructor param `auto_terminate: bool = True`.
     - When `auto_terminate=False`: the `_terminate_after` watchdog still fires on `max_runtime_seconds` elapsed, but instead of calling `self.pod.terminate()`, it appends a breach record to `self.breach_log: list[dict]` (an in-memory list, NOT persisted to any artifact) and emits a warning via `print(f"watchdog_breach pod_id={self.pod.id} ...", flush=True)`. Caller is responsible for termination.
     - When `auto_terminate=True` (default): existing behavior — terminates the pod.
   - `install_signal_handlers(loop)` lifted from L205-232. Sets up SIGINT/SIGTERM → CancelledError.
   - One-line module docstring.
2. **Create `runpod-lifecycle/src/runpod_lifecycle/shipping.py`** containing:
   - `UploadHeartbeat` (L79-100)
   - `should_skip` (L168-174)
   - `upload_dir` (L177-202) — sftp_walk upload
   - `_build_upload_tarball` (L1150-1178) + helpers: `_iter_upload_files` (L1107), `_estimate_upload_payload` (L1120), `_preflight_upload_disk` (L1136), `_upload_tmpdir` (L1100)
   - `_upload_tarball` (L1052-1097)
   - `_upload_remote_script` (L466-488)
   - `download_artifact_archive` — renamed from `_download_artifacts` (L491-545), now a public function. Accepts `pod`, `remote_root`, `local_dest: Path`, `artifact_paths: list[str]` (the remote paths to archive and pull). Returns `Path | None` (local artifact root).
   - All functions keep identical signatures; do NOT rename internal helpers needed by vibecomfy tests.
   - Change internal references from `ROOT` (vibecomfy's repo root) to a parameter `local_root: Path` passed by the caller.
   - One-line module docstring.
3. **Export symbols**: add `guard` and `shipping` to `__init__.py`'s `__all__`.

### Step 3: Create `runner.py` with `ship_and_run` / `ship_and_run_detached`
**Scope:** Large — new orchestration module composing lifecycle primitives.
**Repo:** `runpod-lifecycle`

1. **Create `runpod-lifecycle/src/runpod_lifecycle/runner.py`**.
2. **Import** `launch` from `.lifecycle` (it lives at `lifecycle.py:64`, NOT in this file).
3. **Define** `ShipAndRunResult` dataclass:
   ```python
   @dataclass
   class ShipAndRunResult:
       returncode: int
       stdout: str
       stderr: str
       pod: Pod | None          # None if terminate_after_exec=True
       artifact_root: Path | None
       breach_log: list[dict]   # from PodGuard, populated when auto_terminate=False
       terminated: bool
       upload_info: dict[str, Any]
   ```
4. **Implement `ship_and_run(...)`** (sync exec — launches, uploads, runs, waits):
   - Parameters: `config: RunPodConfig`, `remote_script: str`, `*`, `local_root: Path`, `remote_root: str`, `exclude: set[str]`, `upload_mode: Literal["sftp_walk", "tarball"] = "sftp_walk"`, `timeout: int`, `name_prefix: str`, `terminate_after_exec: bool = True`, `guard_factory: Callable[..., PodGuard] | None = None`.
   - `guard_factory` defaults to `PodGuard`; tests (vibecomfy's `test_runpod_runner.py:197-224`) inject mocks via monkeypatching the shim's `PodGuard` reference.
   - When `terminate_after_exec=True`: terminates in `finally` (existing vibecomfy behavior).
   - When `terminate_after_exec=False`: skips termination in `finally`, returns `pod` in result. Sets `auto_terminate=False` on the guard so the watchdog warns but doesn't terminate.
   - Handles `asyncio.CancelledError` → returncode 130, terminate.
   - Orchestration flow: launch → wait_ready → gpu_check → upload (sftp or tarball) → exec_ssh(remote_script) → return result.
5. **Implement `ship_and_run_detached(...)`** (detached-with-poll exec):
   - Same parameters as `ship_and_run` plus `poll_interval: int = 60`, `poll_command_template: str | None = None`, `poll_exit_marker: str | None = None`, `artifact_paths: list[str] | None = None`.
   - `poll_command_template`: a bash command string for status polling. Default: a generic template with `{remote_root}`, `{exit_marker}` placeholders.
   - `poll_exit_marker`: remote file path that contains the exit code when the detached job finishes. Default: `"/tmp/runpod-lifecycle-exit-code"`.
   - `artifact_paths`: remote paths to archive and download after completion. Default: `["out", "output"]`.
   - The polling loop uses `pod.exec_ssh(poll_command)` every `poll_interval` seconds.
   - **No vibecomfy-specific paths baked in** — the detach command, exit marker, and artifact paths are parameterized. Vibecomfy's shim supplies its own paths (`out/corpus_matrix/exit_code`, etc.).
   - On completion: calls `shipping.download_artifact_archive(pod, remote_root, local_dest, artifact_paths)` to pull results.
6. **One-line module docstring**. Type hints throughout.
7. **Export** `ship_and_run`, `ship_and_run_detached`, `ShipAndRunResult` from `__init__.py`.

### Step 4: Storage create + Pod composable surface
**Scope:** Small.
**Repo:** `runpod-lifecycle`

1. **Add `api.create_network_volume(api_key, name, size_gb, datacenter_id)`** to `api.py`:
   - POST to `https://api.runpod.io/v1/networkvolumes` (same `NETWORK_VOLUMES_URL` at `api.py:20`).
   - Payload: `{"name": name, "size": size_gb, "dataCenterId": datacenter_id}`.
   - Returns the created volume dict with `id`.
2. **Add to `Pod` class** at `pod.py`:
   - `async upload_path(local: Path, remote: str, *, exclude: set[str] | None = None, mode: str = "sftp")` — thin facade calling `shipping.upload_dir` or `shipping._upload_tarball`.
   - `async download_archive(remote: str, local: Path)` — thin facade calling `shipping.download_artifact_archive`.
   - `async create_storage(name: str, size_gb: int, datacenter_id: str)` — thin facade calling `api.create_network_volume`.
   - `async list_storages()` — thin facade calling `api.get_network_volumes` filtered by account.
   - `async get_storage(name_or_id: str)` — thin facade: list all, match by name or id.
   - **No `volume delete`** in V1.
3. **Update `storage.py`** if needed for `create_network_volume` integration (e.g., add a `create_storage_volume` helper that wraps the POST + returns the volume id).

### Step 5: CLI verbs
**Scope:** Small.
**Repo:** `runpod-lifecycle`

1. **Modify `runpod-lifecycle/src/runpod_lifecycle/cli.py`** (or equivalent CLI entrypoint) to add:
   - `launch [--detach]` — wraps `lifecycle.launch`
   - `exec <pod_id> -- <cmd>` — attaches via `discovery.get_pod`, runs `pod.exec_ssh(cmd)`
   - `ship <pod_id> --local <dir> --remote <path>` — attaches + `pod.upload_path`
   - `fetch <pod_id> --remote <path> --local <dir>` — attaches + `pod.download_archive`
   - `run <pod_id> --script <file>` — attaches + `runner.ship_and_run` with `terminate_after_exec=False`
   - `volumes ls` — `api.get_network_volumes` pass-through
   - `volume create <name> <size_gb> [--datacenter <id>]` — `api.create_network_volume`
   - **No** one-shot `ship-and-run` CLI verb (library-first).
   - **No `volume delete`**.

### Step 6: Lifecycle tests + v0.2 tag
**Scope:** Medium.
**Repo:** `runpod-lifecycle`

1. **Add unit tests** (mocked, no live RunPod calls):
   - `tests/test_guard.py` — `PodGuard` with `auto_terminate={True,False}`, `breach_log` populated on False, `guard_factory` injection.
   - `tests/test_shipping.py` — `should_skip` edge cases, `_build_upload_tarball` with excludes, `_preflight_upload_disk` fail path.
   - `tests/test_runner.py` — `ship_and_run` with `terminate_after_exec={True,False}`, `guard_factory` mock, `CancelledError` path, `ship_and_run_detached` with parameterized poll targets.
   - `tests/test_api.py` — `create_network_volume` POST shape, error handling.
   - `tests/test_pod.py` — `Pod.get_storage` find-by-name path, `Pod.create_storage` passthrough.
2. **Add live-pod tests** gated behind `RUNPOD_LIVE_TESTS=1`:
   - sftp_walk upload, tarball upload, sync exec, detached-with-poll exec, reattach by pod_id, `terminate_after_exec=False` round-trip.
   - Document cost per test in the test module docstring.
3. **Run `pytest`** in `runpod-lifecycle/`. Green.
4. **Tag `v0.2.0`** with `git tag v0.2.0`. Commit message: "v0.2: guard, shipping, runner.ship_and_run{,_detached}, storage create, CLI verbs."

## Phase 2: Vibecomfy Shrink — Stop-line

### Step 7: Shrink `vibecomfy/scripts/runpod_runner.py`
**Scope:** Large.
**Repo:** `vibecomfy`

1. **Keep** (do NOT lift — these stay in vibecomfy):
   - `ROOT` (L20) — required by `runpod_corpus_matrix.py`.
   - `REMOTE_ROOT` (L21), `DEFAULT_UPLOAD_EXCLUDES` (L24-41), `MiB` (L22).
   - `_runpod_config_kwargs` (L152-165) — vibecomfy's env-var conventions.
   - Artifact-format readers: `_parse_tsv`, `_png_info`, `_image_info`, `_finalize_artifacts`, `_build_artifact_manifest`, `_collect_outputs`, `_collect_run_metadata`, `_collect_watchdogs`, `_collect_remote_logs`, `_write_artifact_report`, `_print_detached_summary`, `_parse_detached_exit`, plus helpers `_file_record`, `_sha256`, `_load_json`, `_load_watchdog_json`, `_extract_prompt_id`, `_count_failures`, `_display_path`, `_md`, `_new_artifact_root`, `_format_bytes`.
   - These read vibecomfy-shaped paths (`out/corpus_matrix/`, `out/runs/`, `out/runpod_artifacts/`) and are genuinely consumer concerns.
2. **Re-export** from `runpod_lifecycle`:
   - `run_pod` — thin async wrapper calling `runpod_lifecycle.runner.ship_and_run`, then layering vibecomfy's `_finalize_artifacts` + `_print_detached_summary` on the result. Supplies vibecomfy-specific paths for the detached poll command (`out/corpus_matrix/exit_code`, etc.) via the parameterized interface.
   - `run_pod_detached` — thin async wrapper calling `ship_and_run_detached` with vibecomfy-specific `poll_command_template`, `poll_exit_marker="out/corpus_matrix/exit_code"`, `artifact_paths=["out/corpus_matrix", "output", "out/runs"]`.
   - `PodGuard` — re-exported as a module attribute (NOT instantiated in the shim). This preserves `test_runpod_runner.py:212`'s `monkeypatch.setattr(runpod_runner, "PodGuard", FakeGuard)`.
   - `install_signal_handlers` — re-exported from `runpod_lifecycle.guard.install_signal_handlers`. This preserves `test_runpod_runner.py:213`'s monkeypatch.
   - `should_skip` — re-exported from `runpod_lifecycle.shipping.should_skip`. Preserves `test_runpod_runner.py:34`.
   - `_build_upload_tarball` — re-exported. Preserves `test_runpod_runner.py:50`.
   - `_preflight_upload_disk` — re-exported. Preserves `test_runpod_runner.py:62`.
   - `UploadHeartbeat` — re-exported (used internally by `run_pod`).
3. **Remove** all lifted internals (~1k lines). Target ≤ 300 lines.
4. **`_runpod_lifecycle()` helper** (L456-463) updates to import from the v0.2 package rather than the `sys.path` hack for older versions.

### Step 8: Vibecomfy regression — the stop-line
**Scope:** Small.
**Repo:** `vibecomfy`

1. **Run `pytest vibecomfy/tests/`** — every existing test must pass with ZERO source changes:
   - `test_runpod_runner.py:197-224` (cancellation test, monkeypatches `PodGuard` + `install_signal_handlers`) → green.
   - `test_runpod_runner.py:22-36` (uses `should_skip` + `DEFAULT_UPLOAD_EXCLUDES`) → green.
   - `test_runpod_runner.py:39-58` (uses `_build_upload_tarball`) → green.
   - `test_runpod_runner.py:61-68` (uses `_preflight_upload_disk`) → green.
   - All other tests → green.
2. **Smoke-import** the three consumer scripts:
   - `python -c "from scripts.runpod_runner import run_pod, run_pod_detached, REMOTE_ROOT, DEFAULT_UPLOAD_EXCLUDES, ROOT, PodGuard"`
   - Verify `ROOT` resolves correctly for `runpod_corpus_matrix.py`.
   - Verify all three scripts (`runpod_validate.py`, `runpod_model_matrix.py`, `runpod_corpus_matrix.py`) import cleanly.
3. **STOP-LINE**: If ANY test fails or ANY import breaks, halt. Reshape the lifecycle public API surface (Steps 3-4) and retry before tagging v0.2. Do NOT advance to Phase 3.

## Phase 3: Astrid Pack `external.runpod`

### Step 9: Create the pack skeleton
**Scope:** Small.
**Repo:** `Astrid`

1. **Create directory** `astrid/packs/external/runpod/`.
2. **Create files** mirroring `astrid/packs/external/vibecomfy/`:
   - `executor.yaml` — `{"executors": [...]}` dict-wrapping-array format (matches `_validate_manifest_payload`). Four executors: `external.runpod.provision`, `external.runpod.exec`, `external.runpod.teardown`, `external.runpod.session`.
   - `run.py` — argparse dispatcher (stub, implemented in Step 10).
   - `STAGE.md` — pack overview.
   - `requirements.txt` — `runpod-lifecycle>=0.2`.
   - `__init__.py` — empty or one-line docstring.
3. **Register** the pack in `astrid/packs/external/pack.yaml`:
   ```yaml
   id: external
   name: Astrid External Tools
   version: 1.0.0
   packs:
     - id: runpod
       path: runpod/
   ```
   (Extend the existing 3-line file with a `packs` list.)

### Step 10: Implement four executors in `run.py`
**Scope:** Large.
**Repo:** `Astrid`

1. **Argparse dispatcher** with subcommands `provision | exec | teardown | session`. All use `adapter: local`. No `sys.path` hack (runs inside `astrid`).
2. **`provision` executor**:
   - Inputs: `gpu_type`, `storage_name`, `max_runtime_seconds`, `name_prefix`, `image`, `container_disk_gb`, `datacenter_id` (all optional with pack-level defaults).
   - Calls `runpod_lifecycle.lifecycle.launch(config)` to create the pod.
   - Writes `pod_handle.json` at canonical produces path (`steps/<id>/v<N>/[iterations/NNN/]produces/pod_handle.json`) per locked schema:
     ```json
     {
       "pod_id": "...",
       "ssh": "root@<ip> -p <port>",
       "name": "<full pod name>",
       "name_prefix": "<prefix>",
       "terminate_at": "<ISO-8601>",
       "gpu_type": "...",
       "hourly_rate": 0.34,
       "provisioned_at": "<ISO-8601 timestamp>",
       "config_snapshot": {
         "api_key_ref": "RUNPOD_API_KEY",
         "datacenter_id": "...",
         "image": "...",
         "container_disk_in_gb": 30,
         "volume_in_gb": 0,
         "network_volume_id": null,
         "ports": "8888/http,22/tcp"
       }
     }
     ```
   - `config_snapshot.api_key_ref` stores the env var name, NEVER the literal key.
   - `hourly_rate` at top-level so exec/teardown reuse it without re-querying pricing API.
   - Writes `produces/cost.json` with provision-fraction cost (per `_read_cost_sidecar` convention).
   - **Does NOT terminate**. Leaves pod alive.
3. **`exec` executor**:
   - Inputs: `pod_handle` (required), `local_root`, `remote_root`, `remote_script`, `timeout`, `upload_mode`, `excludes` (with pack defaults).
   - Reads `pod_handle.json`, reconstructs `RunPodConfig` from `os.environ[config_snapshot.api_key_ref]` + snapshot fields.
   - Reattaches via `discovery.get_pod(pod_id, config)`.
   - Runs `ship_and_run_detached` with `terminate_after_exec=False`, `auto_terminate=False`.
   - Downloads artifacts to `artifact_dir` inside the produces path.
   - Writes `produces/exec_result.json` + `produces/cost.json` (exec-window fraction using `handle.hourly_rate`).
   - **Leaves pod alive**.
4. **`teardown` executor**:
   - Inputs: `pod_handle` (required).
   - Reads handle, reattaches via `discovery.get_pod`, calls `pod.terminate()`.
   - **Idempotent**: catches "not found" → no-op.
   - Writes `produces/teardown_receipt.json` + `produces/cost.json` (final settle-up using `handle.hourly_rate`).
5. **`session` executor** (composite):
   - Inputs: same as provision + exec combined.
   - Flow:
     1. Provision pod (same as `provision` executor).
     2. **IMMEDIATELY write `pod_handle.json`** at canonical produces path (breadcrumb for sweeper on crash).
     3. Exec + download artifacts (same as `exec` executor).
     4. `finally:` terminate pod + **delete `pod_handle.json`**.
   - On graceful exit: handle is gone, `session.exec_result.json` + `cost.json` remain.
   - On crash (OOM/SIGKILL/segfault): `pod_handle.json` survives → sweeper picks it up.
   - Emits a single combined cost (sum of provision + exec + teardown).
6. **Cost summation invariant**: `provision.cost + exec.cost + teardown.cost == session.cost` for the same pod. Exec and teardown use `handle.hourly_rate` (provision-time pricing), NOT a fresh query.
7. **Subprocess executors write cost via `produces/cost.json`** (existing `_read_cost_sidecar` convention at `local.py:139-155`). They do NOT call `append_event_locked` directly (they don't hold the writer lease). The parent process (`astrid next` lifecycle) reads the sidecar and writes the completion event.

### Step 11: `astrid runpod sweep` verb
**Scope:** Medium — new module + pipeline wiring.
**Repo:** `Astrid`

1. **Create `astrid/core/runpod/sweeper.py`** with:
   - `collect_handles(projects_root: Path) -> list[tuple[Path, dict]]` — walks `astrid-projects/<project>/runs/<run-ulid>/steps/<step-id>/v<N>/[iterations/NNN/]produces/pod_handle.json`, parses each, returns `[(path, handle_dict), ...]`.
   - `sweep(projects_root: Path, *, mode: str = "default") -> list[dict]` — main sweep logic:
     - For each handle: parse `terminate_at`, check if passed. If not, skip.
     - For each handle: parse `name_prefix`, call `discovery.list_pods(api_key, name_prefix=name_prefix)` async, correlate by `handle.name` against `PodSummary.name`.
     - **Default mode**: terminate only if ALL of:
       1. `terminate_at` has passed.
       2. No live session ack'd — check the owning run's `lease.json`:
          - Read `runs/<run_id>/lease.json`. If `attached_session_id` is set AND `writer_epoch > 0`, a session is actively writing → skip.
       3. Pod is idle — use `Pod.is_idle(threshold_seconds=300)` at `pod.py:102-118`. This queries GPU utilization via SSH; if <5% for 300s, pod is idle.
     - **`--hard` mode**: bypasses live-session check and idle check. Still requires `terminate_at` passed.
   - For every termination, append `pod_terminated_by_sweep` event to the owning run's `events.jsonl`:
     ```json
     {"kind": "pod_terminated_by_sweep", "pod_id": "...", "terminate_at": "...", "mode": "default", "reason": "..."}
     ```
   - Event append uses `append_event_locked` (sweeper runs as CLI verb, session-bound → holds or acquires a lease). See Step 11.2 for `--hard` mode lease handling.
2. **Modify `astrid/core/task/events.py`** to support sweeper bypass:
   - Change `append_event_locked` signature: `expected_writer_epoch: int | None = None` (with default).
   - In the body (L131): when `expected_writer_epoch` is `None`, skip the epoch CAS check (only check tail hash). This is the administrative-bypass for `--hard` mode.
   - When `expected_writer_epoch` is an `int`, existing strict-equality behavior is unchanged.
   - `StaleEpochError`'s `expected` field becomes `int | None`.
3. **Sweeper `--hard` mode**:
   - In default mode: sweeper reads the current `writer_epoch` + `tail_hash` from the run's lease/events files, passes real values to `append_event_locked` → CAS-checked append. If the run is actively being written by another process, the sweeper may get `StaleEpochError` or `StaleTailError` → skip (default) or retry once (`--hard`).
   - In `--hard` mode: sweeper passes `expected_writer_epoch=None` (bypass) and the current tail hash. This guarantees the event lands even against an active writer.
   - **Hash-chain integrity under `--hard`**: test by holding a writer lease in one process, running sweep `--hard` in another, verifying the `pod_terminated_by_sweep` event lands and `verify_chain` passes.
4. **Register the verb** in `astrid/pipeline.py`:
   - Add dispatch in `_dispatch` function (near L280): `if raw and raw[0] == "runpod": return _dispatch_runpod(raw[1:])`.
   - Add `_dispatch_runpod(args)` function dispatching sub-verbs: `sweep` → import `astrid.core.runpod.sweeper` and run.
   - `runpod sweep` is NOT added to `_verb_is_unbound_allowlisted` — it requires a session context to resolve `projects_root`. (It follows the same pattern as `doctor`.)
   - `astrid runpod volumes ls` IS added to `_verb_is_unbound_allowlisted` (read-only, no session needed).

### Step 12: `astrid runpod ensure-storage` + `volumes ls`
**Scope:** Small.
**Repo:** `Astrid`

1. **Create `astrid/core/runpod/storage.py`** with:
   - `ensure_storage(name: str, *, size_gb: int = 50, datacenter_id: str, api_key: str) -> dict` — calls `Pod.get_storage(name)`, if missing calls `Pod.create_storage(name, size_gb, datacenter_id)`. Idempotent. No cost event (treated as infra).
   - `list_volumes(api_key: str) -> list[dict]` — pass-through to `api.get_network_volumes`.
2. **Provision/session executors do NOT auto-create**: they error clearly when `storage_name` resolves to nothing. Only `ensure-storage` creates.
3. **Wire** both verbs into `astrid/pipeline.py`:
   - `runpod ensure-storage <name> [--size <GB>] [--datacenter <id>]` — NOT in unbound allowlist (needs project context for default datacenter).
   - `runpod volumes ls` — IN unbound allowlist (pure passthrough, read-only).

### Step 13: `astrid doctor` integration
**Scope:** Small.
**Repo:** `Astrid`

1. **Add `_check_runpod_stale_handles`** to `astrid/doctor.py:run_checks()`:
   - Reuses `collect_handles` from `astrid/core/runpod/sweeper.py` (scan logic).
   - Reports count of stale handles (`terminate_at` passed, handle still on disk).
   - **Read-only**: never calls `terminate()` or `append_event_locked`.
   - Output format: `[{status}] runpod stale handles: N stale handle(s) found` (status = "warn" if >0, "ok" if 0).
2. **Do NOT add a symmetric `_check_runpod_metadata`** — out of scope per brief. The `_check_vibecomfy_metadata` at `doctor.py:164-182` remains unchanged. Adding generic metadata validation for all external packs is a future improvement.
3. **Update** `tests/test_doctor_setup.py` if needed for the new check line.

## Phase 4: Tests

### Step 14: Pack tests (`tests/packs/runpod/`)
**Scope:** Medium.
**Repo:** `Astrid`

1. **Create `tests/packs/runpod/`** directory with `__init__.py`.
2. **`test_pack_executors.py`** — provision/exec/teardown/session round-trip with mocked `runpod_lifecycle`:
   - Mock `lifecycle.launch` → returns a fake `Pod`.
   - Mock `discovery.get_pod` → returns the same fake `Pod`.
   - Mock `Pod.is_idle`, `Pod.exec_ssh`, `Pod.terminate`.
   - Assert `pod_handle.json` schema (all required fields present).
   - Assert `exec_result.json` shape.
   - Assert `produces/cost.json` shape per `_read_cost_sidecar` contract.
   - Assert cost summation invariant.
3. **`test_sweeper.py`** — mocked lifecycle:
   - Default-mode skip: `terminate_at` not passed, live session ack'd (lease.json with active writer), pod not idle (`Pod.is_idle` returns False).
   - Default-mode terminate: all checks pass → terminate called, event appended.
   - `--hard` mode: bypasses live-session + idle checks, terminates past-due pods.
   - Verify `pod_terminated_by_sweep` event shape + `events.jsonl` append.
   - Hash-chain integrity under `--hard` against active run: hold writer lease in test process, run sweeper `--hard`, verify event lands and chain verifies.
4. **`test_ensure_storage.py`** — find path + create path against mocked lifecycle:
   - `Pod.get_storage` returns existing volume → no create call.
   - `Pod.get_storage` returns None → `Pod.create_storage` called.
   - Verify provision/session executors do NOT auto-create (they raise/error when storage resolves to nothing).
5. **`test_doctor_integration.py`** — stale-handle reporting:
   - Set up a `pod_handle.json` with expired `terminate_at`.
   - Run doctor check → reports stale.
   - Assert no termination calls, no event emission.
6. **`test_session_oom_breadcrumb.py`**:
   - Session executor with a crashing remote script (`kill -9 $$`).
   - Verify `pod_handle.json` left behind at canonical produces path.
   - Verify sweeper picks it up and terminates the pod.

### Step 15: Live tests (gated, `RUNPOD_LIVE_TESTS=1`)
**Scope:** Small — human operator runs on demand, never auto-spends GPU credits.
**Repo:** `Astrid`

1. **End-to-end session smoke**:
   - Create a plan-template invocation of `external.runpod.session` with `remote_script="nvidia-smi -L; echo ok"`.
   - Verify `exec_result.json` exists with non-zero `cost` and populated `artifact_dir/`.
   - Document cost: ~$0.01–$0.05 for a 4090 (~1 minute).
2. **End-to-end sweeper**:
   - Provision via `external.runpod.provision`, kill the orchestrator process before teardown runs.
   - Run `astrid runpod sweep` → verify (a) pod is terminated through lifecycle API, (b) `pod_terminated_by_sweep` event lands in `events.jsonl`.
   - Re-run with `--hard` against a deliberately ack'd handle → verify bypass path works.
   - Document cost: ~$0.01 per test (pod billed for a few minutes).

### Step 16: Full suite regression
**Scope:** Small.

1. **Run `pytest tests/`** in Astrid. All Sprint 0-3 tests green (modulo the 7 pre-existing unrelated failures verified in S2).
2. **Run `pytest vibecomfy/tests/`** in vibecomfy. Green.
3. **Run `pytest`** in `runpod-lifecycle/`. Green.

## Execution Order

1. **Phase 1** (Steps 1-6) in strict order. Tag v0.2 only after Step 8's stop-line clears.
2. **Phase 2** (Steps 7-8). HARD STOP at Step 8 if vibecomfy regresses — do NOT advance.
3. **Phase 3** (Steps 9-13). Pack skeleton (9) → executors (10) → sweeper (11, depends on events.py mod) → ensure-storage (12) → doctor (13). Events.py mod (Step 11.2) can be done early since it's a prerequisite for the sweeper.
4. **Phase 4** (Steps 14-16). Unit tests after Phase 3 code lands, live tests on demand, full regression last.

## Validation Order

1. Unit-level: `pytest runpod-lifecycle/tests/` (mocked) after Phase 1 Step 6.
2. Vibecomfy regression after Phase 2 Step 8 (stop-line).
3. Pack unit tests after Phase 3.
4. Live tests gated, optional.
5. Full cross-repo regression last.