import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from artagents.packs.builtin.render import run as render_remotion
from artagents import timeline


ROOT = Path(__file__).resolve().parents[1]
HAS_AUDIO_RENDER_DEPS = (
    shutil.which("ffmpeg") is not None
    and shutil.which("ffprobe") is not None
    and (ROOT / "remotion" / "node_modules").exists()
)


def remotion_launch_blocked(error: RuntimeError) -> bool:
    message = str(error)
    return (
        "Failed to launch the browser process" in message
        or "MachPortRendezvous" in message
        or "Permission denied (1100)" in message
    )


@unittest.skipUnless(HAS_AUDIO_RENDER_DEPS, "ffmpeg/ffprobe and remotion/node_modules are required")
class AudioRenderTest(unittest.TestCase):
    def test_rendered_mp4_contains_audio_stream(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="audio-render-"))
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        tone_path = tmp_dir / "tone.m4a"
        silent_path = tmp_dir / "silent.mp4"
        timeline_path = tmp_dir / "hype.timeline.json"
        assets_path = tmp_dir / "hype.assets.json"
        out_path = tmp_dir / "hype.mp4"

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:a",
                "aac",
                str(tone_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=640x360:d=2:r=30",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(silent_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        config: timeline.TimelineConfig = {
            "theme": "banodoco-default",
            "theme_overrides": {
                "visual": {"canvas": {"width": 640, "height": 360, "fps": 30}}
            },
            "tracks": [
                {"id": "v1", "kind": "visual", "label": "Video"},
                {"id": "a1", "kind": "audio", "label": "Audio"},
            ],
            "clips": [
                {
                    "id": "visual_001",
                    "at": 0.0,
                    "track": "v1",
                    "clipType": "media",
                    "asset": "visual",
                    "from_": 0.0,
                    "to": 2.0,
                },
                {
                    "id": "audio_001",
                    "at": 0.0,
                    "track": "a1",
                    "clipType": "media",
                    "asset": "tone",
                    "from_": 0.0,
                    "to": 2.0,
                },
            ],
        }
        registry: timeline.AssetRegistry = {
            "assets": {
                "visual": {
                    "file": str(silent_path),
                    "type": "video/mp4",
                    "duration": 2.0,
                    "resolution": "640x360",
                    "fps": 30.0,
                },
                "tone": {
                    "file": str(tone_path),
                    "type": "audio/mp4",
                    "duration": 2.0,
                },
            }
        }
        timeline.save_timeline(config, timeline_path)
        timeline.save_registry(registry, assets_path)

        try:
            output = render_remotion.render(
                timeline_path,
                assets_path,
                out_path,
                project_dir=ROOT / "remotion",
            )
        except RuntimeError as exc:
            if remotion_launch_blocked(exc):
                self.skipTest(f"Remotion browser launch is blocked in this environment: {exc}")
            raise

        self.assertTrue(output.exists())
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("audio", probe.stdout)


if __name__ == "__main__":
    unittest.main()
