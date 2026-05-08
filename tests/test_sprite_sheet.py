from __future__ import annotations

import json

from astrid.packs.builtin.sprite_sheet.run import choose_layout, main, validate_sheet_dimensions, write_layout_guide


def test_layout_guide_writes_png_and_manifest_shape(tmp_path):
    guide = tmp_path / "layout.png"
    layout = write_layout_guide(guide, cols=2, rows=2, frame_width=128, frame_height=128)

    assert guide.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert layout["sheet_width"] == 256
    assert layout["sheet_height"] == 256
    assert len(layout["frames"]) == 4
    assert layout["frames"][3] == {"index": 4, "x": 128, "y": 128, "width": 128, "height": 128}
    validate_sheet_dimensions(guide, expected_width=256, expected_height=256)


def test_sprite_sheet_dry_run(capsys, tmp_path):
    code = main(
        [
            "--animation",
            "four-frame blink cycle",
            "--subject",
            "simple black dot",
            "--cols",
            "2",
            "--rows",
            "2",
            "--frame-width",
            "512",
            "--frame-height",
            "512",
            "--out-dir",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["size"] == "1024x1024"
    assert payload["layout_guide"] == str(tmp_path / "layout_guide.png")
    assert payload["sprite_sheet"] == str(tmp_path / "sprite_sheet.png")
    assert payload["alpha_sprite_sheet"] == str(tmp_path / "sprite_sheet_alpha.png")
    assert payload["review_video"] == str(tmp_path / "sprite_preview.mp4")
    assert payload["master_video"] == str(tmp_path / "sprite_preview_prores.mov")
    assert payload["web_dir"] == str(tmp_path / "web")
    assert "Grid: 2 columns by 2 rows" in payload["prompt"]
    assert "chroma-key background" in payload["prompt"]


def test_choose_layout_for_25_frames():
    layout = choose_layout(25, frame_width=256, frame_height=256)

    assert layout["cols"] == 5
    assert layout["rows"] == 5
    assert layout["capacity"] == 25


def test_choose_layout_for_30_frames():
    layout = choose_layout(30, frame_width=256, frame_height=256)

    assert layout["cols"] * layout["rows"] >= 30
    assert layout["cols"] * 256 <= 3840
    assert layout["rows"] * 256 <= 3840


def test_choose_layout_for_rectangular_frames():
    layout = choose_layout(12, frame_width=384, frame_height=224)

    assert layout["cols"] * layout["rows"] >= 12
    assert layout["cols"] * 384 <= 3840
    assert layout["rows"] * 224 <= 3840


def test_rectangular_sprite_sheet_dry_run(capsys, tmp_path):
    code = main(
        [
            "--animation",
            "wide banner motion test",
            "--subject",
            "wide spaceship sprite",
            "--frames",
            "12",
            "--frame-width",
            "384",
            "--frame-height",
            "224",
            "--out-dir",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["size"].endswith("x896")
    assert "Each frame cell is exactly 384x224 pixels." in payload["prompt"]
