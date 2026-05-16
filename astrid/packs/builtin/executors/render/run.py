#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..asset_cache import run as asset_cache
from ..... import timeline
from .....audit import AuditContext
from .....theme_schema import ThemeValidationError, load_theme
from ....._paths import REPO_ROOT, WORKSPACE_ROOT


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _RangeHTTPRequestHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with HTTP Range support.

    Remotion's media components seek into long source videos via Range
    requests. Without this, a 2-hour source video gets fully downloaded
    on every seek, which either times out or renders as black/silence.
    """

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Quiet the access log; one line per clip byte fetch is noise.
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        try:
            fs = os.fstat(f.fileno())
        except OSError:
            f.close()
            self.send_error(500, "File stat failed")
            return None
        size = fs.st_size
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                start_s, end_s = range_header[6:].split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                if start < 0 or end >= size or start > end:
                    raise ValueError
            except ValueError:
                f.close()
                self.send_error(416, "Invalid Range")
                return None
            length = end - start + 1
            f.seek(start)
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            self._range_limit = length
            return f
        self._range_limit = None
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile) -> None:
        limit = getattr(self, "_range_limit", None)
        if limit is None:
            try:
                super().copyfile(source, outputfile)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        remaining = limit
        chunk = 64 * 1024
        try:
            while remaining > 0:
                buf = source.read(min(chunk, remaining))
                if not buf:
                    break
                outputfile.write(buf)
                remaining -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _accepts_ranges(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.headers.get("Accept-Ranges", "").lower() == "bytes"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _parse_url_expiry(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _classify_assets(assets_path: Path) -> dict[str, dict[str, object]]:
    if not assets_path.exists():
        raise FileNotFoundError("hype.assets.json missing — did you run cut.py first?")
    registry = timeline.load_registry(assets_path)
    classified: dict[str, dict[str, object]] = {}
    now = datetime.now(timezone.utc)
    for key, entry in registry["assets"].items():
        url = entry.get("url")
        expires_at = entry.get("url_expires_at")
        if isinstance(expires_at, str) and _parse_url_expiry(expires_at) <= now:
            raise RuntimeError(f"Asset {key} URL expired at {expires_at}; refresh upstream before rendering")
        if isinstance(url, str):
            if _accepts_ranges(url):
                classified[key] = {"mode": "url-direct", "url": url, "local_path": None}
            else:
                classified[key] = {
                    "mode": "url-fetched",
                    "url": url,
                    "local_path": Path(asset_cache.fetch(url, expected_sha256=entry.get("content_sha256"))),
                }
            continue
        file_value = entry.get("file")
        if not isinstance(file_value, str) or not file_value:
            raise FileNotFoundError(f"Asset '{key}' has no file path or URL")
        local_path = Path(file_value)
        if not local_path.is_absolute():
            local_path = (assets_path.parent / local_path).resolve()
        classified[key] = {"mode": "local", "url": None, "local_path": local_path}
    return classified


def _server_root_for(assets_path: Path, classified: dict[str, dict[str, object]]) -> Path:
    """Pick a serve root that contains every asset file.

    Uses the common parent of all absolute asset paths. Callers must ensure
    every asset resolves under this root before URL rewriting.
    """
    resolved_paths: list[Path] = []
    for entry in classified.values():
        if entry.get("mode") == "url-direct":
            continue
        local_path = entry.get("local_path")
        if isinstance(local_path, Path):
            resolved_paths.append(local_path.resolve())
    if not resolved_paths:
        return assets_path.parent
    common = Path(os.path.commonpath([str(p) for p in resolved_paths]))
    return common if common.is_dir() else common.parent


def _swap_from_dump(clip: dict) -> dict:
    out = dict(clip)
    if "from_" in out:
        out["from"] = out.pop("from_")
    return out


def _resolve_assets(
    assets_path: Path,
    server_root: Path,
    server_port: int,
    classified: dict[str, dict[str, object]],
) -> dict:
    # Remotion's bundler would copy the entire --public-dir into the webpack
    # bundle, which explodes disk usage for large source videos. We serve
    # assets over HTTP from their original location instead — Remotion's
    # <Video src> accepts http:// URLs natively and streams without copying.
    if not assets_path.exists():
        raise FileNotFoundError("hype.assets.json missing — did you run cut.py first?")
    registry = timeline.load_registry(assets_path)
    for asset_key, entry in registry["assets"].items():
        asset_info = classified[asset_key]
        if asset_info.get("mode") == "url-direct":
            entry["file"] = entry["url"]
            continue
        local_path = asset_info.get("local_path")
        if not isinstance(local_path, Path):
            raise FileNotFoundError(f"Asset '{asset_key}' has no local path")
        resolved = local_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Asset '{asset_key}' resolved to missing file: {resolved}")
        try:
            rel = resolved.relative_to(server_root)
        except ValueError as err:
            raise RuntimeError(
                f"Asset '{asset_key}' at {resolved} is not inside server root {server_root}; "
                "all assets must share a common parent directory"
            ) from err
        entry["file"] = f"http://localhost:{server_port}/{rel.as_posix()}"
    return registry


def _validate_project_dir(project_dir: Path) -> None:
    if not project_dir.exists():
        raise FileNotFoundError(f"Remotion project directory not found: {project_dir}")
    package_json = project_dir / "package.json"
    if not package_json.exists():
        raise FileNotFoundError(f"Remotion project is missing package.json: {package_json}")
    node_modules = project_dir / "node_modules"
    if not node_modules.exists():
        raise FileNotFoundError("Run `npm install` in tools/remotion/ first")


def _serialize_timeline(timeline_path: Path, *, default_theme: str = "banodoco-default") -> dict:
    return timeline.Timeline.load(timeline_path).for_render(default_theme=default_theme).to_json_data()


def _resolve_theme_path(theme_path: Path) -> Path:
    if theme_path.name == "theme.json":
        return theme_path
    if theme_path.exists() and theme_path.is_dir():
        return theme_path / "theme.json"
    if theme_path.exists():
        return theme_path
    return WORKSPACE_ROOT / "themes" / str(theme_path) / "theme.json"


def _theme_for_props(theme_path: Path) -> dict:
    resolved = _resolve_theme_path(theme_path)
    if not resolved.exists():
        return {
            "id": "banodoco-default",
            "visual": {
                "color": {
                    "fg": "#ffffff",
                    "bg": "#000000",
                    "accent": "#ffffff",
                },
                "type": {
                    "families": {"heading": "Georgia, serif", "body": "Georgia, serif"},
                    "size": {"base": 64, "small": 36, "large": 96},
                    "weight": {"normal": 400, "bold": 700},
                    "lineHeight": 1.1,
                },
                "motion": {"fadeMs": 250},
                "canvas": {
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                },
            },
        }
    theme = load_theme(resolved)
    return {"id": theme["id"], "visual": theme["visual"]}


def _theme_slug_for_render_default(theme_path: Path) -> str:
    resolved = _resolve_theme_path(theme_path)
    if resolved.name == "theme.json":
        return resolved.parent.name
    return resolved.stem or "banodoco-default"


def _resolved_theme_for_render(timeline_path: Path, fallback_theme_path: Path) -> dict:
    """Resolve the timeline's theme + theme_overrides into the props-shaped dict.

    The timeline references a theme by slug; per-run overrides live in
    timeline.theme_overrides. We merge them and trim to {id, visual} for Remotion
    props.
    """
    loaded = timeline.Timeline.load(timeline_path)
    render_view = loaded.for_render(default_theme=_theme_slug_for_render_default(fallback_theme_path))
    timeline_config = loaded.to_config()
    timeline_config.setdefault("theme", render_view.theme)
    themes_root = WORKSPACE_ROOT / "themes"
    try:
        merged = timeline.resolve_timeline_theme(timeline_config, themes_root)
    except (FileNotFoundError, ValueError):
        merged = None
    if not isinstance(merged, dict) or "visual" not in merged:
        # Caller-supplied --theme path is the fallback when the timeline can't be
        # resolved (e.g. running against a stripped fixture).
        return _theme_for_props(fallback_theme_path)
    return {"id": merged.get("id") or merged.get("visual", {}).get("id") or "theme", "visual": merged["visual"]}


def _regenerate_element_registries(project_dir: Path, theme_path: Path | None) -> None:
    generator = REPO_ROOT / "scripts" / "gen_effect_registry.py"
    cmd = [sys.executable, str(generator)]
    if theme_path is not None:
        cmd.extend(["--theme", str(_resolve_theme_path(theme_path))])
    env = os.environ.copy()
    composition_src = project_dir / "node_modules" / "@banodoco" / "timeline-composition" / "typescript" / "src"
    if composition_src.is_dir():
        env.setdefault("ARTAGENTS_TIMELINE_COMPOSITION_SRC", str(composition_src))
    subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        check=True,
        text=True,
    )


def _stderr_tail(stderr: str) -> str:
    lines = stderr.splitlines()
    tail = lines[-40:] if len(lines) > 40 else lines
    return "\n".join(tail).strip()


def _require_free_space(path: Path, min_free_gb: float | None) -> None:
    if min_free_gb is None or min_free_gb <= 0:
        return
    target = path if path.exists() else path.parent
    usage = shutil.disk_usage(target)
    min_free = int(min_free_gb * 1024 * 1024 * 1024)
    if usage.free < min_free:
        free_gb = usage.free / (1024 * 1024 * 1024)
        raise RuntimeError(
            f"Remotion render needs at least {min_free_gb:.1f} GiB free at {target}; "
            f"only {free_gb:.1f} GiB is available"
        )


def render(
    timeline_path: Path,
    assets_path: Path,
    out_path: Path,
    *,
    project_dir: Path | None = None,
    composition_id: str = "TimelineComposition",
    theme_path: Path | None = None,
    min_free_gb: float | None = None,
) -> Path:
    project_dir = project_dir or (REPO_ROOT / "remotion")
    _validate_project_dir(project_dir)
    _regenerate_element_registries(project_dir, theme_path)
    out_path = out_path.resolve()
    _require_free_space(out_path.parent, min_free_gb)
    props_path = (out_path.parent / ".remotion-props.json").resolve()
    classified = _classify_assets(assets_path)
    server_root = _server_root_for(assets_path, classified).resolve()
    try:
        port = _pick_free_port()
        handler = partial(_RangeHTTPRequestHandler, directory=str(server_root))
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise RuntimeError(f"Permission denied (1100): local HTTP asset server blocked: {exc}") from exc
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        resolved_registry = _resolve_assets(assets_path, server_root, port, classified)
        resolved_theme = theme_path or (WORKSPACE_ROOT / "themes" / "banodoco-default" / "theme.json")
        theme_for_props = _resolved_theme_for_render(timeline_path, resolved_theme)
        # The timeline references a theme by slug + optional theme_overrides;
        # theme.visual.canvas is the source of truth for Remotion calculateMetadata.
        merged_props = {
            "timeline": _serialize_timeline(
                timeline_path,
                default_theme=str(theme_for_props.get("id") or "banodoco-default"),
            ),
            "assets": resolved_registry,
            "theme": theme_for_props,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        props_path.write_text(json.dumps(merged_props), encoding="utf-8")
        result = subprocess.run(
            [
                "npx",
                "remotion",
                "render",
                composition_id,
                "--props",
                str(props_path),
                "--output",
                str(out_path),
                "--allow-html-in-canvas",
            ],
            cwd=str(project_dir),
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            stderr_tail = _stderr_tail(result.stderr)
            message = f"Remotion render failed with exit code {result.returncode}"
            if stderr_tail:
                message = f"{message}\n{stderr_tail}"
            raise RuntimeError(message)
        props_path.unlink(missing_ok=True)
    finally:
        server.shutdown()
        server.server_close()
    audit = AuditContext.from_env()
    if audit is not None:
        timeline_id = audit.register_asset(kind="timeline", path=timeline_path, label="Render timeline", stage="render_remotion")
        assets_id = audit.register_asset(kind="assets_registry", path=assets_path, label="Render asset registry", stage="render_remotion")
        render_id = audit.register_asset(
            kind="render",
            path=out_path,
            label="Rendered video",
            parents=[timeline_id, assets_id],
            stage="render_remotion",
            metadata={"composition": composition_id},
        )
        audit.register_node(
            stage="render_remotion",
            label="Render Remotion timeline",
            parents=[timeline_id, assets_id],
            outputs=[render_id],
            metadata={"composition": composition_id, "project_dir": str(project_dir)},
        )
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, default=REPO_ROOT / "remotion")
    parser.add_argument("--composition", default="TimelineComposition")
    parser.add_argument("--min-free-gb", type=float, default=None, help="Abort before rendering unless this much free disk is available near --out.")
    parser.add_argument(
        "--theme",
        type=Path,
        default=WORKSPACE_ROOT / "themes" / "banodoco-default" / "theme.json",
    )
    args = parser.parse_args()
    try:
        output = render(
            args.timeline,
            args.assets,
            args.out,
            project_dir=args.project_dir,
            composition_id=args.composition,
            theme_path=args.theme,
            min_free_gb=args.min_free_gb,
        )
    except Exception as exc:  # pragma: no cover - CLI path
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
