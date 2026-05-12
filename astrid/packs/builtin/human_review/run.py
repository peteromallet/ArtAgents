"""Generic human-gate HTTP server — see STAGE.md for the full contract."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


_GEMINI_SCHEMA_KEYS = {
    "type", "properties", "required", "items", "enum", "description",
    "nullable", "format", "minimum", "maximum", "minItems", "maxItems",
    "minLength", "maxLength", "pattern", "anyOf", "oneOf", "allOf",
}


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, path)


def _safe_under(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _validate_against_schema(body: dict, schema_path: Path) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return True, "jsonschema not installed; validation skipped"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if isinstance(schema, dict):
        schema = schema.get("schema", schema)
    try:
        jsonschema.validate(body, schema)
        return True, ""
    except jsonschema.ValidationError as exc:
        return False, str(exc)


def make_handler_class(*, html_path: Path, data_path: Path, state_path: Path | None,
                       out_path: Path, schema_path: Path | None, mounts: dict[str, Path],
                       token: str, shutdown_event: threading.Event):
    """Closure-based request handler with all config baked in."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Silence default access log; keep stderr clean
            return

        # ── helpers ────────────────────────────────────────────────────
        def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain", extra_headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _send_json(self, status: int, payload: dict):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _token_ok(self) -> bool:
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            t = (qs.get("token", [""])[0]) or self.headers.get("X-Session-Token", "")
            return t == token

        def _serve_file(self, path: Path, content_type: str | None = None):
            if not path.is_file():
                self._send(404, b"Not found")
                return
            ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            # Range request support (mp4 seek)
            range_hdr = self.headers.get("Range", "")
            m = re.match(r"bytes=(\d+)-(\d*)", range_hdr)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else len(data) - 1
                end = min(end, len(data) - 1)
                chunk = data[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self._send(200, data, ctype, {"Accept-Ranges": "bytes"})

        # ── GET ───────────────────────────────────────────────────────
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            p = url.path

            # / → html_path (file or dir/index.html)
            if p == "/" or p == "":
                target = html_path if html_path.is_file() else (html_path / "index.html")
                self._serve_file(target, "text/html; charset=utf-8")
                return

            # /data.json
            if p == "/data.json":
                self._serve_file(data_path, "application/json")
                return

            # /state.json (token required)
            if p == "/state.json":
                if not self._token_ok():
                    self._send(403, b"Forbidden")
                    return
                if state_path and state_path.is_file():
                    self._serve_file(state_path, "application/json")
                else:
                    self._send(404, b"No state file")
                return

            # /<prefix>/... static mounts
            for prefix, root in mounts.items():
                if p == prefix or p.startswith(prefix + "/"):
                    relative = p[len(prefix):].lstrip("/")
                    candidate = (root / relative).resolve()
                    if not _safe_under(root, candidate):
                        self._send(403, b"Forbidden (path escape)")
                        return
                    self._serve_file(candidate)
                    return

            # html_path is a directory → maybe serve from there
            if html_path.is_dir():
                candidate = (html_path / p.lstrip("/")).resolve()
                if _safe_under(html_path, candidate) and candidate.is_file():
                    self._serve_file(candidate)
                    return

            self._send(404, b"Not found")

        # ── POST ──────────────────────────────────────────────────────
        def do_POST(self):  # noqa: N802
            if not self._token_ok():
                self._send_json(403, {"error": "forbidden", "detail": "missing or invalid session token"})
                return

            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b""

            if url.path == "/save":
                if state_path is None:
                    self._send_json(400, {"error": "no_state", "detail": "--state not configured"})
                    return
                try:
                    json.loads(raw.decode("utf-8") or "{}")  # validate it's JSON
                except Exception as exc:
                    self._send_json(400, {"error": "bad_json", "detail": str(exc)})
                    return
                _atomic_write(state_path, raw)
                self._send(204)
                return

            if url.path == "/submit":
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except Exception as exc:
                    self._send_json(400, {"error": "bad_json", "detail": str(exc)})
                    return
                if schema_path is not None:
                    ok, err = _validate_against_schema(body, schema_path)
                    if not ok:
                        self._send_json(400, {"error": "schema_violation", "detail": err})
                        return
                _atomic_write(out_path, raw)
                self._send(204)
                shutdown_event.set()
                return

            self._send(404, b"Not found")

    return Handler


def _parse_mounts(values: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for v in values or []:
        if "=" not in v:
            raise SystemExit(f"--serve expects PREFIX=DIR, got: {v}")
        prefix, root = v.split("=", 1)
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        out[prefix.rstrip("/")] = Path(root).resolve()
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--serve", action="append", default=[])
    p.add_argument("--state", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--response-schema", type=Path)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--timeout", type=int, default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.html.exists():
        print(f"Error: --html not found: {args.html}", file=sys.stderr)
        return 2
    if not args.data.is_file():
        print(f"Error: --data not found: {args.data}", file=sys.stderr)
        return 2

    mounts = _parse_mounts(args.serve)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    port = args.port if args.port else _pick_free_port()
    token = secrets.token_hex(16)
    shutdown_event = threading.Event()

    handler = make_handler_class(
        html_path=args.html.resolve(),
        data_path=args.data.resolve(),
        state_path=args.state.resolve() if args.state else None,
        out_path=args.out.resolve(),
        schema_path=args.response_schema.resolve() if args.response_schema else None,
        mounts=mounts,
        token=token,
        shutdown_event=shutdown_event,
    )

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/?token={token}"

    print(f"human_review: serving at {url}", flush=True)
    print(f"human_review: token={token}", flush=True)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    start_t = time.time()
    while not shutdown_event.is_set():
        if args.timeout and (time.time() - start_t) >= args.timeout:
            print(f"human_review: timeout after {args.timeout}s without /submit", file=sys.stderr)
            server.shutdown()
            return 3
        time.sleep(0.25)

    server.shutdown()
    print(f"human_review: submit received, wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
