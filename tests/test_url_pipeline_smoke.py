import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from artagents.packs.builtin.asset_cache import run as asset_cache
from artagents.packs.builtin.cut import run as cut
from artagents import timeline
from artagents.packs.builtin.render.run import _RangeHTTPRequestHandler


class UrlPipelineSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache_root = self.root / "cache"
        self.serve_dir = self.root / "serve"
        self.run_dir = self.root / "run"
        self.out_dir = self.root / "brief"
        self.serve_dir.mkdir()
        self.run_dir.mkdir()
        self.out_dir.mkdir()
        self.fixture = self.serve_dir / "main.mp4"
        self._ensure_fixture(self.fixture)
        self.fixture_sha = hashlib.sha256(self.fixture.read_bytes()).hexdigest()
        self.env = mock.patch.dict(os.environ, {"HYPE_CACHE_DIR": str(self.cache_root)}, clear=False)
        self.env.start()

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
                "color=c=blue:s=160x90:d=6:r=10",
                "-t",
                "6",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg could not generate the video fixture")

    def _write_inputs(self) -> dict[str, Path]:
        scenes = self.run_dir / "scenes.json"
        transcript = self.run_dir / "transcript.json"
        pool = self.run_dir / "pool.json"
        arrangement = self.out_dir / "arrangement.json"
        brief = self.out_dir / "brief.txt"
        scenes.write_text(json.dumps([{"index": 1, "start": 0.0, "end": 6.0, "duration": 6.0}], indent=2) + "\n", encoding="utf-8")
        transcript.write_text(json.dumps({"segments": [{"start": 0.0, "end": 5.0, "text": "hello world"}]}, indent=2) + "\n", encoding="utf-8")
        pool.write_text(
            json.dumps(
                {
                    "version": timeline.POOL_VERSION,
                    "generated_at": "2026-04-25T00:00:00Z",
                    "source_slug": "smoke",
                    "entries": [
                        {
                            "id": "pool_d_0001",
                            "kind": "source",
                    "category": "dialogue",
                            "asset": "main",
                            "src_start": 0.0,
                            "src_end": 5.0,
                            "duration": 5.0,
                            "source_ids": {"segment_ids": [0], "scene_id": "scene_001"},
                            "scores": {"quotability": 1.0},
                            "excluded": False,
                            "text": "hello world",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        arrangement.write_text(
            json.dumps(
                {
                    "version": timeline.ARRANGEMENT_VERSION,
                    "generated_at": "2026-04-25T00:00:00Z",
                    "brief_text": "Make a compact URL pipeline smoke test.",
                    "target_duration_sec": 75.0,
                    "source_slug": "smoke",
                    "brief_slug": "brief",
                    "pool_sha256": "poolsha",
                    "brief_sha256": "briefsha",
                    "clips": [
                        {
                            "uuid": "00000001",
                            "order": 1,
                            "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 5.0]},
                            "visual_source": None,
                            "rationale": "Keep one URL-backed source clip.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        brief.write_text("Make a compact URL pipeline smoke test.\n", encoding="utf-8")
        return {"scenes": scenes, "transcript": transcript, "pool": pool, "arrangement": arrangement, "brief": brief}

    def test_cut_main_writes_url_registry_with_prefetched_sha(self) -> None:
        from artagents.domains.hype import arrangement_rules as ar
        handler = partial(_RangeHTTPRequestHandler, directory=str(self.serve_dir))
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError:
            self.skipTest("local HTTP server bind is not permitted in this sandbox")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        bounds_patch = mock.patch.object(ar, "TOTAL_DURATION_BOUNDS", (1.0, 100.0))
        bounds_patch.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/{self.fixture.name}"
            asset_cache.fetch(url)
            paths = self._write_inputs()
            cut.main(
                [
                    "--scenes",
                    str(paths["scenes"]),
                    "--transcript",
                    str(paths["transcript"]),
                    "--pool",
                    str(paths["pool"]),
                    "--arrangement",
                    str(paths["arrangement"]),
                    "--brief",
                    str(paths["brief"]),
                    "--video",
                    url,
                    "--out",
                    str(self.out_dir),
                ]
            )
        finally:
            bounds_patch.stop()
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        assets_path = self.out_dir / "hype.assets.json"
        self.assertTrue(assets_path.is_file())
        registry = json.loads(assets_path.read_text(encoding="utf-8"))
        main = registry["assets"]["main"]
        self.assertEqual(main["url"], url)
        self.assertEqual(main["content_sha256"], self.fixture_sha)
        self.assertRegex(main["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("file", main)


if __name__ == "__main__":
    unittest.main()
