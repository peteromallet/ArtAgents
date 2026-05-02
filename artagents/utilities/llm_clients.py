#!/usr/bin/env python3
"""Lazy SDK wrappers for Claude and Gemini JSON calls."""

from __future__ import annotations

import base64
import inspect
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


_IMAGE_BLOCK_ALLOWED_KEYS = frozenset({"type", "source", "cache_control"})
_LLM_DEBUG_LOCK = threading.Lock()


def _materialize_image_source(block: dict[str, Any]) -> dict[str, Any]:
    # Claude's vision API accepts source types `base64` and `url` only.
    # Callers often pass `{"type": "path", "path": "/abs/foo.jpg"}` for
    # ergonomics — transform those to base64 here so call sites don't
    # have to duplicate the encoding boilerplate. Also strip any caller
    # metadata (e.g. `label`) the API rejects as unknown fields.
    if block.get("type") != "image":
        return block
    source = block.get("source") or {}
    new_block = {k: v for k, v in block.items() if k in _IMAGE_BLOCK_ALLOWED_KEYS}
    if source.get("type") == "path":
        path = Path(source["path"])
        data = path.read_bytes()
        media_type = source.get("media_type") or mimetypes.guess_type(path.name)[0] or "image/jpeg"
        new_block["source"] = {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        }
    return new_block


def _materialize_message_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            new_content = [_materialize_image_source(block) if isinstance(block, dict) else block for block in content]
            out.append({**message, "content": new_content})
        else:
            out.append(message)
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        for kwargs in ({"mode": "json"}, {}):
            try:
                return _jsonable(model_dump(**kwargs))
            except TypeError:
                continue
            except Exception:
                break
    return str(value)


