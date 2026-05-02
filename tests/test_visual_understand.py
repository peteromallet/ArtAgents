from __future__ import annotations

import json

from PIL import Image

from artagents.executors.visual_understand.run import main


def test_visual_understand_builds_numbered_contact_sheet(capsys, tmp_path):
    images = []
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255)), start=1):
        path = tmp_path / f"image-{index}.jpg"
        Image.new("RGB", (320, 180), color).save(path)
        images.extend(["--image", str(path)])

    sheet = tmp_path / "sheet.jpg"
    code = main(
        [
            "--query",
            "What should be removed?",
            *images,
            "--contact-sheet",
            str(sheet),
            "--cols",
            "2",
            "--tile-width",
            "200",
            "--dry-run",
        ]
    )

    assert code == 0
    assert sheet.is_file()
    with Image.open(sheet) as rendered:
        assert rendered.size == (400, 324)
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == str(sheet)
    assert [frame["index"] for frame in payload["frames"]] == [1, 2, 3]
    assert payload["detail"] == "low"
    assert payload["models"] == ["gpt-4o-mini"]


def test_visual_understand_single_image_dry_run_does_not_make_sheet(capsys, tmp_path):
    image = tmp_path / "single.jpg"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(image)

    code = main(["--query", "What is here?", "--image", str(image), "--dry-run"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == str(image)
    assert len(payload["frames"]) == 1


def test_visual_understand_best_mode_dry_run(capsys, tmp_path):
    image = tmp_path / "single.jpg"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(image)

    code = main(["--query", "What is here?", "--image", str(image), "--mode", "best", "--dry-run"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["models"] == ["gpt-5.4"]


def test_visual_understand_crop_variants_contact_sheet(capsys, tmp_path):
    image = tmp_path / "wide.jpg"
    Image.new("RGB", (1600, 900), (10, 20, 30)).save(image)
    sheet = tmp_path / "crops.jpg"

    code = main(
        [
            "--query",
            "Which crop works best?",
            "--image",
            str(image),
            "--crop-aspect",
            "9:16",
            "--crop-position",
            "left,center,right",
            "--contact-sheet",
            str(sheet),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == str(sheet)
    assert [frame["label"].split()[:2] for frame in payload["frames"]] == [["9:16", "left"], ["9:16", "center"], ["9:16", "right"]]
    assert sheet.is_file()
