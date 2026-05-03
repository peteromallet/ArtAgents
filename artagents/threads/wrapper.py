"""Runner chokepoint wrapper for thread run records."""

from __future__ import annotations

import contextvars
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from artagents._paths import REPO_ROOT

from .attribute import attribute_run, reap_orphans_once
from .ids import generate_run_id, is_ulid
from .prefix import emit_prefix, format_prefix_lines
from .record import build_run_record, finalize_run_record, write_run_record
from .variants import resolve_group_for_selection, update_groups_for_run, variant_prefix_message

THREAD_ID_ENV = "ARTAGENTS_THREAD_ID"
RUN_ID_ENV = "ARTAGENTS_RUN_ID"
PARENT_RUN_ID_ENV = "ARTAGENTS_PARENT_RUN_ID"
INHERITED_ENV = "ARTAGENTS_THREAD_INHERITED"
THREADS_OFF_ENV = "ARTAGENTS_THREADS_OFF"
REPO_ROOT_ENV = "ARTAGENTS_REPO_ROOT"

_ACTIVE_CONTEXT: contextvars.ContextVar["RunContext | None"] = contextvars.ContextVar("artagents_thread_context", default=None)


@dataclass
class RunContext:
    run_id: str
    thread_id: str
    kind: str
    out_path: Path
    repo_root: Path
    run_json_path: Path
    record: dict[str, Any]
    token: contextvars.Token | None = None


def begin_executor_run(request: Any, executor: Any) -> RunContext | None:
    if getattr(executor, "id", None) == "upload.youtube":
        return None
    return _begin_run(
        request=request,
        kind="executor",
        executor_id=getattr(executor, "id", None),
        orchestrator_id=None,
    )


def begin_orchestrator_run(request: Any, orchestrator: Any) -> RunContext | None:
    return _begin_run(
        request=request,
        kind="orchestrator",
        executor_id=None,
        orchestrator_id=getattr(orchestrator, "id", None),
    )


def finalize_result(context: RunContext | None, result: Any) -> None:
    if context is None:
        return
    returncode = getattr(result, "returncode", None)
    status = "succeeded" if returncode in (0, None) and bool(getattr(result, "ok", True)) else "failed"
    _finish(context, returncode=returncode, status=status, error=None)


def finalize_exception(context: RunContext | None, exc: BaseException) -> None:
    if context is None:
        return
    _finish(context, returncode=-1, status="error", error=exc)


def subprocess_env() -> dict[str, str]:
    context = _ACTIVE_CONTEXT.get()
    if context is None:
        return {}
    return {
        THREAD_ID_ENV: context.thread_id,
        RUN_ID_ENV: context.run_id,
        PARENT_RUN_ID_ENV: context.run_id,
        INHERITED_ENV: "1",
        REPO_ROOT_ENV: str(context.repo_root),
    }


def current_context() -> RunContext | None:
    return _ACTIVE_CONTEXT.get()


def _begin_run(*, request: Any, kind: str, executor_id: str | None, orchestrator_id: str | None) -> RunContext | None:
    if _should_noop(request):
        return None
    repo_root = _repo_root()
    out_path = _request_out(request)
    if out_path is None:
        return None
    out_path = out_path.expanduser().resolve()
    if not _is_under(out_path, repo_root):
        return None
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    reap_orphans_once(repo_root)
    run_id = generate_run_id()
    decision = attribute_run(
        repo_root=repo_root,
        request=request,
        run_id=run_id,
        out_path=out_path,
        label_seed=executor_id or orchestrator_id or kind,
    )
    thread_id = decision.thread_id
    parent_run_ids = _parent_edges(request)
    cli_args = _cli_args(request, executor_id=executor_id, orchestrator_id=orchestrator_id)
    record = build_run_record(
        run_id=run_id,
        thread_id=thread_id,
        kind=kind,
        executor_id=executor_id,
        orchestrator_id=orchestrator_id,
        out_path=out_path,
        repo_root=repo_root,
        inputs=getattr(request, "inputs", {}),
        brief=getattr(request, "brief", None),
        cli_args=cli_args,
        parent_run_ids=parent_run_ids,
    )
    run_json_path = out_path / "run.json"
    write_run_record(record, run_json_path)
    emit_prefix(
        format_prefix_lines(
            decision,
            variants=getattr(request, "variants", None),
            variants_message=variant_prefix_message(repo_root, thread_id),
        )
    )
    context = RunContext(
        run_id=record["run_id"],
        thread_id=thread_id,
        kind=kind,
        out_path=out_path,
        repo_root=repo_root,
        run_json_path=run_json_path,
        record=record,
    )
    context.token = _ACTIVE_CONTEXT.set(context)
    return context


