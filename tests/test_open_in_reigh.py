import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artagents.executors.open_in_reigh import run as open_in_reigh


ROOT = Path(__file__).resolve().parents[1]


class OpenInReighTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="open-reigh-tests-", dir=ROOT))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def write_outputs(self, out_dir: Path) -> tuple[bytes, bytes]:
        timeline_bytes = b'{"title":"Bob\'s cut","clips":[]}\n'
        assets_bytes = b'{"assets":{"main":{"file":"/abs/local path.mov","label":"Bob\'s asset"}}}\n'
        (out_dir / "hype.timeline.json").write_bytes(timeline_bytes)
        (out_dir / "hype.assets.json").write_bytes(assets_bytes)
        return timeline_bytes, assets_bytes

    def run_main(self, argv: list[str]) -> tuple[int | None, str, str, SystemExit | None]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        error = None
        code = None
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = open_in_reigh.main(argv)
            except SystemExit as exc:
                error = exc
        return code, stdout.getvalue(), stderr.getvalue(), error

    def test_copy_to_preserves_bytes_and_creates_directory(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        timeline_bytes, assets_bytes = self.write_outputs(out_dir)
        dest = root / "handoff"

        code, _, _, error = self.run_main(["--out", str(out_dir), "--copy-to", str(dest), "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertEqual((dest / "hype.timeline.json").read_bytes(), timeline_bytes)
        self.assertEqual((dest / "hype.assets.json").read_bytes(), assets_bytes)

    def test_probe_uses_public_timelines_first(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        self.write_outputs(out_dir)
        fake_reigh = root / "reigh"
        (fake_reigh / "public" / "timelines").mkdir(parents=True)

        code, _, _, error = self.run_main(["--out", str(out_dir), "--reigh-app", str(fake_reigh), "--name", "demo", "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertTrue((fake_reigh / "public" / "timelines" / "demo" / "hype.timeline.json").exists())
        self.assertTrue((fake_reigh / "public" / "timelines" / "demo" / "hype.assets.json").exists())

    def test_probe_falls_back_to_public_demos(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        self.write_outputs(out_dir)
        fake_reigh = root / "reigh"
        (fake_reigh / "public" / "demos").mkdir(parents=True)

        code, _, _, error = self.run_main(["--out", str(out_dir), "--reigh-app", str(fake_reigh), "--name", "demo", "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertTrue((fake_reigh / "public" / "demos" / "demo" / "hype.timeline.json").exists())
        self.assertTrue((fake_reigh / "public" / "demos" / "demo" / "hype.assets.json").exists())

    def test_no_probe_match_prints_manual_handoff_and_writes_nothing(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        self.write_outputs(out_dir)
        fake_reigh = root / "reigh"
        fake_reigh.mkdir()

        code, stdout, _, error = self.run_main(["--out", str(out_dir), "--reigh-app", str(fake_reigh), "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertIn("public.timelines", stdout)
        self.assertIn("SupabaseDataProvider", stdout)
        self.assertTrue("timeline-assets" in stdout or "local absolute paths" in stdout)
        self.assertEqual(list(fake_reigh.rglob("hype.timeline.json")), [])
        self.assertEqual(list(fake_reigh.rglob("hype.assets.json")), [])

    def test_missing_required_output_file_returns_non_zero(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        (out_dir / "hype.assets.json").write_text("{}", encoding="utf-8")

        code, _, stderr, error = self.run_main(["--out", str(out_dir), "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 1)
        self.assertIn("missing required output file", stderr)

    def test_dry_run_prints_destination_without_writing_files(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        self.write_outputs(out_dir)
        dest = root / "handoff"

        code, stdout, _, error = self.run_main(["--out", str(out_dir), "--copy-to", str(dest), "--dry-run", "--timeline-id", "123e4567-e89b-12d3-a456-426614174000"])

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertIn("Would copy", stdout)
        self.assertFalse((dest / "hype.timeline.json").exists())
        self.assertFalse((dest / "hype.assets.json").exists())

    def test_print_sql_emits_upsert_and_timeline_id_is_argparse_required(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir()
        self.write_outputs(out_dir)

        code, stdout, _, error = self.run_main(
            [
                "--out",
                str(out_dir),
                "--print-sql",
                "--timeline-id",
                "123e4567-e89b-12d3-a456-426614174000",
            ]
        )

        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertIn("INSERT INTO public.timelines", stdout)
        self.assertIn("ON CONFLICT (id)", stdout)
        self.assertIn("config = EXCLUDED.config", stdout)
        self.assertIn("asset_registry = EXCLUDED.asset_registry", stdout)
        self.assertIn("Bob''s cut", stdout)
        self.assertIn("Bob''s asset", stdout)
        self.assertTrue(stdout.strip().endswith(";"))

        code, _, stderr, error = self.run_main(["--out", str(out_dir), "--print-sql"])
        self.assertIsNone(code)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 2)
        self.assertIn("--timeline-id", stderr)


if __name__ == "__main__":
    unittest.main()
