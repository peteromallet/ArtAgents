import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import render_remotion
import timeline


ROOT = Path(__file__).resolve().parents[1]
THEME_2RP = ROOT.parent / "themes" / "2rp" / "theme.json"


class RenderRemotionRegistryGenerationTest(unittest.TestCase):
    def _write_empty_render_inputs(self, tmp: Path) -> tuple[Path, Path, Path]:
        timeline_path = tmp / "hype.timeline.json"
        assets_path = tmp / "hype.assets.json"
        out_path = tmp / "hype.mp4"
        timeline.save_timeline(
            {
                "theme": "banodoco-default",
                "tracks": [{"id": "v1", "kind": "visual", "label": "Generated"}],
                "clips": [],
            },
            timeline_path,
        )
        timeline.save_registry({"assets": {}}, assets_path)
        return timeline_path, assets_path, out_path

    def _run_with_mocked_subprocess(self, theme_path: Path | None) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append([str(part) for part in cmd])
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        class FakeServer:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def serve_forever(self) -> None:
                pass

            def shutdown(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        with tempfile.TemporaryDirectory(prefix="render-registry-") as tmp_text:
            tmp = Path(tmp_text)
            timeline_path, assets_path, out_path = self._write_empty_render_inputs(tmp)
            with (
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch.object(render_remotion, "_pick_free_port", return_value=49152),
                mock.patch.object(render_remotion, "ThreadingHTTPServer", FakeServer),
            ):
                render_remotion.render(
                    timeline_path,
                    assets_path,
                    out_path,
                    project_dir=ROOT / "remotion",
                    theme_path=theme_path,
                )
        return calls

    def test_render_regenerates_theme_registries_before_remotion_command(self) -> None:
        calls = self._run_with_mocked_subprocess(THEME_2RP)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(Path(calls[0][1]).name, "gen_effect_registry.py")
        self.assertEqual(calls[0][2:], ["--theme", str(THEME_2RP)])
        self.assertEqual(calls[1][:3], ["npx", "remotion", "render"])

    def test_render_without_theme_clears_active_theme_registries(self) -> None:
        calls = self._run_with_mocked_subprocess(None)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(Path(calls[0][1]).name, "gen_effect_registry.py")
        self.assertNotIn("--theme", calls[0])
        self.assertEqual(calls[1][:3], ["npx", "remotion", "render"])


if __name__ == "__main__":
    unittest.main()