def _finish(context: RunContext, *, returncode: int | None, status: str, error: BaseException | None) -> None:
    try:
        finalized = finalize_run_record(
            context.record,
            repo_root=context.repo_root,
            out_path=context.out_path,
            returncode=returncode,
            status=status,
            error=error,
        )
        update_groups_for_run(context.repo_root, finalized)
        context.record = finalized
        write_run_record(finalized, context.run_json_path)
    finally:
        if context.token is not None:
            _ACTIVE_CONTEXT.reset(context.token)
            context.token = None


def _should_noop(request: Any) -> bool:
    if os.environ.get(THREADS_OFF_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get(INHERITED_ENV, "").strip():
        return True
    if bool(getattr(request, "dry_run", False)):
        return True
    if getattr(request, "thread", None) == "@none":
        return True
    if _request_out(request) is None:
        return True
    if _is_temp_output(_request_out(request)):
        return True
    return False


def _request_out(request: Any) -> Path | None:
    raw = getattr(request, "out", None)
    if raw in (None, ""):
        return None
    return Path(raw)


def _repo_root() -> Path:
    return Path(os.environ.get(REPO_ROOT_ENV, REPO_ROOT)).expanduser().resolve()


def _parent_edges(request: Any) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    env_parent = os.environ.get(PARENT_RUN_ID_ENV, "").strip()
    if env_parent and is_ulid(env_parent):
        edges.append({"run_id": env_parent, "kind": "causal"})
    from_ref = getattr(request, "from_ref", None)
    if from_ref:
        raw = str(from_ref)
        run_id = raw.split(":", 1)[0]
        if is_ulid(run_id):
            edge = {"run_id": run_id, "kind": "chosen"}
            if ":" in raw:
                try:
                    index = int(raw.split(":", 1)[1].split(",", 1)[0])
                except ValueError:
                    index = 0
                if index > 0:
                    group = resolve_group_for_selection(_repo_root(), run_id, index)
                    if group:
                        edge["group"] = group
            edges.append(edge)
    return edges


def _cli_args(request: Any, *, executor_id: str | None, orchestrator_id: str | None) -> list[str]:
    args: list[str] = []
    if executor_id:
        args.extend(["executors", "run", executor_id])
    if orchestrator_id:
        args.extend(["orchestrators", "run", orchestrator_id])
    if (out := _request_out(request)) is not None:
        args.append(f"--out={out}")
    if getattr(request, "brief", None) not in (None, ""):
        args.append(f"--brief={getattr(request, 'brief')}")
    if getattr(request, "thread", None):
        args.append(f"--thread={getattr(request, 'thread')}")
    if getattr(request, "variants", None) is not None:
        args.append(f"--variants={getattr(request, 'variants')}")
    if getattr(request, "from_ref", None):
        args.append(f"--from={getattr(request, 'from_ref')}")
    for key, value in sorted(dict(getattr(request, "inputs", {}) or {}).items()):
        args.append(f"--input={key}={value}")
    for arg in getattr(request, "orchestrator_args", ()) or ():
        args.append(str(arg))
    return args


def _is_temp_output(path: Path | None) -> bool:
    if path is None:
        return True
    env_root = os.environ.get(REPO_ROOT_ENV, "").strip()
    if env_root:
        try:
            Path(path).expanduser().resolve().relative_to(Path(env_root).expanduser().resolve())
            return False
        except ValueError:
            pass
    try:
        Path(path).expanduser().resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
