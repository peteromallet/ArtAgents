import json
import os
import tempfile
import unittest
from pathlib import Path

import pytest

from artagents.packs.builtin.render import run as render_remotion
from artagents import timeline


@pytest.mark.slow
class TextCardRenderTest(unittest.TestCase):
    def test_text_card_render_smoke(self) -> None:
        if os.environ.get("RUN_RENDER_TESTS") != "1":
            self.skipTest("Set RUN_RENDER_TESTS=1 to render MP4 fixtures")
        with tempfile.TemporaryDirectory(prefix="text-card-render-") as tmp_text:
            tmp = Path(tmp_text)
            timeline_path = tmp / "hype.timeline.json"
            assets_path = tmp / "hype.assets.json"
            out_path = tmp / "hype.mp4"
            config = {
                "theme": "banodoco-default",
                "tracks": [{"id": "v1", "kind": "visual", "label": "Generated"}],
                "clips": [
                    {
                        "id": "clip_g_1",
                        "at": 0,
                        "track": "v1",
                        "clipType": "text-card",
                        "hold": 1,
                        "params": {"content": "Render smoke"},
                    }
                ],
            }
            timeline.save_timeline(config, timeline_path)
            timeline.save_registry({"assets": {}}, assets_path)
            render_remotion.render(timeline_path, assets_path, out_path)
            self.assertGreater(out_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
