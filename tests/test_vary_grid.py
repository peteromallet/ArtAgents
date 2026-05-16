from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astrid.packs.builtin.orchestrators.vary_grid import run as vary_grid


def _make_grid_png(path: Path, size: int = 192) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), (16, 16, 18))
    draw = ImageDraw.Draw(img)
    cell = size // 3
    palette = [
        (220, 60, 60), (60, 200, 220), (240, 160, 40),
        (200, 80, 200), (60, 220, 120), (240, 220, 80),
        (90, 90, 240), (240, 120, 80), (80, 200, 200),
    ]
    for i in range(9):
        r, c = divmod(i, 3)
        x, y = c * cell, r * cell
        draw.rectangle((x + 4, y + 4, x + cell - 4, y + cell - 4), fill=palette[i])
    img.save(path)


class ParseCellsTest(unittest.TestCase):
    def test_single_index(self):
        self.assertEqual(vary_grid.parse_cells("4", 9), [4])

    def test_comma_list(self):
        self.assertEqual(vary_grid.parse_cells("1,2", 9), [1, 2])

    def test_range(self):
        self.assertEqual(vary_grid.parse_cells("1-3", 9), [1, 2, 3])

    def test_mixed(self):
        self.assertEqual(vary_grid.parse_cells("1,3-5,9", 9), [1, 3, 4, 5, 9])

    def test_all(self):
        self.assertEqual(vary_grid.parse_cells("all", 4), [1, 2, 3, 4])

    def test_dedupes_and_preserves_order(self):
        self.assertEqual(vary_grid.parse_cells("3,1,3,2", 9), [3, 1, 2])

    def test_rejects_out_of_bounds(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            vary_grid.parse_cells("10", 9)

    def test_rejects_zero(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            vary_grid.parse_cells("0", 9)

    def test_rejects_empty(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            vary_grid.parse_cells("", 9)


class DetectSourceLayoutTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="vary-grid-layout-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def test_reads_from_logo_manifest_sibling(self):
        d = self.make_tempdir()
        grid = d / "grid.png"
        grid.write_bytes(b"\x89PNG\r\n")
        (d / "logo-manifest.json").write_text(json.dumps({"count": 4, "candidates": [{}, {}, {}, {}]}))
        rows, cols = vary_grid.detect_source_layout(grid, None, None)
        self.assertEqual((rows, cols), (2, 2))

    def test_falls_back_to_3x3_with_no_manifest(self):
        d = self.make_tempdir()
        grid = d / "grid.png"
        grid.write_bytes(b"\x89PNG\r\n")
        rows, cols = vary_grid.detect_source_layout(grid, None, None)
        self.assertEqual((rows, cols), (3, 3))

    def test_explicit_overrides_take_priority(self):
        d = self.make_tempdir()
        grid = d / "grid.png"
        grid.write_bytes(b"\x89PNG\r\n")
        (d / "logo-manifest.json").write_text(json.dumps({"count": 9}))
        rows, cols = vary_grid.detect_source_layout(grid, 2, 4)
        self.assertEqual((rows, cols), (2, 4))


class DryRunSmokeTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="vary-grid-smoke-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def _patch_network(self):
        for fn in ("_http_post_json",):
            patcher = mock.patch.object(
                vary_grid, fn, side_effect=AssertionError("network call in dry-run")
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            vary_grid, "_load_env_var", side_effect=AssertionError("env lookup in dry-run")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_writes_artifacts_and_ref_crops(self):
        d = self.make_tempdir()
        grid = d / "src_grid.png"
        _make_grid_png(grid)
        out = d / "out"
        self._patch_network()

        rc = vary_grid.main(
            [
                "--from", str(grid),
                "--cells", "4,5",
                "--ideas", "magic hands, sparkles",
                "--out", str(out),
                "--count", "3",
                "--dry-run",
            ]
        )
        self.assertEqual(rc, 0)

        for name in ("vary-plan.json", "concepts.json", "prompts.json", "vary-manifest.json", "grid.png"):
            self.assertTrue((out / name).is_file(), f"missing {name}")

        plan = json.loads((out / "vary-plan.json").read_text())
        self.assertEqual(plan["picked_cells"], [4, 5])
        self.assertEqual(plan["count"], 3)

        # source cells + refs were materialised
        for i in range(1, 10):
            self.assertTrue((out / "source_cells" / f"cell-{i:03d}.png").is_file())
        for i in (1, 2):
            self.assertTrue((out / "refs" / f"ref-{i:03d}.png").is_file())

        manifest = json.loads((out / "vary-manifest.json").read_text())
        self.assertEqual(len(manifest["refs"]), 2)
        self.assertEqual(manifest["refs"][0]["source_cell_index"], 4)
        self.assertEqual(manifest["refs"][1]["source_cell_index"], 5)
        self.assertTrue(manifest["grid"]["placeholder"])


class NoKimiPromptTest(unittest.TestCase):
    def test_brief_appears_in_composite_prompt(self):
        prompt = vary_grid.build_no_kimi_prompt("hands raised, sparkles", 9, 1)
        self.assertIn("hands raised, sparkles", prompt)
        self.assertIn("3x3", prompt)
        self.assertIn("reference image", prompt)


if __name__ == "__main__":
    unittest.main()
