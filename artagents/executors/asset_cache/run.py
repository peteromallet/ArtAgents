#!/usr/bin/env python3
"""URL-backed asset cache for the hype pipeline.

Assets are cached under ${HYPE_CACHE_DIR:-~/.cache/banodoco-hype}/assets.
Delete that directory manually if you need to clear all cached bytes. Run
`python -m asset_cache --prune-older-than N` to reclaim space from entries
that have not been accessed recently.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

try:
    from filelock import FileLock, Timeout
except ImportError:  # pragma: no cover - exercised only without optional dep.
    FileLock = None  # type: ignore[assignment]

    class Timeout(Exception):
        pass


class ContentDriftError(RuntimeError):
    """Raised when fetched bytes do not match the expected SHA-256."""


class EphemeralSession:
    """Tracks URL downloads minted during this session and deletes them on exit.

    Files that already existed in the cache when fetch() was called are NOT
    registered for deletion — only files this session minted (new download or
    force-refetch). Sessions can be nested; the innermost active session owns
    each new download.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._paths: set[Path] = set()

    def register(self, path: Path) -> None:
        if self.enabled:
            self._paths.add(Path(path))

    def __enter__(self) -> "EphemeralSession":
        if self.enabled:
            _SESSION_STACK.append(self)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self.enabled:
            return
        try:
            _SESSION_STACK.remove(self)
        except ValueError:
            pass
        for path in sorted(self._paths):
            self._cleanup(path)

    def _cleanup(self, path: Path) -> None:
        if path.suffix in {".partial", ".lock"}:
            return
        if _is_locked(path):
            print(f"warning: skipping locked ephemeral cache entry {path}", file=sys.stderr)
            return
        meta_path = _meta_path(path)
        for candidate in (path, meta_path):
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                print(f"warning: failed to delete ephemeral cache entry {candidate}: {exc}", file=sys.stderr)


_SESSION_STACK: list[EphemeralSession] = []


def ephemeral_session(enabled: bool = True) -> EphemeralSession:
    """Context manager that tracks and deletes URL downloads minted in scope."""
    return EphemeralSession(enabled=enabled)


def _current_session() -> EphemeralSession | None:
    return _SESSION_STACK[-1] if _SESSION_STACK else None


def _register_with_session(path: Path, *, preexisted: bool) -> None:
    if preexisted:
        return
    session = _current_session()
    if session is not None:
        session.register(path)


class _FcntlLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: Any | None = None

    def acquire(self, timeout: float | None = None) -> "_FcntlLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        deadline = None if timeout is None or timeout < 0 else time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError as exc:
                if timeout == 0 or (deadline is not None and time.monotonic() >= deadline):
                    raise Timeout(str(self.path)) from exc
                time.sleep(0.05)

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "_FcntlLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def _lock_for(path: Path) -> Any:
    lock_path = Path(str(path) + ".lock")
    if FileLock is not None:
        return FileLock(str(lock_path))
    return _FcntlLock(lock_path)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def is_url(value: str | Path) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _cache_dir() -> Path:
    root = Path(os.environ.get("HYPE_CACHE_DIR", "~/.cache/banodoco-hype")).expanduser()
    path = root / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _basename_for(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name or "asset"
    stem = Path(name).stem or "asset"
    suffix = Path(name).suffix
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "asset"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"{digest}__{safe_stem}{safe_suffix}"


def _path_for(url: str) -> Path:
    return _cache_dir() / _basename_for(url)


def _meta_path(path: Path) -> Path:
    return Path(str(path) + ".meta.json")


def _read_meta(path: Path) -> dict[str, Any]:
    meta_path = _meta_path(path)
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    meta_path = _meta_path(path)
    tmp_path = meta_path.with_name(meta_path.name + ".tmp")
    tmp_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, meta_path)


def _touch_accessed(path: Path) -> None:
    meta = _read_meta(path)
    if not meta:
        return
    meta["accessed_at"] = _now()
    _write_meta(path, meta)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head(url: str) -> dict[str, str]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        return {key.lower(): value for key, value in response.headers.items()}


def _get(url: str, *, start: int = 0) -> tuple[Any, dict[str, str]]:
    headers = {"Range": f"bytes={start}-"} if start > 0 else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    response = urllib.request.urlopen(request, timeout=60)
    return response, {key.lower(): value for key, value in response.headers.items()}