def _candidate_output_paths(frame_locals: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    args = frame_locals.get("args")
    if args is not None:
        for attr in ("out", "brief_out"):
            value = getattr(args, attr, None)
            if value is not None:
                candidates.append(Path(value))
    for key in ("out_dir", "out", "brief_out"):
        value = frame_locals.get(key)
        if value is not None:
            candidates.append(Path(value))
    video_path = frame_locals.get("video_path")
    if video_path is not None:
        candidates.append(Path(video_path).resolve().parent)
    return candidates


def _run_root_for_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.name == "briefs":
        return resolved.parent
    for ancestor in resolved.parents:
        if ancestor.name == "briefs":
            return ancestor.parent
    return resolved if resolved.is_dir() else resolved.parent


def _llm_debug_context() -> tuple[Path, str] | None:
    for frame_info in inspect.stack()[2:]:
        frame_path = Path(frame_info.filename)
        stage = frame_path.stem
        if stage == Path(__file__).stem:
            continue
        for candidate in _candidate_output_paths(frame_info.frame.f_locals):
            run_root = _run_root_for_path(candidate)
            debug_dir = run_root / "_llm_debug"
            return debug_dir, stage
    return None


def _next_debug_sequence(debug_dir: Path, stage: str) -> int:
    highest = 0
    for path in debug_dir.glob(f"{stage}.*.request.json"):
        parts = path.name.split(".")
        if len(parts) < 4:
            continue
        try:
            highest = max(highest, int(parts[1]))
        except ValueError:
            continue
    return highest + 1


def _start_debug_log(provider: str, payload: dict[str, Any]) -> tuple[Path, Path, int, str] | None:
    context = _llm_debug_context()
    if context is None:
        return None
    debug_dir, stage = context
    debug_dir.mkdir(parents=True, exist_ok=True)
    with _LLM_DEBUG_LOCK:
        seq = _next_debug_sequence(debug_dir, stage)
        request_path = debug_dir / f"{stage}.{seq:04d}.request.json"
        response_path = debug_dir / f"{stage}.{seq:04d}.response.json"
        request_path.write_text(json.dumps({"provider": provider, **payload}, indent=2) + "\n", encoding="utf-8")
    return request_path, response_path, seq, stage


def _finish_debug_log(
    context: tuple[Path, Path, int, str] | None,
    *,
    provider: str,
    model: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    if context is None:
        return
    request_path, response_path, seq, stage = context
    response_path.write_text(json.dumps({"provider": provider, **payload}, indent=2) + "\n", encoding="utf-8")
    summary = {
        "ts": _utc_now(),
        "provider": provider,
        "stage": stage,
        "seq": seq,
        "model": model,
        "status": status,
        "request_file": request_path.name,
        "response_file": response_path.name,
    }
    with _LLM_DEBUG_LOCK:
        index_path = request_path.parent / "index.jsonl"
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\n")


class ClaudeClient(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]: ...


class GeminiClient(Protocol):
    def describe_video(
        self,
        *,
        model: str,
        video_path: Path,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]: ...


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        env_key, env_value = stripped.split("=", 1)
        if env_key.strip() == key:
            return env_value.strip().strip('"').strip("'")
    return ""


def _candidate_env_files(env_file: Path | None) -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = repo_root.parent
    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(env_file)
    candidates.extend(
        [
            Path.cwd() / "this.env",
            Path.cwd() / ".env",
            Path(__file__).resolve().parent / "this.env",
            Path(__file__).resolve().parent / ".env",
            repo_root / "this.env",
            repo_root / ".env",
            workspace / "this.env",
            workspace / ".env",
            workspace / "reigh-app" / "this.env",
            workspace / "reigh-app" / ".env",
            workspace / "reigh-worker" / "this.env",
            workspace / "reigh-worker" / ".env",
            workspace / "reigh-worker-orchestrator" / "this.env",
            workspace / "reigh-worker-orchestrator" / ".env",
            Path.home() / "this.env",
            Path.home() / ".env",
            Path.home() / ".codex" / "this.env",
            Path.home() / ".codex" / ".env",
            Path.home() / ".claude" / "this.env",
            Path.home() / ".claude" / ".env",
            Path.home() / ".hermes" / "this.env",
            Path.home() / ".hermes" / ".env",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _load_api_key(env_file: Path | None, key: str) -> str:
    if value := os.environ.get(key, "").strip():
        return value
    for candidate in _candidate_env_files(env_file):
        if value := _read_env_value(candidate, key):
            return value
    raise SystemExit(f"{key} not found")


def _is_transient_error(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    markers = ("timeout", "tempor", "connection", "rate limit", "overloaded", "unavailable", "429", "500", "502", "503", "504")
    return any(marker in message for marker in markers)


def build_claude_client(env_file: Path | None = None) -> ClaudeClient:
    from anthropic import Anthropic

    sdk_client = Anthropic(api_key=_load_api_key(env_file, "ANTHROPIC_API_KEY"))

    class _ClaudeJSONClient:
        def complete_json(
            self,
            *,
            model: str,
            system: str,
            messages: list[dict[str, Any]],
            response_schema: dict[str, Any],
            max_tokens: int,
        ) -> dict[str, Any]:
            materialized = _materialize_message_images(messages)
            debug_context = _start_debug_log(
                "claude",
                {
                    "model": model,
                    "system": system,
                    "messages": materialized,
                    "response_schema": response_schema,
                    "max_tokens": max_tokens,
                },
            )
            for attempt in range(2):
                try:
                    response = sdk_client.messages.create(
                        model=model,
                        system=system,
                        messages=materialized,
                        max_tokens=max_tokens,
                        tools=[{"name": "return_json", "description": "Return the requested JSON payload.", "input_schema": response_schema}],
                        tool_choice={"type": "tool", "name": "return_json"},
                    )
                    for block in response.content:
                        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "return_json":
                            payload = getattr(block, "input", None)
                            if isinstance(payload, dict):
                                _finish_debug_log(
                                    debug_context,
                                    provider="claude",
                                    model=model,
                                    status="ok",
                                    payload={
                                        "attempt": attempt + 1,
                                        "sdk_response": _jsonable(response),
                                        "parsed_payload": payload,
                                    },
                                )
                                return payload
                    raise RuntimeError("Claude response did not include a return_json tool payload")
                except Exception as exc:
                    if attempt == 1 or not _is_transient_error(exc):
                        _finish_debug_log(
                            debug_context,
                            provider="claude",
                            model=model,
                            status="error",
                            payload={
                                "attempt": attempt + 1,
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        )
                    if attempt == 1 or not _is_transient_error(exc):
                        raise
                    time.sleep(1.0)
            raise RuntimeError("Claude request exhausted retries")

    return _ClaudeJSONClient()


def _sanitize_gemini_schema(node: Any) -> Any:
    # Gemini's SDK parses response_schema through a pydantic model that
    # rejects JSON-Schema keywords it doesn't recognise (e.g.
    # `additionalProperties`). Drop those recursively so shared schemas
    # written for Claude still work when passed to Gemini.
    if isinstance(node, dict):
        return {k: _sanitize_gemini_schema(v) for k, v in node.items() if k != "additionalProperties"}
    if isinstance(node, list):
        return [_sanitize_gemini_schema(v) for v in node]
    return node


def build_gemini_client(env_file: Path | None = None) -> GeminiClient:
    from google import genai
    from google.genai import types

    sdk_client = genai.Client(api_key=_load_api_key(env_file, "GEMINI_API_KEY"))

    class _GeminiVideoClient:
        def describe_video(
            self,
            *,
            model: str,
            video_path: Path,
            prompt: str,
            response_schema: dict[str, Any],
        ) -> dict[str, Any]:
            sanitized_schema = _sanitize_gemini_schema(response_schema)
            debug_context = _start_debug_log(
                "gemini",
                {
                    "model": model,
                    "video_path": str(video_path),
                    "prompt": prompt,
                    "response_schema": sanitized_schema,
                },
            )
            for attempt in range(2):
                upload_name: str | None = None
                try:
                    uploaded = sdk_client.files.upload(file=str(video_path))
                    upload_name = getattr(uploaded, "name", None)
                    # Uploads are async — the file stays in PROCESSING for up
                    # to a minute on longer clips and generate_content rejects
                    # any file not yet ACTIVE. Poll until it transitions.
                    deadline = time.monotonic() + 180.0
                    while True:
                        state = str(getattr(uploaded, "state", "")).upper()
                        if state.endswith("ACTIVE"):
                            break
                        if state.endswith("FAILED"):
                            raise RuntimeError(f"Gemini upload entered FAILED state: {upload_name}")
                        if time.monotonic() > deadline:
                            raise RuntimeError(f"Gemini upload {upload_name} did not become ACTIVE within 180s (state={state!r})")
                        time.sleep(2.0)
                        uploaded = sdk_client.files.get(name=upload_name)
                    response = sdk_client.models.generate_content(
                        model=model,
                        contents=[uploaded, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=sanitized_schema,
                        ),
                    )
                    payload = json.loads(response.text)
                    _finish_debug_log(
                        debug_context,
                        provider="gemini",
                        model=model,
                        status="ok",
                        payload={
                            "attempt": attempt + 1,
                            "upload_name": upload_name,
                            "sdk_response": _jsonable(response),
                            "parsed_payload": payload,
                        },
                    )
                    return payload
                except Exception as exc:
                    if attempt == 1 or not _is_transient_error(exc):
                        _finish_debug_log(
                            debug_context,
                            provider="gemini",
                            model=model,
                            status="error",
                            payload={
                                "attempt": attempt + 1,
                                "upload_name": upload_name,
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        )
                    if attempt == 1 or not _is_transient_error(exc):
                        raise
                    time.sleep(1.0)
                finally:
                    if upload_name:
                        try:
                            sdk_client.files.delete(name=upload_name)
                        except Exception:
                            pass
            raise RuntimeError("Gemini request exhausted retries")

    return _GeminiVideoClient()
