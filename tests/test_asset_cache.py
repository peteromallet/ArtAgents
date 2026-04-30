import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import asset_cache
from render_remotion import _RangeHTTPRequestHandler


class CountingRangeHandler(_RangeHTTPRequestHandler):
    get_count = 0
    ranges: list[str | None] = []
    lock = threading.Lock()
    delay = 0.0

    def do_GET(self) -> None:
        with self.lock:
            type(self).get_count += 1
            type(self).ranges.append(self.headers.get("Range"))
        if type(self).delay:
            time.sleep(type(self).delay)
        super().do_GET()


class AssetCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache_root = self.root / "cache"
        self.serve_dir = self.root / "serve"
        self.serve_dir.mkdir()
        self.fixture = self.serve_dir / "main.mp4"
        self._ensure_fixture(self.fixture)
        self.fixture_bytes = self.fixture.read_bytes()
        self.fixture_sha = hashlib.sha256(self.fixture_bytes).hexdigest()
        self.env = mock.patch.dict(os.environ, {"HYPE_CACHE_DIR": str(self.cache_root)}, clear=False)
        self.env.start()
        os.environ.pop("HYPE_DRIFT_MODE", None)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _ensure_fixture(self, path: Path) -> None:
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required to generate the video fixture")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=160x90:d=2:r=10",
                "-t",
                "2",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg could not generate the video fixture")

    @contextlib.contextmanager
    def _server(self, *, delay: float = 0.0):
        CountingRangeHandler.get_count = 0
        CountingRangeHandler.ranges = []
        CountingRangeHandler.delay = delay
        handler = partial(CountingRangeHandler, directory=str(self.serve_dir))
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError:
            self.skipTest("local HTTP server bind is not permitted in this sandbox")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/{self.fixture.name}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            CountingRangeHandler.delay = 0.0

    def test_fetch_happy_path(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
        self.assertEqual(path.read_bytes(), self.fixture_bytes)
        meta = asset_cache._read_meta(path)
        self.assertEqual(meta["url"], url)
        self.assertEqual(meta["content_sha256"], self.fixture_sha)

    def test_fetch_resume_from_partial(self) -> None:
        with self._server() as url:
            partial_path = Path(str(asset_cache._path_for(url)) + ".partial")
            partial_path.write_bytes(self.fixture_bytes[: len(self.fixture_bytes) // 2])
            path = asset_cache.fetch(url)
        self.assertEqual(path.read_bytes(), self.fixture_bytes)
        self.assertIn(f"bytes={len(self.fixture_bytes) // 2}-", CountingRangeHandler.ranges)

    def test_fetch_drift_strict(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
            original = path.read_bytes()
            with self.assertRaises(asset_cache.ContentDriftError):
                asset_cache.fetch(url, expected_sha256="0" * 64)
            self.assertEqual(path.read_bytes(), original)

    def test_fetch_drift_warn(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
            with mock.patch.dict(os.environ, {"HYPE_DRIFT_MODE": "warn"}, clear=False):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    returned = asset_cache.fetch(url, expected_sha256="0" * 64)
        self.assertEqual(returned, path)
        self.assertIn("warning: Content drift", stderr.getvalue())

    def test_fetch_drift_refetch(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
            path.write_bytes(b"stale")
            asset_cache._write_meta(path, {"url": url, "content_sha256": "bad", "fetched_at": "2026-04-25T00:00:00Z", "accessed_at": "2026-04-25T00:00:00Z"})
            with mock.patch.dict(os.environ, {"HYPE_DRIFT_MODE": "refetch"}, clear=False):
                returned = asset_cache.fetch(url, expected_sha256=self.fixture_sha)
        self.assertEqual(returned.read_bytes(), self.fixture_bytes)

    def test_fetch_force_redownloads(self) -> None:
        with self._server() as url:
            asset_cache.fetch(url)
            asset_cache.fetch(url, force=True)
        self.assertEqual(CountingRangeHandler.get_count, 2)

    def test_metadata_dispatches(self) -> None:
        with self._server() as url:
            for target in (self.fixture, url):
                meta = asset_cache.metadata(target)
                self.assertEqual(set(meta), {"duration", "resolution", "fps", "codec"})
                self.assertEqual(meta["resolution"], "160x90")

    def test_resolve_path_url_combos(self) -> None:
        with self._server() as url:
            file_entry = {"file": str(self.fixture)}
            url_entry = {"url": url}
            file_url_entry = {"file": str(self.fixture), "url": url}
            sha_entry = {"file": str(self.fixture), "url": url, "content_sha256": self.fixture_sha}
            self.assertEqual(asset_cache.resolve(file_entry, want="path"), self.fixture.resolve())
            self.assertEqual(asset_cache.resolve(file_entry, want="url"), self.fixture.resolve())
            self.assertEqual(asset_cache.resolve(url_entry, want="url"), url)
            self.assertEqual(asset_cache.resolve(url_entry, want="path").read_bytes(), self.fixture_bytes)
            self.assertEqual(asset_cache.resolve(file_url_entry, want="url"), url)
            self.assertEqual(asset_cache.resolve(file_url_entry, want="path"), self.fixture.resolve())
            self.assertEqual(asset_cache.resolve(sha_entry, want="url"), url)
            self.assertEqual(asset_cache.resolve(sha_entry, want="path").read_bytes(), self.fixture_bytes)

    def test_filelock_prevents_concurrent_fetches_of_same_url(self) -> None:
        with self._server(delay=0.2) as url:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: asset_cache.fetch(url), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0].read_bytes(), self.fixture_bytes)
        self.assertEqual(CountingRangeHandler.get_count, 1)

    def test_prune_removes_old_entries(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
        old = "2026-01-01T00:00:00Z"
        meta = asset_cache._read_meta(path)
        meta["accessed_at"] = old
        asset_cache._write_meta(path, meta)
        removed = asset_cache.prune(older_than_days=30)
        self.assertIn(path, removed)
        self.assertIn(asset_cache._meta_path(path), removed)
        self.assertFalse(path.exists())
        self.assertFalse(asset_cache._meta_path(path).exists())

    def test_prune_respects_locks(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
        meta = asset_cache._read_meta(path)
        meta["accessed_at"] = "2026-01-01T00:00:00Z"
        asset_cache._write_meta(path, meta)
        lock = asset_cache._lock_for(path)
        lock.acquire()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                removed = asset_cache.prune(older_than_days=30)
        finally:
            lock.release()
        self.assertEqual(removed, [])
        self.assertTrue(path.exists())
        self.assertIn("skipping locked cache entry", stderr.getvalue())

    def test_ephemeral_session_deletes_new_downloads(self) -> None:
        with self._server() as url:
            with asset_cache.ephemeral_session():
                path = asset_cache.fetch(url)
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())
            self.assertFalse(asset_cache._meta_path(path).exists())

    def test_ephemeral_session_preserves_preexisting(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
            self.assertTrue(path.exists())
            with asset_cache.ephemeral_session():
                same = asset_cache.fetch(url)
                self.assertEqual(path, same)
            self.assertTrue(path.exists())

    def test_ephemeral_session_respects_locks(self) -> None:
        with self._server() as url:
            session = asset_cache.ephemeral_session()
            session.__enter__()
            try:
                path = asset_cache.fetch(url)
            except BaseException:
                session.__exit__(None, None, None)
                raise
            lock = asset_cache._lock_for(path)
            lock.acquire()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    session.__exit__(None, None, None)
            finally:
                lock.release()
            self.assertTrue(path.exists())
            self.assertIn("skipping locked ephemeral cache entry", stderr.getvalue())

    def test_ephemeral_session_handles_force_refetch(self) -> None:
        with self._server() as url:
            path = asset_cache.fetch(url)
            self.assertTrue(path.exists())
            with asset_cache.ephemeral_session():
                refetched = asset_cache.fetch(url, force=True)
                self.assertEqual(path, refetched)
            self.assertFalse(path.exists())

    def test_ephemeral_session_nested(self) -> None:
        with self._server() as url:
            with asset_cache.ephemeral_session() as outer:
                with asset_cache.ephemeral_session() as inner:
                    path = asset_cache.fetch(url)
                    self.assertIn(path, inner._paths)
                    self.assertNotIn(path, outer._paths)
                self.assertFalse(path.exists())

    def test_ephemeral_session_cleanup_on_exception(self) -> None:
        captured: dict[str, Path] = {}
        with self._server() as url:
            with self.assertRaises(RuntimeError):
                with asset_cache.ephemeral_session():
                    captured["p"] = asset_cache.fetch(url)
                    self.assertTrue(captured["p"].exists())
                    raise RuntimeError("boom")
            self.assertFalse(captured["p"].exists())


if __name__ == "__main__":
    unittest.main()