def _drift_mode() -> str:
    mode = os.environ.get("HYPE_DRIFT_MODE", "strict").strip().lower()
    return mode if mode in {"strict", "warn", "refetch"} else "strict"


def _handle_drift(path: Path, expected: str, actual: str, *, allow_refetch: bool) -> bool:
    message = f"Content drift for {path}: expected sha256 {expected}, got {actual}"
    mode = _drift_mode()
    if mode == "warn":
        print(f"warning: {message}", file=sys.stderr)
        return False
    if mode == "refetch" and allow_refetch:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        with contextlib.suppress(FileNotFoundError):
            _meta_path(path).unlink()
        return True
    raise ContentDriftError(message)


def _download_once(url: str, path: Path, expected_sha256: str | None, head_meta: dict[str, str]) -> Path:
    partial_path = Path(str(path) + ".partial")
    existing = partial_path.stat().st_size if partial_path.exists() else 0
    response, get_meta = _get(url, start=existing)
    status = getattr(response, "status", None)
    mode = "ab" if existing > 0 and status == 206 else "wb"
    try:
        with response, partial_path.open(mode) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    finally:
        response.close()

    actual_sha256 = _sha256_path(partial_path)
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise ContentDriftError(f"Content drift for {url}: expected sha256 {expected_sha256}, got {actual_sha256}")

    fetched_at = _now()
    os.replace(partial_path, path)
    content_length = get_meta.get("content-length") or head_meta.get("content-length")
    meta: dict[str, Any] = {
        "url": url,
        "etag": get_meta.get("etag") or head_meta.get("etag"),
        "content_length": int(content_length) if content_length and content_length.isdigit() else path.stat().st_size,
        "content_sha256": actual_sha256,
        "fetched_at": fetched_at,
        "accessed_at": fetched_at,
    }
    old_meta = _read_meta(path)
    if isinstance(old_meta.get("url_expires_at"), str):
        meta["url_expires_at"] = old_meta["url_expires_at"]
    _write_meta(path, meta)
    return path


def fetch(url: str, *, expected_sha256: str | None = None, force: bool = False) -> Path:
    if not is_url(url):
        raise ValueError(f"fetch requires an http(s) URL, got {url!r}")
    path = _path_for(url)
    lock = _lock_for(path)
    preexisted = path.exists() and not force
    with lock:
        if path.exists() and not force:
            actual_sha256 = _sha256_path(path) if expected_sha256 else None
            if expected_sha256 and actual_sha256 != expected_sha256:
                refetch = _handle_drift(path, expected_sha256, actual_sha256 or "", allow_refetch=True)
                if not refetch:
                    _touch_accessed(path)
                    return path
                force = True
                preexisted = False
            else:
                _touch_accessed(path)
                return path

        head_meta: dict[str, str] = {}
        with contextlib.suppress(urllib.error.URLError, TimeoutError, OSError):
            head_meta = _head(url)

        last_error: BaseException | None = None
        for delay in (2, 4, 8):
            try:
                try:
                    verify_sha256 = expected_sha256 if _drift_mode() == "strict" else None
                    downloaded = _download_once(url, path, verify_sha256, head_meta)
                    if expected_sha256:
                        actual_sha256 = _sha256_path(downloaded)
                        if actual_sha256 != expected_sha256:
                            _handle_drift(downloaded, expected_sha256, actual_sha256, allow_refetch=False)
                    _register_with_session(downloaded, preexisted=preexisted)
                    return downloaded
                except ContentDriftError:
                    if expected_sha256:
                        partial_path = Path(str(path) + ".partial")
                        actual_sha256 = _sha256_path(partial_path) if partial_path.exists() else ""
                        if _handle_drift(path, expected_sha256, actual_sha256, allow_refetch=False):
                            continue
                    raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(delay)
        try:
            verify_sha256 = expected_sha256 if _drift_mode() == "strict" else None
            downloaded = _download_once(url, path, verify_sha256, head_meta)
            if expected_sha256:
                actual_sha256 = _sha256_path(downloaded)
                if actual_sha256 != expected_sha256:
                    _handle_drift(downloaded, expected_sha256, actual_sha256, allow_refetch=False)
            _register_with_session(downloaded, preexisted=preexisted)
            return downloaded
        except BaseException as exc:
            if last_error is not None and isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
                raise exc from last_error
            raise


def _parse_ffprobe_fps(value: Any, *, path: str | Path) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"ffprobe did not return fps for {path}")
    if "/" in value:
        numerator_text, denominator_text = value.split("/", 1)
        numerator = float(numerator_text)
        denominator = float(denominator_text)
        if denominator == 0:
            raise SystemExit(f"ffprobe returned invalid fps {value!r} for {path}")
        return numerator / denominator
    return float(value)


def metadata(url_or_path: str | Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration:stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(url_or_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid ffprobe JSON for {url_or_path}: {exc.msg}") from exc
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise SystemExit(f"ffprobe did not return a video stream for {url_or_path}")
    stream = streams[0]
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        raise SystemExit(f"ffprobe did not return format metadata for {url_or_path}")
    try:
        duration = float(format_info["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"ffprobe returned incomplete metadata for {url_or_path}") from exc
    codec = stream.get("codec_name")
    if not isinstance(codec, str) or not codec:
        raise SystemExit(f"ffprobe did not return a codec for {url_or_path}")
    fps_source = stream.get("avg_frame_rate")
    if fps_source in (None, "", "0/0"):
        fps_source = stream.get("r_frame_rate")
    return {
        "duration": duration,
        "resolution": f"{width}x{height}",
        "fps": _parse_ffprobe_fps(fps_source, path=url_or_path),
        "codec": codec,
    }


def resolve(entry: dict[str, Any], *, want: Literal["path", "url"]) -> Path | str:
    if want not in {"path", "url"}:
        raise ValueError("want must be 'path' or 'url'")
    if want == "url":
        if isinstance(entry.get("url"), str):
            return entry["url"]
        if isinstance(entry.get("file"), str):
            return Path(entry["file"]).resolve()
        raise ValueError("Asset entry must include 'file' or 'url'")
    if isinstance(entry.get("url"), str) and isinstance(entry.get("content_sha256"), str):
        path = fetch(entry["url"], expected_sha256=entry.get("content_sha256"))
        _touch_accessed(path)
        return path
    if isinstance(entry.get("file"), str) and not is_url(entry["file"]):
        return Path(entry["file"]).resolve()
    if isinstance(entry.get("url"), str):
        path = fetch(entry["url"], expected_sha256=entry.get("content_sha256"))
        _touch_accessed(path)
        return path
    raise ValueError("Asset entry must include 'file' or 'url'")


def resolve_input(value: str | Path, *, want: Literal["path", "url"] = "path") -> Path | str:
    if want not in {"path", "url"}:
        raise ValueError("want must be 'path' or 'url'")
    if is_url(value):
        if want == "url":
            return str(value)
        return fetch(str(value))
    path = Path(value).expanduser().resolve()
    if want == "path":
        _touch_accessed(path)
        return path
    return path


def _is_locked(path: Path) -> bool:
    lock = _lock_for(path)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True
    else:
        lock.release()
        return False


def prune(older_than_days: int = 30) -> list[Path]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)
    removed: list[Path] = []
    for meta_path in _cache_dir().glob("*.meta.json"):
        asset_path = Path(str(meta_path)[: -len(".meta.json")])
        if asset_path.suffix in {".partial", ".lock"}:
            continue
        if not asset_path.exists():
            continue
        if _is_locked(asset_path):
            print(f"warning: skipping locked cache entry {asset_path}", file=sys.stderr)
            continue
        meta = _read_meta(asset_path)
        accessed_at = meta.get("accessed_at") or meta.get("fetched_at")
        if not isinstance(accessed_at, str):
            continue
        try:
            accessed = dt.datetime.fromisoformat(accessed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if accessed >= cutoff:
            continue
        for candidate in (asset_path, meta_path):
            if candidate.suffix in {".partial", ".lock"}:
                continue
            with contextlib.suppress(FileNotFoundError):
                candidate.unlink()
                removed.append(candidate)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the hype asset cache.")
    parser.add_argument("--prune-older-than", type=int, metavar="DAYS")
    args = parser.parse_args()
    if args.prune_older_than is None:
        parser.error("--prune-older-than is required")
    before: dict[Path, int] = {}
    for meta_path in _cache_dir().glob("*.meta.json"):
        asset_path = Path(str(meta_path)[: -len(".meta.json")])
        if asset_path.exists():
            before[asset_path] = asset_path.stat().st_size
    removed = prune(older_than_days=args.prune_older_than)
    freed = sum(before.get(path, 0) for path in removed)
    print(f"removed={len(removed)} freed_bytes={freed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
